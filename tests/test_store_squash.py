"""commit_run squashes the dataset history after committing, and a failed squash never fails the run."""
from pathlib import Path

import huggingface_hub

from fleet import store


class FakeApi:
    calls: list = []  # noqa: RUF012 - a test double that records calls
    fail_squash = False

    def __init__(self, *a, **k):
        pass

    def create_commit(self, repo, operations, commit_message, repo_type):
        FakeApi.calls.append(("commit", repo, len(operations)))

        class Info:
            commit_url = "https://huggingface.co/datasets/x/commit/abc"
        return Info()

    def super_squash_history(self, repo, repo_type, branch, commit_message):
        FakeApi.calls.append(("squash", repo, branch))
        if FakeApi.fail_squash:
            raise RuntimeError("hub down")


def test_commit_then_squash(monkeypatch, tmp_path: Path):
    FakeApi.calls, FakeApi.fail_squash = [], False
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    f = tmp_path / "a.parquet"
    f.write_bytes(b"x")
    url = store.commit_run({"a.parquet": f}, "run")
    assert url.endswith("/abc")
    assert [c[0] for c in FakeApi.calls] == ["commit", "squash"]
    assert FakeApi.calls[1][2] == "main"


def test_failed_squash_does_not_fail_the_run(monkeypatch, tmp_path: Path, capsys):
    FakeApi.calls, FakeApi.fail_squash = [], True
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    f = tmp_path / "a.parquet"
    f.write_bytes(b"x")
    store.commit_run({"a.parquet": f}, "run")
    assert "history squash failed" in capsys.readouterr().out
