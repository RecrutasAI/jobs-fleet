# Architecture

jobs-fleet keeps an open, history-preserving dataset of jobs read directly from
company career pages. It is built to start at $0 and scale to enterprise use
without rewrites: the hard-to-change parts (identity, data model, history,
provenance, the worker contract) are fixed now; the services around them are
swappable.

```
registry/boards.csv          what to read (private dataset; read every 1-3 days by size)
        │  deterministic sharding (hash of board_id)
        ▼
scrape workers (N in parallel)   one container image; input = a shard of boards,
        │                          output = job rows + one run record per board
        ▼
merge (single writer)        compares with the previous state → events
        │                    (opened / changed / closed), new state
        ▼
dataset (Parquet)            state/ · snapshots/ · events/ · runs/
                             one atomic commit per run
```

## Today → later

| Concern | Today ($0) | Later (same contracts) |
|---|---|---|
| Registry | `registry/boards.csv` in the private dataset | Postgres control plane |
| Scheduling | GitHub Actions matrix, sharded by `board_id` hash; cadence by board size | Work queue + adaptive scheduler |
| Workers | GitHub Actions runners (+ self-hosted) | Kubernetes / Cloud Run jobs |
| Storage | Parquet on Hugging Face `recrutas/us-jobs` | Iceberg on object storage (R2/S3) |
| Query | DuckDB (`hf://` paths) | Trino / Snowflake / BigQuery |

## Invariants

1. **Stable identity.** The same posting always gets the same `job_id`
   (see ADR 0002). Never a random ID.
2. **History is never lost.** `first_seen`, `last_seen`, `closed_at`; every change
   is an event.
3. **A failed read never closes jobs.** A board that errors, or suddenly returns
   nothing after having jobs, keeps its previous jobs open and is flagged.
4. **One writer.** Workers only produce files; the merge step is the only writer,
   and it commits everything for a run at once.
5. **Provenance on every row:** source URL, fetch time, scraper version,
   collection method.
6. **Schema changes are additive** and bump `schema_version`.

See `docs/adr/` for the reasoning behind each decision.
