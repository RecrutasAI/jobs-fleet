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
              out: Path, groups: int = GROUPS) -> dict:
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
        previous = {r["job_id"]: r for r in _read(prev_by_group.get(g))}
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
    return {**counts, "events": events, "suspect_boards": suspect}


def _read(path: Path | None) -> list[dict]:
    return pq.read_table(path).to_pylist() if path is not None else []
