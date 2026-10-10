"""Infra check: is everything the fleet needs in place? Scrapes nothing.

Run it from the "Infra check" workflow (Actions tab) or locally:

    python -m fleet.check
"""
from __future__ import annotations

import importlib.metadata as md
import os
import sys

DATASET = os.environ.get("HF_DATASET", "recrutas/us-jobs")
results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        results.append((name, True, fn() or "ok"))
    except Exception as err:  # noqa: BLE001 - report every failure, keep going
        results.append((name, False, f"{type(err).__name__}: {err}"[:200]))


def python_version() -> str:
    if sys.version_info < (3, 11):
        raise RuntimeError(f"needs Python 3.11+, have {sys.version.split()[0]}")
    return sys.version.split()[0]


def library() -> str:
    import ats_scrapers  # noqa: F401
    from ats_scrapers.scrapers import ScraperRegistry  # noqa: F401
    return f"ats-scrapers {md.version('ats-scrapers')}"


def hugging_face() -> str:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN secret is not set")
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    who = api.whoami()["name"]
    api.repo_info(DATASET, repo_type="dataset")
    return f"signed in as {who}; dataset {DATASET} reachable"


check("Python", python_version)
check("ats-scrapers library", library)
check("Hugging Face", hugging_face)

width = max(len(n) for n, _, _ in results)
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
