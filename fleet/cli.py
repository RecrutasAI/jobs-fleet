"""Command line: `scrape` a shard, then `merge` all shards into the dataset.

    python -m fleet.cli scrape --shard 0 --of 4 --out out/ [--all]
    python -m fleet.cli merge --in out/ [--registry boards.csv] [--dry-run]

The registry is private (FLEET_REGISTRY points at a local copy). Logs are public, so they
carry counts only: board names and errors stay in the run records in the dataset.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from . import registry, store
from .bigmerge import merge_run
from .rows import content_hash


def cmd_scrape(args: argparse.Namespace) -> int:
    from .scrape import read_boards
    day = None if args.all else (date.fromisoformat(args.day) if args.day else datetime.now(UTC).date())
    boards = registry.shard(registry.load(), args.shard, args.of, day)
    if args.limit:
        boards = boards[: args.limit]
    print(f"shard {args.shard}/{args.of}: {len(boards)} boards due {day or '(all)'}")
    rows, runs = asyncio.run(read_boards(boards))
    out = Path(args.out)
    store.write_parquet(rows, out / f"rows-{args.shard:03d}.parquet")
    store.write_parquet(runs, out / f"runs-{args.shard:03d}.parquet")
    status = Counter(r["status"] for r in runs)
    print(f"shard {args.shard}: {len(rows)} jobs · boards {dict(status)}")
    kinds = Counter(f"{r['ats']}: {_error_kind(r['error'])}" for r in runs if r["status"] != "ok")
    for kind, n in kinds.most_common():
        print(f"  ! {n} × {kind}")
    return 0


def _error_kind(error: str | None) -> str:
    """The exception name only; the message can carry a board's URL or name."""
    if (error or "").startswith("timed out"):
        return "timeout"
    if (error or "").startswith("site down for maintenance"):
        return "maintenance"
    head = (error or "unknown").split(":", 1)[0].strip()
    return head if head.replace("_", "").replace(".", "").isalnum() and len(head) <= 60 else "error"


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
    names = {b.id: b.name for b in registry.load(Path(args.registry))} if args.registry else None
    from . import gate
    published = gate.published_counts(state_file)   # before this run, for the publish gate
    result = merge_run(row_files, runs, state_file, now, content_hash, out, names=names)
    # Posting dates from the job pages of sources whose listings carry none (fleet/pagedates.py).
    from .pagedates import add_page_dates
    page_dates = add_page_dates(out / "state.parquet") if (out / "state.parquet").exists() else {"asked": 0, "dated": 0}
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
    reprioritized = disabled = None
    if args.registry:
        reprioritized = registry.reprioritize(Path(args.registry), runs)
        disabled = registry.disable_closed(Path(args.registry), runs)
        files[registry.DATASET_PATH] = Path(args.registry)

    open_jobs = result["open_jobs"]
    summary = {
        "boards": len(runs), "boards_ok": sum(r["status"] == "ok" for r in runs),
        "boards_failed": sum(r["status"] == "error" for r in runs),
        "boards_unavailable": sum(r["status"] == "unavailable" for r in runs),
        "boards_closed": sum(r["status"] == "closed" for r in runs),
        "suspect_empty": len(result["suspect_boards"]),
        "us_open_jobs": result["us_open_jobs"], "jobs_read": result["jobs_read"], "open_jobs": open_jobs,
        "duplicates_marked": result.get("duplicates", 0),
        "page_dates": page_dates,
        "events": dict(Counter(e["event"] for e in result["events"])),
        "priorities_changed": reprioritized,
        "boards_disabled": disabled,
    }
    summary["retried_ok"] = sum(1 for r in runs if r.get("retried") and r["status"] == "ok")
    print(json.dumps(summary, indent=2))
    stop = gate.problems(published, summary)
    for p in stop:
        print(f"::error title=Publish gate::{p}")
    if args.dry_run:
        print(f"dry run: files left in {out}")
        return 0
    if stop and not gate.allowed():
        print("Not published: this run looks broken (above). Recrutas keeps the last good data. "
              "If the drop is intended, run again with allow_drop.")
        return 2
    url = store.commit_run(files, f"Run {now}: {summary['boards_ok']}/{summary['boards']} boards, "
                                  f"{open_jobs} open jobs, events {summary['events']}")
    print(f"committed: {url}")
    return 0


def cmd_embed(args: argparse.Namespace) -> int:
    from . import embed
    state = Path(args.state) if args.state else store.state_file()
    vectors = Path(args.vectors) if args.vectors else store.download(embed.VECTORS_PATH)
    out = Path(args.out) / f"vectors-{args.shard:03d}.parquet"
    n = embed.embed_shard(state, vectors, out, embed.load_embedder(), args.shard, args.of)
    print(f"shard {args.shard}/{args.of}: embedded {n} new or changed jobs")
    return 0


def cmd_embed_combine(args: argparse.Namespace) -> int:
    from . import embed
    state = Path(args.state) if args.state else store.state_file()
    vectors = Path(args.vectors) if args.vectors else store.download(embed.VECTORS_PATH)
    shards = sorted(Path(args.inp).rglob("vectors-*.parquet"))
    out = store.tmpdir() / "jobs.parquet"
    summary = embed.combine(state, vectors, shards, out)
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        print(f"dry run: {out}")
        return 0
    print("committed:", store.commit_run({embed.VECTORS_PATH: out},
                                          f"Job vectors: {summary['vectors']} ({summary['embedded_this_run']} new or changed)"))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="fleet")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--of", type=int, required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--day", help="read the boards due on this UTC day (default: today)")
    s.add_argument("--all", action="store_true", help="read every board, whatever its cadence")
    m = sub.add_parser("merge")
    m.add_argument("--in", dest="inp", required=True)
    m.add_argument("--state", help="local previous state (tests / dry runs)")
    m.add_argument("--registry", help="local registry: priorities are updated from this run and committed with it")
    m.add_argument("--dry-run", action="store_true")
    e = sub.add_parser("embed", help="vectors for this shard's new and changed open US jobs")
    e.add_argument("--shard", type=int, default=0)
    e.add_argument("--of", type=int, default=1)
    e.add_argument("--out", required=True)
    e.add_argument("--state", help="local state file (default: the dataset's)")
    e.add_argument("--vectors", help="local previous vectors (default: the dataset's)")
    c = sub.add_parser("embed-combine", help="merge shard vectors into vectors/jobs.parquet and commit")
    c.add_argument("--in", dest="inp", required=True)
    c.add_argument("--state")
    c.add_argument("--vectors")
    c.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return {"scrape": cmd_scrape, "merge": cmd_merge, "embed": cmd_embed, "embed-combine": cmd_embed_combine}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
