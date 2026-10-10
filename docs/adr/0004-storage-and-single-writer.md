# 0004. Storage: Parquet on Hugging Face, single writer

**Status:** accepted (2026-10-10); revisit when more than one pipeline writes.

**Context.** We want $0, no extra accounts, an open format, and something every
engine reads.

**Decision.** Parquet in the Hugging Face dataset `recrutas/us-jobs`:
`state/jobs.parquet`, `snapshots/date=…/`, `events/date=…/`, `runs/date=…/`.
Scrape workers write nothing to the dataset; one merge job writes everything for
a run in a single commit.

**Consequences.** Readers never see a half-written run. Moving to Iceberg on
object storage later is a one-time import of the same files, with the same IDs.
