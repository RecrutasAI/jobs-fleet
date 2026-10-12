"""Posting dates read from the job's own page, for sources whose listings carry none.

JazzHR, Recruiterbox, Pinpoint and SuccessFactors list jobs without a date, but each job page
states the employer's date in schema.org markup: `"datePosted": "2026-10-02"` (JSON-LD) or
`itemprop="datePosted" content="Tue Oct 06 07:00:00 UTC 2026"`. Checked 2026-10-12 on a live
board of each. Read once per job: the date is carried from run to run (history.CARRY_FIELDS),
so only jobs still without one are fetched, at most MAX_PER_RUN per run.
"""
from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

PAGE_DATE_ATS = frozenset({"jazzhr", "recruiterbox", "pinpoint", "successfactors"})
MAX_PER_RUN = 12_000
PER_HOST = 4
TOTAL = 32

_JSONLD = re.compile(r'"datePosted"\s*:\s*"([^"]+)"')
_META = re.compile(r'itemprop=["\']datePosted["\'][^>]*content=["\']([^"\']+)["\']|content=["\']([^"\']+)["\'][^>]*itemprop=["\']datePosted["\']', re.IGNORECASE)


def parse_page_date(html: str) -> str | None:
    """The page's datePosted as an ISO timestamp (UTC), or None."""
    for m in [*_JSONLD.finditer(html), *_META.finditer(html)]:
        raw = next(g for g in m.groups() if g).strip()
        when = _parse(raw)
        if when is not None:
            return when.isoformat()
    return None


def _parse(raw: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(raw)  # Python 3.11+ reads a trailing Z
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        pass
    for fmt in ("%a %b %d %H:%M:%S UTC %Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


async def fetch_dates(urls: list[str]) -> dict[str, str]:
    """{url: datePosted} for the pages that state one. Polite: PER_HOST at a time per site."""
    import httpx
    out: dict[str, str] = {}
    hosts: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(PER_HOST))
    total = asyncio.Semaphore(TOTAL)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; jobs-fleet; +https://github.com/RecrutasAI/jobs-fleet)"}) as client:
        async def one(url: str) -> None:
            async with total, hosts[urlsplit(url).netloc]:
                try:
                    r = await client.get(url)
                except httpx.HTTPError:
                    return
            if r.status_code == 200:
                when = parse_page_date(r.text)
                if when:
                    out[url] = when
        await asyncio.gather(*(one(u) for u in urls))
    return out


def add_page_dates(state: Path, fetch=fetch_dates, limit: int = MAX_PER_RUN) -> dict:
    """Fill posted_at in `state` for open jobs of PAGE_DATE_ATS that have none."""
    f = pq.ParquetFile(state)
    cols = [c for c in ("job_id", "ats", "url", "posted_at", "closed_at") if c in f.schema_arrow.names]
    todo: dict[str, str] = {}
    for batch in f.iter_batches(batch_size=100_000, columns=cols):
        d = batch.to_pydict()
        for jid, ats, url, posted, closed in zip(d["job_id"], d["ats"], d["url"], d["posted_at"], d["closed_at"]):
            if ats in PAGE_DATE_ATS and not posted and closed is None and url and len(todo) < limit:
                todo[jid] = url
    if not todo:
        return {"asked": 0, "dated": 0}
    by_url = asyncio.run(fetch(sorted(set(todo.values()))))
    dates = {jid: by_url[url] for jid, url in todo.items() if url in by_url}
    if dates:
        tmp = state.with_suffix(".dates.parquet")
        w = pq.ParquetWriter(tmp, f.schema_arrow, compression="zstd")
        for batch in f.iter_batches(batch_size=50_000):
            d = batch.to_pydict()
            d["posted_at"] = [dates.get(j, p) for j, p in zip(d["job_id"], d["posted_at"])]
            w.write_table(pa.Table.from_pydict(d, schema=f.schema_arrow), row_group_size=50_000)
        w.close()
        tmp.replace(state)
    return {"asked": len(todo), "dated": len(dates)}
