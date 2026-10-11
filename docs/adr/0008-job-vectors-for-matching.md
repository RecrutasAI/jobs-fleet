# 0008. Job vectors here, so matching runs outside the Recrutas server

**Status:** accepted (2026-10-11)

**Decision.** After each Fleet run, the `Job vectors` workflow embeds every open US job
that is new or changed and commits `vectors/jobs.parquet` (job_id, content_hash, 384
float16 values) to the private dataset. It uses Recrutas's model and text exactly
(bge-small-en-v1.5, full-precision ONNX, mean pooling, normalised; title, company and
the first 1,000 characters of the description), so a Fleet vector and a Recrutas resume
vector are directly comparable (checked on production jobs: cosine 1.0).

**Why.** The Recrutas server has 2 CPUs and 1.9 GB of RAM and serves users. Embedding
875K jobs there would take days of its CPU; on free public runners it is a one-time
~1,600 runner-minutes (about 80 minutes across 20 shards), then a few minutes a day.
The matcher reads these vectors; the server only receives finished results.

**Consequences.** Jobs holding the dataset token install only the embedding libraries,
never the scraper package. A job without a vector is simply not matched until the next
run. Changing the model or the text means re-embedding everything, in step with Recrutas.
