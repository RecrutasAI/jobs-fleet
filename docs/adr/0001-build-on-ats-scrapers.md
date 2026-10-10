# 0001. Build on ats-scrapers, following its practices

**Status:** accepted (2026-10-10)

**Context.** [ats-scrapers](https://github.com/kalil0321/ats-scrapers) (MIT) covers
60+ sources, including the systems most US employers use (Workday, iCIMS,
Oracle, Paycom, Greenhouse, Lever, Ashby, SmartRecruiters, SuccessFactors).
Rewriting them would take months.

**Decision.** Use it as a pinned dependency, following its practices as they are,
including TLS impersonation and the stealth browser for protected sites.
Contribute fixes upstream. Fork under RecrutasAI only if upstream stops being
maintained.

**Consequences.** Every row records its `collection_method`, so consumers can
choose which methods they accept. A library upgrade is a reviewed change with a
canary run.
