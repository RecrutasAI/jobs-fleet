"""The board registry: registry/boards.csv (ADR 0005)."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

from .ids import board_id, shard_of


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
# SuccessFactors: the recruiting host or legacy career URL). Identity still uses the slug.
URL_INPUT_ATS = frozenset({"workday", "oracle", "successfactors"})


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


def shard(boards: list[Board], index: int, of: int) -> list[Board]:
    if not 0 <= index < of:
        raise ValueError(f"shard index {index} out of range for {of} shards")
    return [b for b in boards if b.enabled and shard_of(b.id, of) == index]
