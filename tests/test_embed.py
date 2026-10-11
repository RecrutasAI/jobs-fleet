"""Job vectors: only open US jobs, only new or changed ones, closed jobs dropped on combine."""
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from fleet import embed as E
from fleet.store import write_parquet


def state(path: Path, rows: list[dict]) -> Path:
    write_parquet(rows, path)
    return path


def job(n, h="h1", closed=None, is_us=True, desc="Build things"):
    return {"job_id": f"j{n}", "content_hash": h, "title": f"Engineer {n}", "company_name": "Acme",
            "description": desc, "closed_at": closed, "is_us": is_us}


calls: list[list[str]] = []


def fake_embed(texts: list[str]) -> np.ndarray:
    calls.append(texts)
    v = np.ones((len(texts), E.DIM), np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_job_text_matches_recrutas():
    assert E.job_text("Nurse", "Kaiser", "x" * 1500) == "Nurse Kaiser " + "x" * 1000
    assert E.job_text("Nurse", None, None) == "Nurse  "


def test_first_run_then_incremental_then_combine(tmp_path: Path):
    calls.clear()
    s1 = state(tmp_path / "s1.parquet", [job(1), job(2), job(3, closed="2026-10-01"), job(4, is_us=False), job(5, is_us=None)])
    out1 = tmp_path / "shard1.parquet"
    assert E.embed_shard(s1, None, out1, fake_embed) == 2          # only open US jobs
    v1 = tmp_path / "v1.parquet"
    assert E.combine(s1, None, [out1], v1) == {"vectors": 2, "embedded_this_run": 2, "open_us_jobs": 2, "not_embedded_yet": 0}

    # Next day: j1 changed, j2 closed, j6 new.
    s2 = state(tmp_path / "s2.parquet", [job(1, h="h2"), job(2, closed="2026-10-02"), job(6)])
    calls.clear()
    out2 = tmp_path / "shard2.parquet"
    assert E.embed_shard(s2, v1, out2, fake_embed) == 2            # j1 (changed) and j6 (new)
    assert sorted(t.split()[1] for t in calls[0]) == ["1", "6"]
    v2 = tmp_path / "v2.parquet"
    E.combine(s2, v1, [out2], v2)
    t = pq.read_table(v2)
    assert dict(zip(t.column("job_id").to_pylist(), t.column("content_hash").to_pylist())) == {"j1": "h2", "j6": "h1"}
    vec = np.array(t.column("vector")[0].as_py(), dtype=np.float32)
    assert vec.shape == (E.DIM,) and abs(np.linalg.norm(vec) - 1) < 1e-2


def test_shards_split_the_work(tmp_path: Path):
    s = state(tmp_path / "s.parquet", [job(i) for i in range(40)])
    total = sum(E.embed_shard(s, None, tmp_path / f"o{k}.parquet", fake_embed, shard=k, of=4) for k in range(4))
    assert total == 40
    out = tmp_path / "v.parquet"
    assert E.combine(s, None, [tmp_path / f"o{k}.parquet" for k in range(4)], out)["vectors"] == 40
