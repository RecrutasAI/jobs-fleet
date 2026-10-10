# 0005. Registry in the repo, deterministic sharding

**Status:** accepted (2026-10-10)

**Decision.** `registry/boards.csv` lists every board (ats, slug, name,
careers_url, priority, enabled). Shard = `sha256(board_id) mod N`, so a board
always lands in the same shard for a given N.

**Consequences.** Adding a company is a reviewed pull request. Runs are
reproducible. A queue can replace sharding later without changing workers.
