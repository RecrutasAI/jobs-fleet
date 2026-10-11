"""History and events (ADR 0003). Pure functions: no I/O, fully unit-tested.

A job closes only when its board was read successfully and the job is absent.
A failed read, or a board that suddenly returns nothing after having jobs,
keeps the board's jobs open and is flagged instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

SUSPECT_EMPTY_MIN = 5

# Fields a scraper sometimes leaves empty on one run and fills on the next (Workday skipped
# 852 descriptions on one run, 2026-10-10). Missing data never erases known data.
CARRY_FIELDS = ("description", "location", "salary_summary", "salary_min", "salary_max", "employment_type",
                "department", "team", "posted_at", "apply_url")
LOCATION_DERIVED = ("countries", "country_iso", "us_state", "city", "is_us")
PLACEHOLDER_LOCATION = re.compile(r"^\s*\d+\s+locations?\s*$", re.IGNORECASE)  # Workday's "2 Locations"


def _missing(field_name: str, value) -> bool:
    if value is None or value == "":
        return True
    return field_name == "location" and isinstance(value, str) and bool(PLACEHOLDER_LOCATION.match(value))


# The fields that make up a posting's content (rows.content_hash hashes the same ones).
CONTENT_FIELDS = ("title", "location", "apply_url", "salary_summary", "employment_type", "description")


def really_changed(prior: dict, row: dict) -> bool:
    """A change is a difference between two KNOWN values. A field filled in for the first
    time (Workday adding a description it skipped before) is new information, not a change."""
    if prior.get("content_hash") == row.get("content_hash"):
        return False
    return any(not _missing(f, prior.get(f)) and not _missing(f, row.get(f)) and prior.get(f) != row.get(f)
               for f in CONTENT_FIELDS)


def _same_day_or_next(a, b) -> bool:
    if _missing("posted_at", a) or _missing("posted_at", b) or a == b:
        return False
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days) <= 1
    except ValueError:
        return False


def fill_from_prior(row: dict, prior: dict, rehash) -> dict:
    """Keep known values where this read came back empty, then recompute the content hash."""
    filled = dict(row)
    touched = False
    for f in CARRY_FIELDS:
        if _missing(f, filled.get(f)) and not _missing(f, prior.get(f)):
            filled[f] = prior[f]
            touched = True
            if f == "location":  # the place derived from it comes along
                for d in LOCATION_DERIVED:
                    if d in prior:
                        filled[d] = prior[d]
    # A posting day read two ways (Workday's exact day one run, its "Posted 3 Days Ago" the next)
    # can differ by a day across time zones. The day already published stays.
    if _same_day_or_next(prior.get("posted_at"), filled.get("posted_at")):
        filled["posted_at"] = prior["posted_at"]
    if touched and rehash is not None:
        filled["content_hash"] = rehash(filled)
    return filled  # a board that had at least this many open jobs and now returns 0 is suspect


@dataclass
class BoardRead:
    board_id: str
    ok: bool                      # the scraper finished without error
    jobs: dict[str, dict]         # job_id -> row (must include content_hash)
    error: str | None = None


@dataclass
class MergeResult:
    state: dict[str, dict]        # job_id -> state row
    events: list[dict] = field(default_factory=list)
    suspect_boards: list[str] = field(default_factory=list)


def merge(previous: dict[str, dict], reads: list[BoardRead], now: str, rehash=None) -> MergeResult:
    """Fold one run's board reads into the previous state.

    previous: job_id -> {board_id, first_seen, last_seen, closed_at, content_hash, ...}
    """
    state = {k: dict(v) for k, v in previous.items()}
    events: list[dict] = []
    suspect: list[str] = []

    open_by_board: dict[str, set[str]] = {}
    for jid, row in previous.items():
        if row.get("closed_at") is None:
            open_by_board.setdefault(row["board_id"], set()).add(jid)

    for read in reads:
        was_open = open_by_board.get(read.board_id, set())
        if not read.ok:
            continue  # failed read: change nothing for this board
        if not read.jobs and len(was_open) >= SUSPECT_EMPTY_MIN:
            suspect.append(read.board_id)
            continue  # treat as a failed read

        for jid, row in read.jobs.items():
            prior = state.get(jid)
            if prior is None or prior.get("closed_at") is not None:
                kind = "opened" if prior is None else "reopened"
                state[jid] = {**row, "board_id": read.board_id, "first_seen": prior["first_seen"] if prior else now,
                              "last_seen": now, "closed_at": None}
                events.append({"event": kind, "job_id": jid, "board_id": read.board_id, "at": now})
            else:
                row = fill_from_prior(row, prior, rehash)
                changed = really_changed(prior, row)
                state[jid] = {**row, "board_id": read.board_id, "first_seen": prior["first_seen"],
                              "last_seen": now, "closed_at": None}
                if changed:
                    events.append({"event": "changed", "job_id": jid, "board_id": read.board_id, "at": now})

        for jid in was_open - set(read.jobs):
            state[jid] = {**state[jid], "closed_at": now}
            events.append({"event": "closed", "job_id": jid, "board_id": read.board_id, "at": now})

    return MergeResult(state=state, events=events, suspect_boards=suspect)
