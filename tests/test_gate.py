from pathlib import Path

from fleet import gate
from fleet.store import write_parquet

PREV = {"open_jobs": 1_285_210, "us_open_jobs": 811_317}


def test_a_normal_run_publishes():
    # 2026-10-12 17:32: more boards, more jobs.
    assert gate.problems(PREV, {"open_jobs": 1_525_041, "us_open_jobs": 894_975, "boards": 9_576, "boards_failed": 109}) == []


def test_a_big_drop_in_open_or_us_jobs_stops_it():
    out = gate.problems(PREV, {"open_jobs": 1_100_000, "us_open_jobs": 811_000, "boards": 9_000, "boards_failed": 100})
    assert len(out) == 1 and out[0].startswith("open_jobs fell")
    out = gate.problems(PREV, {"open_jobs": 1_280_000, "us_open_jobs": 700_000, "boards": 9_000, "boards_failed": 100})
    assert len(out) == 1 and out[0].startswith("us_open_jobs fell")


def test_a_small_dip_is_normal():
    assert gate.problems(PREV, {"open_jobs": 1_200_000, "us_open_jobs": 760_000, "boards": 7_000, "boards_failed": 150}) == []


def test_many_failed_boards_stop_it():
    out = gate.problems(PREV, {"open_jobs": 1_285_000, "us_open_jobs": 811_000, "boards": 7_000, "boards_failed": 2_000})
    assert out and "boards failed" in out[0]


def test_the_first_run_has_nothing_to_compare():
    assert gate.problems(None, {"open_jobs": 10, "us_open_jobs": 5, "boards": 3, "boards_failed": 0}) == []


def test_published_counts_skip_closed_and_duplicates(tmp_path: Path):
    state = tmp_path / "state.parquet"
    write_parquet([
        {"job_id": "a", "closed_at": None, "is_us": True, "duplicate_of": None},
        {"job_id": "b", "closed_at": None, "is_us": True, "duplicate_of": "a"},
        {"job_id": "c", "closed_at": None, "is_us": False, "duplicate_of": None},
        {"job_id": "d", "closed_at": "2026-10-01", "is_us": True, "duplicate_of": None},
    ], state)
    assert gate.published_counts(state) == {"open_jobs": 3, "us_open_jobs": 1}
    assert gate.published_counts(None) is None


def test_allow_drop(monkeypatch):
    monkeypatch.setenv("FLEET_ALLOW_DROP", "1")
    assert gate.allowed()
    monkeypatch.setenv("FLEET_ALLOW_DROP", "")
    assert not gate.allowed()
