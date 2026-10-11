"""Merge a run into the state in board groups, so memory stays bounded at any fleet size.

Every job belongs to exactly one board, so history.merge gives the same answer whether it
sees all boards at once or one group at a time. The rows and the previous state are first
split by board into group files in one streaming pass; then each group is merged and
written out before the next is read. At 15K boards (1.3M jobs with descriptions) the
all-at-once merge needed more than the 16 GB a GitHub runner has (2026-10-10).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .history import BoardRead, merge
from .ids import shard_of
from .rows import UNNAMED, repair
from .store import EVENT_SCHEMA, STATE_EXTRA

GROUPS = 16
SNAPSHOT_DROP = frozenset({"description"})
ROW_GROUP = 50_000  # small row groups let the next run stream the state instead of loading it whole


def unified_schema(paths: list[Path], extra: tuple[str, ...] = ()) -> pa.Schema | None:
    """One schema across files (a column that is all-null in one file is typed by the others)."""
    schemas = [pq.read_schema(p) for p in paths]
    if extra:
        schemas.append(pa.schema([(c, pa.string()) for c in extra]))
    return pa.unify_schemas(schemas, promote_options="default") if schemas else None


def split_by_group(paths: list[Path], schema: pa.Schema, out: Path, name: str, groups: int) -> dict[int, Path]:
    """Stream the files once, writing each row to its board group's file."""
    out.mkdir(parents=True, exist_ok=True)
    writers: dict[int, pq.ParquetWriter] = {}
    files: dict[int, Path] = {}
    group_of: dict[str, int] = {}
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=20_000):  # one row group at a time
            table = pa.Table.from_batches([batch])
            table = _conform(table, schema)
            boards = table.column("board_id")
            for b in pc.unique(boards).to_pylist():
                if b not in group_of:
                    group_of[b] = shard_of(b, groups)
            by_group: dict[int, list[str]] = {}
            for b in pc.unique(boards).to_pylist():
                by_group.setdefault(group_of[b], []).append(b)
            for g, members in by_group.items():
                part = table.filter(pc.is_in(boards, value_set=pa.array(members, pa.string())))
                if g not in writers:
                    files[g] = out / f"{name}-{g:03d}.parquet"
                    writers[g] = pq.ParquetWriter(files[g], schema, compression="zstd")
                writers[g].write_table(part)
    for w in writers.values():
        w.close()
    return files


