"""Turn an ats-scrapers Job into a jobs-fleet row with provenance (ADR 0006)."""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

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


def oracle_job_url(url: str | None, ats_job_id: str | None) -> str | None:
    """The job's own page on Oracle Recruiting Cloud. The scraper gives every job the career-site
    search page (`/?mode=jobs&site_number=CX_1`), which isn't a link to the job. The id is the
    part of ats_job_id after the host ("eigx.fa.us6.oraclecloud.com:52165"). Checked 2026-10-11:
    the page opens and Oracle's job-details API returns the same title for the id. Ids can be codes
    too ("DCC035", "REQ2500019G"): the details API finds those the same way (checked 2026-10-11)."""
    if not url or not ats_job_id or "/job/" in url:
        return url
    parts = urlsplit(url)
    job = ats_job_id.rsplit(":", 1)[-1].strip()
    if not parts.netloc or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", job):
        return url
    site = dict(parse_qsl(parts.query)).get("site_number") or "CX_1"
    return f"https://{parts.netloc}/hcmUI/CandidateExperience/en/sites/{site}/job/{job}"


def to_row(job: Any, *, ats: str, slug: str, board: str, scraper: Any, scraper_version: str, fetched_at: str,
           company: str | None = None) -> dict:
    """`company` is the registry's name for the board; the scrapers often give only the slug."""
    url = _s(job.url)
    if ats == "oracle":
        url = oracle_job_url(url, _s(getattr(job, "ats_id", None)))
    row = {
        "job_id": job_id(ats, slug, getattr(job, "ats_id", None), url),
        "board_id": board,
        "ats": ats,
        "slug": slug,
        "company_name": _s(company) or _s(job.company),
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


UNNAMED = re.compile(r"oraclecloud\.com|saasfaprod", re.IGNORECASE)


def repair(row: dict, names: dict[str, str] | None = None) -> dict:
    """Bring a stored row up to today's rules. Boards are read every 1-3 days and some reads fail,
    so a fix made in to_row would otherwise reach their jobs late or never.

    Oracle: the job's own link instead of the career-site search page. Names: the registry's name
    for the board; an Oracle board the registry can't name shows its host, so it stays unnamed.
    US: a location today's rules read as US ("Mountain View, California (HQ)") is marked US. Only
    added, never removed: a stored row can't tell a country the scraper gave from one read off the
    text, so a removal waits for the board's next read (to_row).
    """
    out = dict(row)
    if not out.get("is_us") and out.get("location"):
        loc = parse_location(out["location"], out.get("is_remote"))
        if loc.is_us:
            countries = [c for c in (out.get("countries") or "").split("|") if c]
            out.update(countries="|".join(["US"] + [c for c in countries if c != "US"]),
                       country_iso=out.get("country_iso") or "US", us_state=out.get("us_state") or loc.us_state,
                       city=out.get("city") or loc.city, is_us=True)
    if out.get("ats") == "oracle":
        out["url"] = canonical_url(oracle_job_url(out.get("url"), out.get("ats_job_id"))) or out.get("url")
    if names is not None and out.get("board_id") in names:
        name = names[out["board_id"]]
        if name:
            out["company_name"] = name
        elif out.get("ats") == "oracle":
            out["company_name"] = urlsplit(out.get("url") or "").netloc or out.get("company_name")
    return out
