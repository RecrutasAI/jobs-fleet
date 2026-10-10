"""Read a shard of boards with ats-scrapers. Produces rows + one run record per board."""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import time
from datetime import datetime, timezone

from .registry import Board
from .rows import to_row

BOARD_TIMEOUT_S = 600   # one slow board can't hold a shard hostage
CONCURRENCY = 6         # boards read at once per worker (each board is a different site)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def read_board(board: Board, version: str, sem: asyncio.Semaphore) -> tuple[list[dict], dict]:
    from ats_scrapers.scrapers import get_scraper  # imported here so pure modules test without it

    started = time.monotonic()
    run = {"board_id": board.id, "ats": board.ats, "slug": board.slug, "started_at": _now(),
           "status": "ok", "jobs": 0, "error": None, "duration_s": 0.0, "scraper_version": version}
    rows: list[dict] = []
    async with sem:
        try:
            scraper = get_scraper(board.ats, board.slug)
            jobs = await asyncio.wait_for(scraper.afetch(), timeout=BOARD_TIMEOUT_S)
            fetched = _now()
            seen: set[str] = set()
            for job in jobs:
                try:
                    row = to_row(job, ats=board.ats, slug=board.slug, board=board.id,
                                 scraper=scraper, scraper_version=version, fetched_at=fetched)
                except ValueError:
                    continue  # no id and no url: can't be identified, skip it
                if row["job_id"] not in seen:
                    seen.add(row["job_id"])
                    rows.append(row)
            run["jobs"] = len(rows)
        except asyncio.TimeoutError:
            run.update(status="error", error=f"timed out after {BOARD_TIMEOUT_S}s")
        except Exception as err:  # noqa: BLE001 - every failure becomes a run record, never a crash
            run.update(status="error", error=f"{type(err).__name__}: {err}"[:500])
    run["duration_s"] = round(time.monotonic() - started, 2)
    return rows, run


async def read_boards(boards: list[Board]) -> tuple[list[dict], list[dict]]:
    version = md.version("ats-scrapers")
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(read_board(b, version, sem) for b in boards))
    rows = [r for rs, _ in results for r in rs]
    runs = [run for _, run in results]
    return rows, runs
