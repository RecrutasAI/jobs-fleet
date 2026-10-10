"""Turn an ats-scrapers Job into a jobs-fleet row with provenance (ADR 0006)."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from .ids import canonical_url, job_id
from .location import parse as parse_location

SCHEMA_VERSION = 2  # v2 (2026-10-10): + countries, us_state, city, is_us; country_iso and is_remote filled from location text

# Collection method per source, from how each ats-scrapers scraper fetches (ADR 0001/0006).
STEALTH_BROWSER = frozenset({"meta", "tesla", "uber", "darwinbox", "builtin", "infojobs_es"})
HTML_SOURCES = frozenset({"icims"})

ROW_FIELDS = [
    "job_id", "board_id", "ats", "slug", "company_name", "ats_job_id", "title", "url", "apply_url",
    "location", "country_iso", "region", "is_remote", "employment_type", "department", "team",
    "requisition_id", "salary_min", "salary_max", "salary_currency", "salary_period", "salary_summary",
    "countries", "us_state", "city", "is_us",
    "description", "posted_at", "fetched_at", "content_hash",
    "scraper", "scraper_version", "collection_method", "schema_version",
]


def collection_method(ats: str, scraper: Any) -> str:
    if ats in STEALTH_BROWSER:
        return "stealth_browser"
    if getattr(type(scraper), "fetch_engine", "httpx") == "cloak":
        return "tls_impersonation"
    if ats in HTML_SOURCES:
        return "html"
    return "public_api"


def _s(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    return str(getattr(v, "value", v))


def content_hash(row: dict) -> str:
    """What counts as a change: the parts of a posting a candidate would notice."""
    parts = [row.get(k) or "" for k in ("title", "location", "apply_url", "salary_summary", "employment_type", "description")]
    return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()[:32]


def to_row(job: Any, *, ats: str, slug: str, board: str, scraper: Any, scraper_version: str, fetched_at: str) -> dict:
    url = _s(job.url)
    row = {
        "job_id": job_id(ats, slug, getattr(job, "ats_id", None), url),
        "board_id": board,
        "ats": ats,
        "slug": slug,
        "company_name": _s(job.company),
        "ats_job_id": _s(getattr(job, "ats_id", None)),
        "title": _s(job.title),
        "url": canonical_url(url),
        "apply_url": _s(getattr(job, "apply_url", None)),
        "location": _s(getattr(job, "location", None)),
        "country_iso": _s(getattr(job, "country_iso", None)),
        "region": _s(getattr(job, "region", None)),
        "is_remote": getattr(job, "is_remote", None),
        "employment_type": _s(getattr(job, "employment_type", None)),
        "department": _s(getattr(job, "department", None)),
        "team": _s(getattr(job, "team", None)),
        "requisition_id": _s(getattr(job, "requisition_id", None)),
        "salary_min": getattr(job, "salary_min", None),
        "salary_max": getattr(job, "salary_max", None),
        "salary_currency": _s(getattr(job, "salary_currency", None)),
        "salary_period": _s(getattr(job, "salary_period", None)),
        "salary_summary": _s(getattr(job, "salary_summary", None)),
        "description": _s(getattr(job, "description", None)),
        "posted_at": _s(getattr(job, "posted_at", None)),
        "fetched_at": fetched_at,
        "scraper": type(scraper).__name__,
        "scraper_version": scraper_version,
        "collection_method": collection_method(ats, scraper),
        "schema_version": SCHEMA_VERSION,
    }
    # Normalization step 1: the scrapers rarely fill the country, so derive it from the
    # location text. Not part of content_hash: adding these fields is not a posting change.
    loc = parse_location(row["location"], row["is_remote"])
    countries = list(loc.countries)
    if row["country_iso"] and row["country_iso"].upper() not in countries:
        countries.insert(0, row["country_iso"].upper())
    row.update(
        countries="|".join(countries) or None,
        country_iso=(row["country_iso"] or loc.country_iso),
        us_state=loc.us_state,
        city=loc.city,
        is_remote=bool(row["is_remote"]) or loc.is_remote,
        is_us="US" in countries,
    )
    row["content_hash"] = content_hash(row)
    return row
