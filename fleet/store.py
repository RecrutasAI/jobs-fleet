"""Dataset storage: Parquet on Hugging Face, one atomic commit per run (ADR 0004)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DATASET = os.environ.get("HF_DATASET", "recrutas/us-jobs")
STATE_PATH = "state/jobs.parquet"
STATE_EXTRA = ["first_seen", "last_seen", "closed_at", "duplicate_of"]


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
    squash_history()
    return info.commit_url


def squash_history() -> None:
    """Keep only the latest version of the dataset.

    Every run adds about 2.5 GB of new Parquet and Hugging Face keeps every old version, so the
    private dataset hit its storage limit and every merge from Oct 30 to Nov 8, 2026 was refused
    ("Private storage limit reached"). Nothing reads old versions (readers use main), so squashing
    after each commit keeps storage at about one copy. A failed squash is only a warning: the run's
    data is already committed, and the next run squashes again.
    """
    from huggingface_hub import HfApi
    try:
        HfApi().super_squash_history(DATASET, repo_type="dataset", branch="main",
                                     commit_message="Keep only the latest version (storage)")
    except Exception as err:  # noqa: BLE001 - never fail a committed run over housekeeping
        print(f"::warning::history squash failed, storage will grow until the next run squashes: {err}")


def download(path_in_repo: str) -> Path | None:
    """A file from the dataset, or None if it doesn't exist yet."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError
    try:
        return Path(hf_hub_download(DATASET, path_in_repo, repo_type="dataset"))
    except EntryNotFoundError:
        return None


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="fleet-"))
