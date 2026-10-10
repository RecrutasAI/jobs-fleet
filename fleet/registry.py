"""The board registry: boards.csv, kept in the private dataset (ADR 0005).

Boards are read on a cadence set by their size: big boards hold most jobs and change
daily, while small ones take most of the run time and rarely change (2026-10-10 run:
boards under 20 jobs were 62% of read time and 5% of jobs).
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .ids import board_id, shard_of

DATASET_PATH = "registry/boards.csv"  # where the registry lives in the private dataset

# priority -> read every N days
CADENCE = {1: 1, 2: 2, 3: 3}


def _default_registry() -> Path:
    """FLEET_REGISTRY, else ./registry/boards.csv (Docker, CI), else next to the source tree."""
    if os.environ.get("FLEET_REGISTRY"):
        return Path(os.environ["FLEET_REGISTRY"])
    here = Path.cwd() / "registry" / "boards.csv"
    return here if here.exists() else Path(__file__).resolve().parent.parent / "registry" / "boards.csv"


REGISTRY = _default_registry()
COLUMNS = ["ats", "slug", "name", "careers_url", "priority", "enabled"]

# Systems whose ats-scrapers scraper takes the career page URL rather than a short id
# (Workday: https://{co}.wdN.myworkdayjobs.com/{site}; Oracle: the oraclecloud.com site;
# SuccessFactors: the recruiting host or legacy career URL; Keka: the *.keka.com/careers page;
# Recruitee: the career site, which may be a custom domain). Identity still uses the slug.
URL_INPUT_ATS = frozenset({"workday", "oracle", "successfactors", "keka", "recruitee"})


@dataclass(frozen=True)
class Board:
    ats: str
    slug: str
    name: str
    careers_url: str
    priority: int = 2
    enabled: bool = True

    @property
    def id(self) -> str:
        return board_id(self.ats, self.slug)

    @property
    def scraper_input(self) -> str:
        """What to hand the ats-scrapers scraper for this board."""
        return self.careers_url if self.ats in URL_INPUT_ATS and self.careers_url else self.slug


def load(path: Path = REGISTRY) -> list[Board]:
    boards: dict[str, Board] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("ats") or not row.get("slug"):
                continue
            b = Board(
                ats=row["ats"].strip().lower(),
                slug=row["slug"].strip(),
                name=(row.get("name") or "").strip(),
                careers_url=(row.get("careers_url") or "").strip(),
                priority=int(row.get("priority") or 2),
                enabled=(row.get("enabled") or "true").strip().lower() not in ("false", "0", "no"),
            )
            boards.setdefault(b.id, b)  # first row wins; duplicates are ignored
    return list(boards.values())


def shard(boards: list[Board], index: int, of: int, day: date | None = None) -> list[Board]:
    """This shard's enabled boards; with `day`, only the boards due that day."""
    if not 0 <= index < of:
        raise ValueError(f"shard index {index} out of range for {of} shards")
    return [b for b in boards if b.enabled and shard_of(b.id, of) == index and (day is None or due(b, day))]


def due(board: Board, day: date) -> bool:
    """Whether a board is read on `day`. Each board gets a fixed offset, so the boards of
    one cadence are spread evenly over its days instead of all landing on the same one."""
    every = CADENCE.get(board.priority, 1)
    return (day.toordinal() + shard_of(board.id, every)) % every == 0


def priority_for(open_jobs: int) -> int:
    return 1 if open_jobs >= 100 else 2 if open_jobs >= 20 else 3


def reprioritize(path: Path, runs: list[dict]) -> int:
    """Set each board's priority from this run's job count. Only clean reads count: a failed
    or suspect-empty read keeps the board's current priority. Returns how many changed."""
    counts = {r["board_id"]: int(r.get("jobs") or 0) for r in runs
              if r.get("status") == "ok" and not r.get("suspect_empty")}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or COLUMNS
        rows = list(reader)
    changed = 0
    for row in rows:
        if not row.get("ats") or not row.get("slug"):
            continue
        jobs = counts.get(board_id(row["ats"], row["slug"]))
        if jobs is None:
            continue
        new = str(priority_for(jobs))
        if (row.get("priority") or "2").strip() != new:
            row["priority"] = new
            changed += 1
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
    return changed

