"""Read the CloakBrowser boards (Meta, Tesla) once on a runner and print counts only.

Measurement before they go in the registry: both readers return an empty list, not an
error, when CloakBrowser is missing or blocked, so a board that "succeeds" with 0 jobs is
a failure here. Writes nothing. Run by hand: .github/workflows/cloak-probe.yml.
"""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import os
import sys

from fleet.registry import Board
from fleet.scrape import _read_board

BOARDS = {
    "meta": Board("meta", "meta", "Meta", "https://www.metacareers.com/jobs", 1),
    "tesla": Board("tesla", "tesla", "Tesla", "https://www.tesla.com/careers/search", 1),
}


async def main(names: list[str]) -> int:
    print(f"license key set: {bool(os.environ.get('CLOAKBROWSER_LICENSE_KEY'))}")
    print(f"proxy set: {bool(os.environ.get('PROXY'))}")
    version = md.version("ats-scrapers")
    bad = 0
    for name in names:
        rows, run = await _read_board(BOARDS[name], version, asyncio.Semaphore(1))
        us = sum(1 for r in rows if r.get("is_us"))
        described = sum(1 for r in rows if r.get("description"))
        linked = sum(1 for r in rows if str(r.get("url") or "").startswith("http"))
        print(f"{name}: status={run['status']} jobs={len(rows)} us={us} with_description={described} "
              f"with_link={linked} seconds={run['duration_s']} error={run['error']}")
        bad += run["status"] != "ok" or not rows
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or list(BOARDS))))
