"""Stable identity (ADR 0002). Deterministic, so any worker computes the same IDs."""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track where a click came from; they never change the posting.
TRACKING_PARAMS = frozenset({"gh_src", "source", "src", "ref", "referrer", "lever-source", "lever-origin", "s", "jobboard", "_ga"})


def canonical_url(url: str | None) -> str:
    """Normalise a posting URL so the same page always yields the same string."""
    if not url:
        return ""
    parts = urlsplit(str(url).strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(sorted(query)), ""))


def board_id(ats: str, slug: str) -> str:
    return f"{ats.strip().lower()}:{slug.strip().lower()}"


def job_id(ats: str, slug: str, ats_job_id: str | None, url: str | None) -> str:
    """The same posting always gets the same id. Never random (the library falls back to a UUID)."""
    key = (str(ats_job_id).strip() if ats_job_id not in (None, "") else canonical_url(url))
    if not key:
        raise ValueError(f"job on {ats}:{slug} has neither an id nor a url")
    digest = hashlib.sha256(f"{ats.lower()}|{slug.lower()}|{key}".encode()).hexdigest()
    return "j_" + digest[:24]


def shard_of(board: str, shards: int) -> int:
    """Deterministic shard for a board id (ADR 0005)."""
    if shards < 1:
        raise ValueError("shards must be >= 1")
    return int(hashlib.sha256(board.encode()).hexdigest(), 16) % shards
