"""Fixes for ats-scrapers scrapers broken by a source change, until upstream ships them (ADR 0007).

Each patch is the smallest change that makes the pinned scraper read the source again, and
is removed once a released ats-scrapers version includes an equivalent fix.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta


def get_scraper(ats: str, scraper_input: str):
    """ats_scrapers.scrapers.get_scraper, with the patched scrapers swapped in."""
    from ats_scrapers.scrapers import get_scraper as upstream

    if ats == "bamboohr":
        return _bamboohr()(scraper_input)
    if ats == "workday":
        return _workday()(scraper_input)
    return upstream(ats, scraper_input)


def parse_bamboohr_widget(text: str, slug: str) -> list[dict] | None:
    """Positions from BambooHR's JSON widget, or None when the response is the older HTML.

    Since 2026 /jobs/embed2.php returns {"departments": [{"label", "positions": [{"id", "name",
    "url", "location"}]}]}; ats-scrapers 0.3.0 only parses the HTML form and reads 0 jobs.
    """
    if not text.lstrip().startswith("{"):
        return None
    data = json.loads(text)
    out, seen = [], set()
    for dept in data.get("departments") or []:
        for pos in dept.get("positions") or []:
            ats_id, title = str(pos.get("id") or "").strip(), (pos.get("name") or "").strip()
            if not ats_id or not title or ats_id in seen:
                continue
            seen.add(ats_id)
            out.append({
                "ats_id": ats_id,
                "title": title,
                "url": pos.get("url") or f"https://{slug}.bamboohr.com/careers/{ats_id}",
                "location": (pos.get("location") or "").strip() or None,
                "department": (dept.get("label") or "").strip() or None,
            })
    return out


def _bamboohr():
    from ats_scrapers.models import ATSType, Job
    from ats_scrapers.scrapers.bamboohr import BambooHRScraper

    class PatchedBambooHRScraper(BambooHRScraper):
        def _parse_widget(self, html: str) -> list[Job]:
            positions = parse_bamboohr_widget(html, self.company_slug)
            if positions is None:
                return super()._parse_widget(html)
            now = datetime.now(UTC)
            return [Job(company=self.company_slug, ats_type=ATSType.BAMBOOHR, posted_at=None,
                        fetched_at=now, **p) for p in positions]

    return PatchedBambooHRScraper


_DAYS_AGO = re.compile(r"posted\s+(\d+)\s+days?\s+ago", re.IGNORECASE)


def workday_posted_at(start_date: str | None, posted_on: str | None, today: date) -> datetime | None:
    """When a Workday job was posted, or None when Workday doesn't say exactly.

    ats-scrapers 0.3.0 drops both dates Workday gives. The job's detail has `startDate`, the exact
    posting day ("2026-08-19"); the listing has `postedOn`, relative to the day it was read
    ("Posted Today", "Posted 3 Days Ago", "Posted 30+ Days Ago"). The detail's day wins; "30+" is
    not a date. Checked 2026-10-11 on NVIDIA: startDate matched postedOn on every job read.
    """
    if start_date:
        try:
            d = date.fromisoformat(str(start_date)[:10])
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        except ValueError:
            pass
    text = (posted_on or "").strip().lower()
    if not text or "+" in text:
        return None
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        m = _DAYS_AGO.search(text)
        if not m:
            return None
        days = int(m.group(1))
    d = today - timedelta(days=days)
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _workday():
    from ats_scrapers.scrapers.workday import WorkdayScraper

    class PatchedWorkdayScraper(WorkdayScraper):
        def _parse_job(self, item, base_url, company):
            job = super()._parse_job(item, base_url, company)
            raw = dict(job.raw or {})
            if item.get("postedOn"):
                raw["postedOn"] = item["postedOn"]
            return job.model_copy(update={"raw": raw or None})

        async def afetch(self):
            jobs = await super().afetch()
            today = datetime.now(UTC).date()
            out = []
            for job in jobs:
                raw = job.raw or {}
                when = workday_posted_at(raw.get("startDate"), raw.get("postedOn"), today)
                out.append(job.model_copy(update={"posted_at": when}) if when else job)
            return out

    return PatchedWorkdayScraper
