# 0003. History, events and safe closing

**Status:** accepted (2026-10-10)

**Decision.**
- `state/` holds every known job with `first_seen`, `last_seen`, `closed_at`,
  `content_hash`.
- Each run emits events: `opened`, `changed` (content hash differs), `closed`.
- A job is closed only when its board was read **successfully** and the job is
  absent.
- A board that fails, or returns 0 jobs after having at least 5, is treated as a
  failed read: its jobs stay open and the run record flags it
  (`suspect_empty`).

**Consequences.** A broken scraper can never wipe a company's jobs; it shows up
as a flagged run instead.
