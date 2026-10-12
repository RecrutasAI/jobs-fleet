"""The publish gate: a run that looks broken is not written to the dataset.

Each board already guards itself (history.SUSPECT_EMPTY_MIN: a board that suddenly reads
empty doesn't close its jobs). This guards the run as a whole: if open jobs or US open jobs
fall by more than MAX_DROP against the state already published, or more than
MAX_FAILED_SHARE of the boards read failed, the merge stops before writing, and the job
fails so GitHub emails the owner. Recrutas would otherwise close every job the bad run lost.

A deliberate drop (a registry cleanup, a vendor retired) is published with
FLEET_ALLOW_DROP=1 (the workflow's "allow_drop" input).
"""
from __future__ import annotations

import os
from pathlib import Path

import pyarrow.parquet as pq

MAX_DROP = 0.10
MAX_FAILED_SHARE = 0.25


def published_counts(state: Path | None) -> dict[str, int] | None:
    """Open and US open jobs (duplicates excluded, as the run summary counts them) in the
    state the dataset holds now; None when there is no previous state."""
    if state is None or not state.exists():
        return None
    f = pq.ParquetFile(state)
    cols = [c for c in ("closed_at", "is_us", "duplicate_of") if c in f.schema_arrow.names]
    open_jobs = us_open = 0
    for batch in f.iter_batches(batch_size=200_000, columns=cols):
        d = batch.to_pydict()
        closed = d.get("closed_at", [None] * batch.num_rows)
        us = d.get("is_us", [False] * batch.num_rows)
        dup = d.get("duplicate_of", [None] * batch.num_rows)
        for c, u, x in zip(closed, us, dup):
            if c is None:
                open_jobs += 1
                if u and not x:
                    us_open += 1
    return {"open_jobs": open_jobs, "us_open_jobs": us_open}


def problems(previous: dict[str, int] | None, summary: dict) -> list[str]:
    """Why this run shouldn't be published; empty when it looks sound."""
    out: list[str] = []
    if previous:
        for key in ("open_jobs", "us_open_jobs"):
            before, now = previous.get(key) or 0, summary.get(key) or 0
            if before and now < before * (1 - MAX_DROP):
                out.append(f"{key} fell {before:,} → {now:,} ({(before - now) / before:.0%}, limit {MAX_DROP:.0%})")
    read = (summary.get("boards") or 0)
    failed = summary.get("boards_failed") or 0
    if read and failed / read > MAX_FAILED_SHARE:
        out.append(f"{failed:,} of {read:,} boards failed ({failed / read:.0%}, limit {MAX_FAILED_SHARE:.0%})")
    return out


def allowed() -> bool:
    return os.environ.get("FLEET_ALLOW_DROP", "").strip().lower() in {"1", "true", "yes"}
