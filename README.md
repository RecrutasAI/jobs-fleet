# jobs-fleet

An open, daily-updated dataset of **US jobs read directly from company career pages**
(Greenhouse, Lever, Ashby, Workday, iCIMS, Oracle, Paycom and more). No job boards,
no reposters: every job links to the employer's own posting.

Built on [ats-scrapers](https://github.com/kalil0321/ats-scrapers) (MIT) and run on
GitHub Actions. Maintained by [Recrutas](https://www.recrutas.ai).

## Status

Infrastructure setup. Nothing is scraped yet.

| Piece | Where |
|---|---|
| Code | this repo (MIT) |
| Compute | GitHub Actions (`.github/workflows/`) |
| Data | Hugging Face dataset [`recrutas/us-jobs`](https://huggingface.co/datasets/recrutas/us-jobs) (empty until the first run) |

## Check the setup

Actions → **Infra check** → Run workflow. It checks Python, the scraper library and
access to the Hugging Face dataset, and scrapes nothing.

## Employers

Each job carries its source URL on the employer's site. If you'd like your postings
removed, open an issue with the company name and we'll take them out.

## License

Code: MIT. Dataset license to be set before the first data release.
