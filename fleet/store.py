"""Dataset storage: Parquet on Hugging Face, one atomic commit per run (ADR 0004)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DATASET = os.environ.get("HF_DATASET", "recrutas/us-jobs")
STATE_PATH = "state/jobs.parquet"
STATE_EXTRA = ["first_seen", "last_seen", "closed_at"]


EVENT_SCHEMA = pa.schema([("event", pa.string()), ("job_id", pa.string()), ("board_id", pa.string()), ("at", pa.string())])


def write_parquet(rows: list[dict], path: Path, schema: pa.Schema | None = None) -> None:
    """Write rows; with a schema, an empty list still produces a typed, readable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema) if schema is not None else pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")


def read_parquet(path: Path) -> list[dict]:
    return pq.read_table(path).to_pylist() if path.exists() else []


def load_state(local: Path | None = None) -> dict[str, dict]:
    """Previous state: from a local file (tests, dry runs) or the dataset."""
    if local is not None:
        rows = read_parquet(local)
    else:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import EntryNotFoundError
        try:
            rows = read_parquet(Path(hf_hub_download(DATASET, STATE_PATH, repo_type="dataset")))
        except EntryNotFoundError:
            rows = []  # first run
    return {r["job_id"]: r for r in rows}


def state_file() -> Path | None:
    """The dataset's current state file, downloaded; None on the first run."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError
    try:
        return Path(hf_hub_download(DATASET, STATE_PATH, repo_type="dataset"))
    except EntryNotFoundError:
        return None


def commit_run(files: dict[str, Path], message: str) -> str:
    """Upload every file for a run in ONE commit, so readers never see half a run."""
    from huggingface_hub import CommitOperationAdd, HfApi
    ops = [CommitOperationAdd(path_in_repo=dest, path_or_fileobj=str(src)) for dest, src in files.items()]
    info = HfApi().create_commit(DATASET, operations=ops, commit_message=message, repo_type="dataset")
    return info.commit_url


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="fleet-"))
