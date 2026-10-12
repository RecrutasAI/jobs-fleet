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
    if ats == "apple":
        _patch_apple_locations()
    return upstream(ats, scraper_input)


def apple_location(entry: dict) -> str | None:
    """One Apple location as "Place, State, Country". Apple's records put the place in `name`
    ("Cupertino") with `city` and `stateProvince` empty and the country in `countryName`, so
    `name` alone can't be placed: 4,840 of 4,868 jobs read as not-US (2026-10-12)."""
    name = (entry.get("name") or "").strip()
    place = name or (entry.get("city") or "").strip()
    parts = [place, (entry.get("stateProvince") or "").strip(), (entry.get("countryName") or "").strip()]
    out: list[str] = []
    for p in parts:
        if p and not any(p.lower() in q.lower() for q in out):   # "India" named twice, or a name that already says it
            out.append(p)
    return ", ".join(out) or None


def _patch_apple_locations() -> None:
    """Swap ats_scrapers' Apple location decoder for one that keeps state and country."""
    from ats_scrapers.scrapers import apple

    if getattr(apple, "_fleet_patched", False):
        return

    def decode(item: dict) -> list[str]:
        out: list[str] = []
        for entry in item.get("locations") or item.get("locationsList") or []:
            label = apple_location(entry) if isinstance(entry, dict) else (entry.strip() if isinstance(entry, str) else None)
            if label and label not in out:
                out.append(label)
        if not out and isinstance(item.get("location"), str) and item["location"].strip():
            out.append(item["location"].strip())
        return out

    apple._decode_locations = decode
    apple._fleet_patched = True


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


# Workday throttles by IP, and every shard reads from the same GitHub Actions address
# ranges. ats-scrapers 0.3.0 gives up after 3 retries ~1, 1.5 and 2 s apart (~5 s), so a
# throttled tenant fails outright: 183 boards on 2026-10-11, 139 of them on the first page,
# all of which answered normally when probed one request at a time. Patient retries
# (1, 2, 4 ... 60 s; ~2 min in all) and fewer requests at once per tenant.
WORKDAY_LIMITS = {"MAX_RETRIES": 7, "RETRY_BACKOFF": 2.0, "MAX_RETRY_DELAY": 60.0, "MAX_CONCURRENCY": 3}


def tune_workday() -> None:
    """Apply WORKDAY_LIMITS to the upstream module (its methods read these at call time)."""
    import ats_scrapers.scrapers.workday as upstream

    for name, value in WORKDAY_LIMITS.items():
        setattr(upstream, name, value)


def _workday():
    from ats_scrapers.scrapers.workday import WorkdayScraper

    tune_workday()

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
