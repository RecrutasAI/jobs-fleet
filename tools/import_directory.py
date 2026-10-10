"""Add US companies from the ats-scrapers company directory to registry/boards.csv.

Takes only the companies list (name, id, career page URL), never their job data. A company
counts as US when the ats-scrapers dataset shows at least one current US job for it, matched by
its id or, where the id is opaque (Paycom's portal hashes), by its name within the same system. New
boards are appended; existing ones (same board_id) are left untouched.

    pip install duckdb
    python tools/import_directory.py --ats greenhouse ashby lever smartrecruiters
"""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

BASE = "https://storage.stapply.ai/jobhive/v1"
REGISTRY = Path(os.environ.get("FLEET_REGISTRY") or Path(__file__).resolve().parent.parent / "registry" / "boards.csv")
FIELDS = ["ats", "slug", "name", "careers_url", "priority", "enabled"]


def us_companies(ats: list[str], min_us_jobs: int) -> list[dict]:
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    systems = ", ".join(f"'{a}'" for a in ats)
    norm = "regexp_replace(lower({}), '[^a-z0-9]', '', 'g')"
    return [dict(zip(["ats", "slug", "name", "careers_url", "us_jobs"], r)) for r in con.execute(f"""
        WITH dir AS (
            SELECT ats, slug, name, url, {norm.format("split_part(slug, '/', 1)")} AS k,
                   {norm.format("name")} AS nk FROM read_parquet('{BASE}/companies.parquet')
            WHERE ats IN ({systems})),
        us AS (
            SELECT ats_type AS ats, {norm.format("company")} AS k, count(*) AS us_jobs
            FROM read_parquet('{BASE}/all.parquet')
            WHERE ats_type IN ({systems}) AND country_iso = 'US' GROUP BY 1, 2)
        SELECT d.ats, d.slug, d.name, d.url, max(u.us_jobs) AS us_jobs
        FROM dir d JOIN us u ON u.ats = d.ats AND (u.k = d.k OR u.k = d.nk)
        WHERE u.us_jobs >= {min_us_jobs} GROUP BY 1, 2, 3, 4 ORDER BY d.ats, us_jobs DESC""").fetchall()]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ats", nargs="+", required=True)
    p.add_argument("--min-us-jobs", type=int, default=1)
    args = p.parse_args()
    with open(REGISTRY, newline="") as f:
        existing = list(csv.DictReader(f))
    have = {f"{r['ats']}:{r['slug'].strip().lower()}" for r in existing}
    found = us_companies(args.ats, args.min_us_jobs)
    new = [r for r in found if f"{r['ats']}:{r['slug'].strip().lower()}" not in have]
    seen: set[str] = set()
    rows = []
    for r in new:
        key = f"{r['ats']}:{r['slug'].strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({"ats": r["ats"], "slug": r["slug"], "name": r["name"], "careers_url": r["careers_url"],
                     "priority": 2, "enabled": "true"})
    with open(REGISTRY, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerows(rows)
    print(f"{len(found)} US companies found, {len(rows)} new, registry now {len(existing) + len(rows)} boards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
