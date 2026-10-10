# 0006. Provenance on every row

**Status:** accepted (2026-10-10)

**Decision.** Every job row carries `source_url`, `fetched_at`,
`scraper` (class), `scraper_version`, `collection_method`
(`public_api` · `html` · `tls_impersonation` · `stealth_browser`) and
`schema_version`. Every board read produces a run record (status, job count,
duration, error).

**Consequences.** Any number can be traced to where and how it was collected,
which is what data buyers and takedown requests need.
