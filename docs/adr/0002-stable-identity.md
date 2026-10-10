# 0002. Stable identity

**Status:** accepted (2026-10-10)

**Context.** History, events and de-duplication are only as good as the IDs. The
library's `global_id` falls back to a random UUID when a source exposes no job id,
which would make the same job look new on every run.

**Decision.**
- `board_id = "<ats>:<slug>"` (lower-cased slug).
- `job_id = "j_" + sha256("<ats>|<slug>|<ats_job_id or canonical url>")[:24]`.
- Canonical URL: lower-cased scheme and host, no fragment, tracking parameters
  (`utm_*`, `gh_src`, `source`, `ref`, …) removed, no trailing slash.

**Consequences.** IDs are deterministic across runs and machines and need no
central counter, so any number of workers can compute them independently.