def _conform(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Add missing columns as nulls and cast to the shared schema, in schema order."""
    cols = []
    for f in schema:
        if f.name in table.column_names:
            cols.append(table.column(f.name).cast(f.type))
        else:
            cols.append(pa.nulls(len(table), f.type))
    return pa.Table.from_arrays(cols, schema=schema)


def merge_run(row_files: list[Path], runs: list[dict], state_file: Path | None, now: str, rehash,
              out: Path, groups: int = GROUPS, names: dict[str, str] | None = None) -> dict:
    """Merge one run group by group. Writes state.parquet, snapshot.parquet and events.parquet
    to `out` and returns counts plus the suspect boards."""
    work = out / "groups"
    row_files = [p for p in row_files if pq.read_metadata(p).num_rows]
    row_schema = unified_schema(row_files)
    state_paths = [state_file] if state_file is not None and state_file.exists() else []
    state_schema = unified_schema(state_paths + row_files, extra=STATE_EXTRA)
    rows_by_group = split_by_group(row_files, row_schema, work, "rows", groups) if row_files else {}
    prev_by_group = split_by_group(state_paths, state_schema, work, "prev", groups) if state_paths else {}

    runs_by_group: dict[int, list[dict]] = {}
    for run in runs:
        runs_by_group.setdefault(shard_of(run["board_id"], groups), []).append(run)

    snap_schema = pa.schema([f for f in row_schema if f.name not in SNAPSHOT_DROP]) if row_schema else None
    state_w = pq.ParquetWriter(out / "state.parquet", state_schema, compression="zstd") if state_schema else None
    snap_w = pq.ParquetWriter(out / "snapshot.parquet", snap_schema, compression="zstd") if snap_schema else None
    events: list[dict] = []
    suspect: list[str] = []
    counts = Counter()

    for g in range(groups):
        previous = {r["job_id"]: repair(r, names) for r in _read(prev_by_group.get(g))}
        rows = _read(rows_by_group.get(g))
        by_board: dict[str, dict[str, dict]] = {}
        for r in rows:
            by_board.setdefault(r["board_id"], {})[r["job_id"]] = r
        reads = [BoardRead(board_id=run["board_id"], ok=run["status"] == "ok",
                           jobs=by_board.get(run["board_id"], {}), error=run["error"])
                 for run in runs_by_group.get(g, [])]
        result = merge(previous, reads, now, rehash=rehash)
        del previous
        events.extend(result.events)
        suspect.extend(result.suspect_boards)
        state = list(result.state.values())
        counts["open_jobs"] += sum(1 for s in state if s.get("closed_at") is None)
        counts["us_open_jobs"] += sum(1 for s in state if s.get("closed_at") is None and s.get("is_us"))
        counts["jobs_read"] += len(rows)
        if state:
            state_w.write_table(pa.Table.from_pylist(state, schema=state_schema), row_group_size=ROW_GROUP)
        if rows:
            snap_w.write_table(pa.Table.from_pylist(rows, schema=snap_schema), row_group_size=ROW_GROUP)
        del state, rows, by_board, reads, result

    for w in (state_w, snap_w):
        if w is not None:
            w.close()
    pq.write_table(pa.Table.from_pylist(events, schema=EVENT_SCHEMA), out / "events.parquet", compression="zstd")
    for p in work.glob("*.parquet"):
        p.unlink()
    dups = mark_duplicates(out / "state.parquet") if state_w else {"duplicates": 0, "us_duplicates": 0}
    counts["us_open_jobs"] -= dups["us_duplicates"]
    return {**counts, **dups, "events": events, "suspect_boards": suspect}


def duplicate_key(ats: str | None, ats_job_id: str | None, url: str | None, title: str | None) -> tuple | None:
    """What makes two open rows the same posting. Oracle: the tenant's job id (ats_job_id is
    "host:id"), since one tenant's career sites each give the job its own link. Elsewhere: the same
    link and title (one link with many titles is a career page given to every job, not one job)."""
    if ats == "oracle" and ats_job_id and ":" in ats_job_id:
        return ("oracle", ats_job_id.lower())
    if url and title:
        return ("url", url, title.strip().lower())
    return None


def _rank(board_id: str, company: str | None) -> tuple:
    """Which copy is kept: a named employer first, then the lowest board id (stable across runs)."""
    named = bool((company or "").strip()) and not UNNAMED.search(company or "")
    return (0 if named else 1, board_id)


def mark_duplicates(state: Path) -> dict:
    """Set duplicate_of on every open row that repeats another open row from a different board
    (the same company registered twice: 2026-10-11, 68K US Oracle jobs counted twice). The kept
    copy has duplicate_of empty; consumers (vectors, the catalog count) skip marked rows."""
    cols = ["job_id", "board_id", "ats", "ats_job_id", "url", "title", "company_name", "closed_at"]
    best: dict[tuple, tuple] = {}
    boards_of: dict[tuple, set] = {}
    f = pq.ParquetFile(state)
    present = [c for c in cols if c in f.schema_arrow.names]
    for batch in f.iter_batches(batch_size=100_000, columns=present):
        d = batch.to_pydict()
        n_rows = batch.num_rows
        for jid, board, ats, aid, url, title, co, closed in zip(*(d.get(c, [None] * n_rows) for c in cols)):
            if closed is not None:
                continue
            key = duplicate_key(ats, aid, url, title)
            if key is None:
                continue
            cand = (*_rank(board, co), jid)
            if key not in best or cand < best[key]:
                best[key] = cand
            boards_of.setdefault(key, set()).add(board)
    keep = {k: v[-1] for k, v in best.items() if len(boards_of[k]) > 1}
    del best, boards_of

    tmp = state.with_suffix(".dedup.parquet")
    schema = f.schema_arrow
    if "duplicate_of" not in schema.names:
        schema = schema.append(pa.field("duplicate_of", pa.string()))
    w = pq.ParquetWriter(tmp, schema, compression="zstd")
    n = us = 0
    for batch in f.iter_batches(batch_size=ROW_GROUP):
        d = batch.to_pydict()
        none = [None] * batch.num_rows
        ats, aid, url, title, closed, is_us = (d.get(c, none) for c in ("ats", "ats_job_id", "url", "title", "closed_at", "is_us"))
        marks = []
        for i, jid in enumerate(d["job_id"]):
            mark = None
            if closed[i] is None:
                key = duplicate_key(ats[i], aid[i], url[i], title[i])
                winner = keep.get(key) if key is not None else None
                if winner is not None and winner != jid:
                    mark = winner
                    n += 1
                    us += bool(is_us[i])
            marks.append(mark)
        d["duplicate_of"] = marks
        w.write_table(pa.Table.from_pydict(d, schema=schema), row_group_size=ROW_GROUP)
    w.close()
    tmp.replace(state)
    return {"duplicates": n, "us_duplicates": us}


def _read(path: Path | None) -> list[dict]:
    return pq.read_table(path).to_pylist() if path is not None else []
