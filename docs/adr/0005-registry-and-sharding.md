# 0005. Private registry, deterministic sharding, cadence by size

**Status:** accepted (2026-10-10); amended 2026-10-10 (registry made private; cadence)

**Decision.** `boards.csv` lists every board (ats, slug, name, careers_url,
priority, enabled). It lives at `registry/boards.csv` in the private dataset, not
in this public repo. Shard = `sha256(board_id) mod N`, so a board always lands in
the same shard for a given N.

Each board is read every 1, 2 or 3 days by priority, set after every run from the
board's open jobs: 100+ daily, 20–99 every 2 days, under 20 every 3 days. Failed
reads keep the old priority. A fixed hash offset spreads each cadence evenly over
its days. Unread boards are untouched by the merge, so nothing closes early.

**Why.** On the 2026-10-10 run, boards under 20 jobs were 62% of read time and 5%
of jobs; boards with 100+ jobs held 81% of jobs and took 10% of the time.

**Consequences.** Adding companies is an upload to the dataset, not a pull
request. A closed posting on a small board is noticed up to 3 days later.
A manual run with `all_boards` reads everything.
