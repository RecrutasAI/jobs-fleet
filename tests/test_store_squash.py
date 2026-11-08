"""commit_run squashes the history and deletes only the large files old versions used; a failed
cleanup never fails the run."""
from pathlib import Path
from types import SimpleNamespace

import huggingface_hub

from fleet import store


class FakeApi:
    calls: list = []  # noqa: RUF012 - a test double that records calls
    fail_squash = False
    deleted: list = []  # noqa: RUF012

    def __init__(self, *a, **k):
        pass

    def create_commit(self, repo, operations, commit_message, repo_type):
        FakeApi.calls.append("commit")
        return SimpleNamespace(commit_url="https://huggingface.co/datasets/x/commit/abc")

    def super_squash_history(self, repo, repo_type, branch, commit_message):
        FakeApi.calls.append("squash")
        if FakeApi.fail_squash:
            raise RuntimeError("hub down")

    def dataset_info(self, repo, files_metadata):
        lfs = lambda sha: SimpleNamespace(sha256=sha)
        return SimpleNamespace(siblings=[
            SimpleNamespace(rfilename="state/jobs.parquet", lfs=lfs("cur1")),
            SimpleNamespace(rfilename="snapshot.parquet", lfs=lfs("cur2")),
            SimpleNamespace(rfilename="README.md", lfs=None),
        ])

    def list_lfs_files(self, repo, repo_type):
        return [SimpleNamespace(file_oid=o, size=s) for o, s in (("cur1", 2), ("old1", 5), ("cur2", 1), ("old2", 7))]

    def permanently_delete_lfs_files(self, repo, files, repo_type):
        FakeApi.deleted = [f.file_oid for f in files]


def _run(monkeypatch, tmp_path):
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    f = tmp_path / "a.parquet"
    f.write_bytes(b"x")
    return store.commit_run({"a.parquet": f}, "run")


def test_commit_squash_and_delete_only_unused(monkeypatch, tmp_path: Path):
    FakeApi.calls, FakeApi.fail_squash, FakeApi.deleted = [], False, []
    url = _run(monkeypatch, tmp_path)
    assert url.endswith("/abc")
    assert FakeApi.calls == ["commit", "squash"]
    assert sorted(FakeApi.deleted) == ["old1", "old2"]  # never a file the current data uses


def test_failed_cleanup_does_not_fail_the_run(monkeypatch, tmp_path: Path, capsys):
    FakeApi.calls, FakeApi.fail_squash, FakeApi.deleted = [], True, []
    _run(monkeypatch, tmp_path)
    assert FakeApi.deleted == []
    assert "history cleanup failed" in capsys.readouterr().out
