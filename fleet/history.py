"""History and events (ADR 0003). Pure functions: no I/O, fully unit-tested.

A job closes only when its board was read successfully and the job is absent.
A failed read, or a board that suddenly returns nothing after having jobs,
keeps the board's jobs open and is flagged instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SUSPECT_EMPTY_MIN = 5  # a board that had at least this many open jobs and now returns 0 is suspect


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


def merge(previous: dict[str, dict], reads: list[BoardRead], now: str) -> MergeResult:
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
                changed = prior.get("content_hash") != row.get("content_hash")
                state[jid] = {**row, "board_id": read.board_id, "first_seen": prior["first_seen"],
                              "last_seen": now, "closed_at": None}
                if changed:
                    events.append({"event": "changed", "job_id": jid, "board_id": read.board_id, "at": now})

        for jid in was_open - set(read.jobs):
            state[jid] = {**state[jid], "closed_at": now}
            events.append({"event": "closed", "job_id": jid, "board_id": read.board_id, "at": now})

    return MergeResult(state=state, events=events, suspect_boards=suspect)
