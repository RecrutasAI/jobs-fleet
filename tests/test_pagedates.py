from pathlib import Path

import pyarrow.parquet as pq

from fleet.pagedates import add_page_dates, parse_page_date
from fleet.store import write_parquet


def test_reads_the_date_each_source_writes():
    assert parse_page_date('{"@type":"JobPosting","datePosted": "2026-10-02","validThrough":"x"}') == "2026-10-02T00:00:00+00:00"
    assert parse_page_date('{"datePosted":"2025-12-01T17:34:42+00:00","description":""}') == "2025-12-01T17:34:42+00:00"
    assert parse_page_date('<meta itemprop="datePosted" content="Tue Oct 06 07:00:00 UTC 2026">') == "2026-10-06T07:00:00+00:00"
    assert parse_page_date('<html>no date here</html>') is None
    assert parse_page_date('"datePosted": "soon"') is None


def test_fills_only_open_undated_jobs_of_page_date_sources(tmp_path: Path):
    state = tmp_path / "state.parquet"
    write_parquet([
        {"job_id": "a", "ats": "jazzhr", "url": "https://x.applytojob.com/1", "posted_at": None, "closed_at": None},
        {"job_id": "b", "ats": "jazzhr", "url": "https://x.applytojob.com/2", "posted_at": "2026-09-01T00:00:00+00:00", "closed_at": None},
        {"job_id": "c", "ats": "jazzhr", "url": "https://x.applytojob.com/3", "posted_at": None, "closed_at": "2026-10-01"},
        {"job_id": "d", "ats": "greenhouse", "url": "https://g/4", "posted_at": None, "closed_at": None},
        {"job_id": "e", "ats": "pinpoint", "url": "https://p/5", "posted_at": None, "closed_at": None},
    ], state)
    asked = []

    async def fake(urls):
        asked.extend(urls)
        return {"https://x.applytojob.com/1": "2026-10-02T00:00:00+00:00"}   # the Pinpoint page states no date

    got = add_page_dates(state, fetch=fake)
    assert sorted(asked) == ["https://p/5", "https://x.applytojob.com/1"]
    assert got == {"asked": 2, "dated": 1}
    rows = {r["job_id"]: r["posted_at"] for r in pq.read_table(state).to_pylist()}
    assert rows == {"a": "2026-10-02T00:00:00+00:00", "b": "2026-09-01T00:00:00+00:00", "c": None, "d": None, "e": None}
