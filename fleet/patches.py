"""Fixes for ats-scrapers scrapers broken by a source change, until upstream ships them (ADR 0007).

Each patch is the smallest change that makes the pinned scraper read the source again, and
is removed once a released ats-scrapers version includes an equivalent fix.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime


def get_scraper(ats: str, scraper_input: str):
    """ats_scrapers.scrapers.get_scraper, with the patched scrapers swapped in."""
    from ats_scrapers.scrapers import get_scraper as upstream

    if ats == "bamboohr":
        return _bamboohr()(scraper_input)
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
