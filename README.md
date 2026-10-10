# jobs-fleet

Open-source pipeline that reads **US jobs directly from company career pages**
(Greenhouse, Lever, Ashby, Workday, iCIMS, Oracle, Paycom and more). No job boards,
no reposters: every job links to the employer's own posting.

Built on [ats-scrapers](https://github.com/kalil0321/ats-scrapers) (MIT) and run on
GitHub Actions. Maintained by [Recrutas](https://www.recrutas.ai).

## Status

Running daily (12:00 UTC) on 100 seed US companies across 8 hiring systems. The
foundation (stable IDs, history, provenance, one atomic commit per run) is proven;
the registry grows from here. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The data

The jobs are stored in a **private** Hugging Face dataset, `recrutas/us-jobs`, read by
[Recrutas](https://www.recrutas.ai). The code here is open; the data is not published.

| Path | What |
|---|---|
| `state/jobs.parquet` | Every job seen, with `first_seen`, `last_seen`, `closed_at` (null = still open) |
| `snapshots/date=…/` | The jobs read in each run |
| `events/date=…/` | `opened` · `changed` · `closed` · `reopened` |
| `runs/date=…/` | One record per board per run: status, job count, duration, error |

Every job carries its source URL, fetch time, scraper version and collection method, plus
`country_iso`, `us_state`, `city`, `is_remote` and `is_us` derived from the location text.

## Check the setup

Actions → **Infra check** → Run workflow. It checks Python, the scraper library and
access to the Hugging Face dataset, and scrapes nothing.

## Employers

Each job carries its source URL on the employer's site. If you'd like your postings
removed, open an issue with the company name and we'll take them out.

## License

Code: MIT. The job data is private.
