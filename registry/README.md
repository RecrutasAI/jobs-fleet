# Registry

`boards.csv` lists every career board the fleet reads: one row per company board.

| Column | Meaning |
|---|---|
| `ats` | Hiring system, as named by ats-scrapers (`greenhouse`, `workday`, …) |
| `slug` | The company's id on that system (what ats-scrapers expects) |
| `name` | Company name |
| `careers_url` | The public career page |
| `priority` | 1 = read most often, 3 = least (used by the scheduler later) |
| `enabled` | `false` pauses a board without deleting its history |

To add a company, open a pull request with a new row. Bulk imports use
`tools/import_directory.py` (US companies from the ats-scrapers company directory:
the list only, never their job data). The first 100 boards are a
reproducible sample (seed `20261010`) of mid-sized US companies from the
[ats-scrapers](https://github.com/kalil0321/ats-scrapers) company lists.
