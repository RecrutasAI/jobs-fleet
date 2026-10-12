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
# One more try for boards that failed with an error, after the rest of the shard: most
# failures are throttling (Workday "gave up after N retries", 429s) that clears within
# minutes. Timeouts, closed sites and maintenance windows aren't retried. Bounded so a shard
# keeps well inside its job limit: 109 of 9,576 boards failed on 2026-10-12.
RETRY_PAUSE_S = 60
RETRY_BOARD_TIMEOUT_S = 300
RETRY_BUDGET_S = 900


MAINTENANCE_MARKERS = ("maintenance", "/outage", "/drs/outage")
# The employer closed its job site: Paycom sends a retired portal to "jobs do not exist"
# (58 of 61 failing Paycom boards on 2026-10-12).
CLOSED_MARKERS = ("jobsnotexist",)
# Vendors whose failures are checked for a redirect that explains them.
PROBE_REDIRECT = ("workday", "paycom")


def classify_failure(ats: str, error: str, redirect_to: str | None) -> str:
    """'unavailable' when the site says it's down for maintenance (not our bug), 'closed'
    when the employer retired the job site, else 'error'.

    Workday sends every tenant to an outage page during its scheduled windows; seen
    2026-10-10, when 12 boards redirected to community.workday.com/maintenance-page.
    """
    target = (redirect_to or "").lower()
    if target and any(m in target for m in CLOSED_MARKERS):
        return "closed"
    if target and any(m in target for m in MAINTENANCE_MARKERS):
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
                     vendor_sems: dict[str, asyncio.Semaphore] | None = None,
                     timeout_s: float | None = None) -> tuple[list[dict], dict]:
    vendor = (vendor_sems or {}).get(board.ats)
    if vendor is None:
        return await _read_board(board, version, sem, timeout_s)
    async with vendor:
        return await _read_board(board, version, sem, timeout_s)


async def _read_board(board: Board, version: str, sem: asyncio.Semaphore,
                      timeout_s: float | None = None) -> tuple[list[dict], dict]:
    timeout_s = BOARD_TIMEOUT_S if timeout_s is None else timeout_s
    started = time.monotonic()
    run = {"board_id": board.id, "ats": board.ats, "slug": board.slug, "started_at": _now(),
           "status": "ok", "jobs": 0, "error": None, "duration_s": 0.0, "scraper_version": version,
           "retried": False}
    rows: list[dict] = []
    async with sem:
        try:
            scraper = get_scraper(board.ats, board.scraper_input)
            jobs = await asyncio.wait_for(scraper.afetch(), timeout=timeout_s)
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
            run.update(status="error", error=f"timed out after {timeout_s:.0f}s")
        except Exception as err:  # noqa: BLE001 - every failure becomes a run record, never a crash
            message = f"{type(err).__name__}: {err}"[:500]
            redirect = await _redirect_target(board.careers_url) if board.ats in PROBE_REDIRECT else None
            status = classify_failure(board.ats, message, redirect)
            reason = {"unavailable": f"site down for maintenance (redirects to {redirect})",
                      "closed": f"job site closed by the employer (redirects to {redirect})"}
            run.update(status=status, error=reason.get(status, message))
    run["duration_s"] = round(time.monotonic() - started, 2)
    return rows, run


async def read_boards(boards: list[Board]) -> tuple[list[dict], list[dict]]:
    version = md.version("ats-scrapers")
    sem = asyncio.Semaphore(CONCURRENCY)
    vendor_sems = {ats: asyncio.Semaphore(n) for ats, n in VENDOR_CONCURRENCY.items()}
    results = list(await asyncio.gather(*(read_board(b, version, sem, vendor_sems) for b in boards)))
    await retry_failed(boards, results, version, sem, vendor_sems)
    rows = [r for rs, _ in results for r in rs]
    runs = [run for _, run in results]
    return rows, runs


def retryable(run: dict) -> bool:
    """A failed read worth one more try: an error, not a timeout (that would just repeat)."""
    return run["status"] == "error" and not str(run.get("error") or "").startswith("timed out")


async def retry_failed(boards: list[Board], results: list[tuple[list[dict], dict]], version: str,
                       sem: asyncio.Semaphore, vendor_sems: dict[str, asyncio.Semaphore],
                       pause_s: float | None = None, board_timeout_s: float | None = None,
                       budget_s: float | None = None) -> int:
    """Read each retryable board once more (in place in `results`); returns how many now read ok.
    A board still failing, or not reached within the budget, keeps its first failure."""
    todo = [i for i, (_, run) in enumerate(results) if retryable(run)]
    if not todo:
        return 0
    pause_s = RETRY_PAUSE_S if pause_s is None else pause_s
    board_timeout_s = RETRY_BOARD_TIMEOUT_S if board_timeout_s is None else board_timeout_s
    budget_s = RETRY_BUDGET_S if budget_s is None else budget_s
    await asyncio.sleep(pause_s)

    async def again(i: int) -> tuple[int, list[dict], dict]:
        rows, run = await read_board(boards[i], version, sem, vendor_sems, timeout_s=board_timeout_s)
        return i, rows, run

    tasks = [asyncio.create_task(again(i)) for i in todo]
    done, pending = await asyncio.wait(tasks, timeout=budget_s)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    recovered = 0
    for t in done:
        i, rows, run = t.result()
        if run["status"] != "error":   # ok, or now understood (closed / maintenance)
            run["retried"] = True
            results[i] = (rows, run)
            recovered += run["status"] == "ok"
        else:
            results[i][1]["retried"] = True
    return recovered
