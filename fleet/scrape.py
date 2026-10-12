"""Read a shard of boards with ats-scrapers. Produces rows + one run record per board."""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import time
from datetime import UTC, datetime

from .patches import get_scraper
from .registry import Board
from .rows import to_row

BOARD_TIMEOUT_S = 1800  # big boards (Domino's, ~25K jobs) need ~10+ min; still bounded so one board can't hold a shard hostage
CONCURRENCY = 6         # boards read at once per worker (each board is a different site)
# Per-vendor caps within that: Workday tenants share Workday's servers and throttle us as
# one client, so only a couple at once (patches.WORKDAY_LIMITS covers retries per tenant).
VENDOR_CONCURRENCY = {"workday": 2}


MAINTENANCE_MARKERS = ("maintenance", "/outage", "/drs/outage")


def classify_failure(ats: str, error: str, redirect_to: str | None) -> str:
    """'unavailable' when the site says it's down for maintenance (not our bug), else 'error'.

    Workday sends every tenant to an outage page during its scheduled windows; seen
    2026-10-10, when 12 boards redirected to community.workday.com/maintenance-page.
    """
    if redirect_to and any(m in redirect_to.lower() for m in MAINTENANCE_MARKERS):
        return "unavailable"
    return "error"


async def _redirect_target(url: str) -> str | None:
    """Where a career page redirects, without following it. None if it doesn't or can't be read."""
    if not url:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            r = await client.get(url)
            return r.headers.get("location") if 300 <= r.status_code < 400 else None
    except Exception:  # noqa: BLE001 - the probe is best-effort; the board is already a failed read
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def read_board(board: Board, version: str, sem: asyncio.Semaphore,
                     vendor_sems: dict[str, asyncio.Semaphore] | None = None) -> tuple[list[dict], dict]:
    vendor = (vendor_sems or {}).get(board.ats)
    if vendor is None:
        return await _read_board(board, version, sem)
    async with vendor:
        return await _read_board(board, version, sem)


async def _read_board(board: Board, version: str, sem: asyncio.Semaphore) -> tuple[list[dict], dict]:
    started = time.monotonic()
    run = {"board_id": board.id, "ats": board.ats, "slug": board.slug, "started_at": _now(),
           "status": "ok", "jobs": 0, "error": None, "duration_s": 0.0, "scraper_version": version}
    rows: list[dict] = []
    async with sem:
        try:
            scraper = get_scraper(board.ats, board.scraper_input)
            jobs = await asyncio.wait_for(scraper.afetch(), timeout=BOARD_TIMEOUT_S)
            fetched = _now()
            seen: set[str] = set()
            for job in jobs:
                try:
                    row = to_row(job, ats=board.ats, slug=board.slug, board=board.id,
                                 scraper=scraper, scraper_version=version, fetched_at=fetched, company=board.name)
                except ValueError:
                    continue  # no id and no url: can't be identified, skip it
                if row["job_id"] not in seen:
                    seen.add(row["job_id"])
                    rows.append(row)
            run["jobs"] = len(rows)
        except TimeoutError:
            run.update(status="error", error=f"timed out after {BOARD_TIMEOUT_S}s")
        except Exception as err:  # noqa: BLE001 - every failure becomes a run record, never a crash
            message = f"{type(err).__name__}: {err}"[:500]
            redirect = await _redirect_target(board.careers_url) if board.ats == "workday" else None
            status = classify_failure(board.ats, message, redirect)
            run.update(status=status, error=(f"site down for maintenance (redirects to {redirect})" if status == "unavailable" else message))
    run["duration_s"] = round(time.monotonic() - started, 2)
    return rows, run


async def read_boards(boards: list[Board]) -> tuple[list[dict], list[dict]]:
    version = md.version("ats-scrapers")
    sem = asyncio.Semaphore(CONCURRENCY)
    vendor_sems = {ats: asyncio.Semaphore(n) for ats, n in VENDOR_CONCURRENCY.items()}
    results = await asyncio.gather(*(read_board(b, version, sem, vendor_sems) for b in boards))
    rows = [r for rs, _ in results for r in rs]
    runs = [run for _, run in results]
    return rows, runs
