"""The group-by-group merge must give exactly what history.merge gives on everything at once."""
import pyarrow.parquet as pq

from fleet.bigmerge import merge_run
from fleet.history import BoardRead, merge
from fleet.store import write_parquet

T0, T1 = "2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00"


def job(board, n, title="Engineer", desc="text", is_us=True, location="Austin, TX"):
    return {"job_id": f"j_{board}_{n}", "board_id": board, "title": title, "description": desc,
            "location": location, "is_us": is_us, "content_hash": f"{title}|{desc}|{location}"}


def rehash(row):
    return f"{row['title']}|{row['description']}|{row['location']}"


def scenario():
    boards = [f"greenhouse:co{i}" for i in range(40)]
    prev_rows = [job(b, n) for b in boards for n in range(6)]
    prev = {r["job_id"]: {**r, "first_seen": T0, "last_seen": T0, "closed_at": None} for r in prev_rows}
    rows, runs = [], []
    for i, b in enumerate(boards):
        if i % 10 == 0:
            runs.append({"board_id": b, "status": "error", "error": "boom"})       # failed read
            continue
        if i % 10 == 1:
            runs.append({"board_id": b, "status": "ok", "error": None})            # suspect empty
            continue
        keep = [job(b, n) for n in range(5)]                                         # job 5 closes
        keep[0] = job(b, 0, title="Senior Engineer")                                 # a change
        keep[1] = job(b, 1, desc=None, location=None)                                # carried, not a change
        keep.append(job(b, 9, is_us=i % 2 == 0))                                     # opened
        rows += keep
        runs.append({"board_id": b, "status": "ok", "error": None})
    rows += [job("lever:new", 1)]
    runs.append({"board_id": "lever:new", "status": "ok", "error": None})
    return prev, rows, runs


def test_group_merge_equals_all_at_once(tmp_path):
    prev, rows, runs = scenario()
    by_board = {}
    for r in rows:
        by_board.setdefault(r["board_id"], {})[r["job_id"]] = r
    expected = merge(prev, [BoardRead(r["board_id"], r["status"] == "ok", by_board.get(r["board_id"], {}), r["error"])
                            for r in runs], T1, rehash=rehash)

    write_parquet(list(prev.values()), tmp_path / "prev.parquet")
    write_parquet(rows[: len(rows) // 2], tmp_path / "in" / "rows-000.parquet")
    write_parquet(rows[len(rows) // 2:], tmp_path / "in" / "rows-001.parquet")
    out = tmp_path / "out"
    out.mkdir()
    got = merge_run(sorted((tmp_path / "in").glob("rows-*.parquet")), runs, tmp_path / "prev.parquet", T1,
                    rehash, out, groups=7)

    state = {r["job_id"]: r for r in pq.read_table(out / "state.parquet").to_pylist()}
    assert state == expected.state
    key = lambda e: (e["job_id"], e["event"])
    assert sorted(got["events"], key=key) == sorted(expected.events, key=key)
    assert sorted(got["suspect_boards"]) == sorted(expected.suspect_boards)
    assert got["open_jobs"] == sum(1 for s in expected.state.values() if s["closed_at"] is None)
    assert got["jobs_read"] == len(rows)
    events = {e["event"] for e in got["events"]}
    assert events == {"opened", "changed", "closed"}
    snap = pq.read_table(out / "snapshot.parquet")
    assert snap.num_rows == len(rows) and "description" not in snap.column_names


def test_first_run_without_state(tmp_path):
    rows = [job("ashby:a", n) for n in range(3)]
    write_parquet(rows, tmp_path / "rows-000.parquet")
    out = tmp_path / "out"
    out.mkdir()
    got = merge_run([tmp_path / "rows-000.parquet"], [{"board_id": "ashby:a", "status": "ok", "error": None}],
                    None, T1, rehash, out, groups=4)
    state = pq.read_table(out / "state.parquet").to_pylist()
    assert len(state) == 3 and all(s["first_seen"] == T1 and s["closed_at"] is None for s in state)
    assert got["open_jobs"] == 3 and got["us_open_jobs"] == 3
