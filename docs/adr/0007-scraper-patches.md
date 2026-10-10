# 0007. Patch broken scrapers locally until upstream ships the fix

**Status:** accepted (2026-10-10)

**Context.** Sources change their pages without notice. In October 2026 BambooHR's
`/jobs/embed2.php` widget switched from HTML to JSON, and ats-scrapers 0.3.0 (the latest
release) read 0 jobs from every BambooHR company without raising an error.

**Decision.** `fleet/patches.py` wraps `get_scraper` and swaps in a subclass of the upstream
scraper that changes only what broke (here, `_parse_widget` reads the JSON and falls back to
the upstream HTML parser). Each patch has tests from a real response. The same fix is offered
upstream, and the patch is deleted when a released version includes it.

**Consequences.** Upstream behaviour (detail enrichment, retries, `collection_method`) is
kept. A library upgrade must check whether each patch is still needed.
