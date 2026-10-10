"""Command line: `scrape` a shard, then `merge` all shards into the dataset.

    python -m fleet.cli scrape --shard 0 --of 4 --out out/
    python -m fleet.cli merge --in out/ [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import registry, store
from .bigmerge import merge_run
from .rows import content_hash


def cmd_scrape(args: argparse.Namespace) -> int:
    from .scrape import read_boards
    boards = registry.shard(registry.load(), args.shard, args.of)
    if args.limit:
        boards = boards[: args.limit]
    print(f"shard {args.shard}/{args.of}: {len(boards)} boards")
    rows, runs = asyncio.run(read_boards(boards))
    out = Path(args.out)
    store.write_parquet(rows, out / f"rows-{args.shard:03d}.parquet")
    store.write_parquet(runs, out / f"runs-{args.shard:03d}.parquet")
    status = Counter(r["status"] for r in runs)
    print(f"shard {args.shard}: {len(rows)} jobs · boards {dict(status)}")
    for r in runs:
        if r["status"] != "ok":
            print(f"  ! {r['board_id']}: {r['error']}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    src = Path(args.inp)
    row_files = sorted(src.rglob("rows-*.parquet"))
    runs = [r for f in sorted(src.rglob("runs-*.parquet")) for r in store.read_parquet(f)]
    if not runs:
        print("no run records found; nothing to merge")
        return 1
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    day = now[:10]

    out = store.tmpdir()
    state_file = Path(args.state) if args.state else store.state_file()
    result = merge_run(row_files, runs, state_file, now, content_hash, out)
    for run in runs:
        run["suspect_empty"] = run["board_id"] in result["suspect_boards"]

    stamp = now.replace(":", "")
    # Snapshots are slim (no descriptions): the full text lives in state, and changes are
    # events. Keeps daily storage small at thousands of boards.
    files = {
        store.STATE_PATH: out / "state.parquet",
        f"snapshots/date={day}/{stamp}.parquet": out / "snapshot.parquet",
        f"events/date={day}/{stamp}.parquet": out / "events.parquet",
        f"runs/date={day}/{stamp}.parquet": out / "runs.parquet",
    }
    files = {dest: path for dest, path in files.items() if path.exists() or path.name == "runs.parquet"}
    store.write_parquet(runs, files[f"runs/date={day}/{stamp}.parquet"])

    open_jobs = result["open_jobs"]
    summary = {
        "boards": len(runs), "boards_ok": sum(r["status"] == "ok" for r in runs),
        "boards_failed": sum(r["status"] == "error" for r in runs),
        "boards_unavailable": sum(r["status"] == "unavailable" for r in runs),
        "suspect_empty": result["suspect_boards"],
        "us_open_jobs": result["us_open_jobs"], "jobs_read": result["jobs_read"], "open_jobs": open_jobs,
        "events": dict(Counter(e["event"] for e in result["events"])),
    }
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        print(f"dry run: files left in {out}")
        return 0
    url = store.commit_run(files, f"Run {now}: {summary['boards_ok']}/{summary['boards']} boards, "
                                  f"{open_jobs} open jobs, events {summary['events']}")
    print(f"committed: {url}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="fleet")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--of", type=int, required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--limit", type=int, default=0)
    m = sub.add_parser("merge")
    m.add_argument("--in", dest="inp", required=True)
    m.add_argument("--state", help="local previous state (tests / dry runs)")
    m.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return cmd_scrape(args) if args.cmd == "scrape" else cmd_merge(args)


if __name__ == "__main__":
    raise SystemExit(main())
