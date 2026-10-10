# Registry

The board registry (`boards.csv`, one row per company board) is private. It lives
at `registry/boards.csv` in the dataset, not in this repo. Fleet runs download it
and pass it between jobs encrypted.

| Column | Meaning |
|---|---|
| `ats` | Hiring system, as named by ats-scrapers (`greenhouse`, `workday`, …) |
| `slug` | The company's id on that system (what ats-scrapers expects) |
| `name` | Company name |
| `careers_url` | The public career page |
| `priority` | How often it's read: 1 daily, 2 every 2 days, 3 every 3 days. Set by each run from the board's size |
| `enabled` | `false` pauses a board without deleting its history |

To change it, download, edit, upload. Avoid 12:00–13:00 UTC: each run writes the
registry back with updated priorities, which would overwrite an edit made meanwhile.

```bash
hf download recrutas/us-jobs registry/boards.csv --repo-type dataset --local-dir .
FLEET_REGISTRY=registry/boards.csv python tools/import_directory.py --ats greenhouse   # bulk import, optional
hf upload recrutas/us-jobs registry/boards.csv registry/boards.csv --repo-type dataset
```

Local runs read `FLEET_REGISTRY`, else `registry/boards.csv` (git-ignored).
