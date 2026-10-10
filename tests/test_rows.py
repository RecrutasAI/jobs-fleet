from datetime import datetime, timezone
from types import SimpleNamespace

from fleet.rows import ROW_FIELDS, collection_method, to_row


class FakeScraper:
    fetch_engine = "httpx"


class CloakScraper:
    fetch_engine = "cloak"


def fake_job(**kw):
    base = dict(url="https://job-boards.greenhouse.io/acme/jobs/1?gh_src=x", title="Engineer", company="Acme",
                ats_id="1", location="Austin, TX", country_iso="US", posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                description="Build things")
    base.update(kw)
    return SimpleNamespace(**base)


def test_row_has_every_field_and_provenance():
    row = to_row(fake_job(), ats="greenhouse", slug="acme", board="greenhouse:acme",
                 scraper=FakeScraper(), scraper_version="0.3.0", fetched_at="2026-10-10T00:00:00+00:00")
    assert set(ROW_FIELDS) <= set(row)
    assert row["url"] == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert row["collection_method"] == "public_api" and row["scraper"] == "FakeScraper"
    assert row["posted_at"] == "2026-10-01T00:00:00+00:00" and row["schema_version"] == 1


def test_content_hash_changes_only_with_content():
    kw = dict(ats="greenhouse", slug="acme", board="greenhouse:acme", scraper=FakeScraper(), scraper_version="v")
    a = to_row(fake_job(), fetched_at="t1", **kw)
    b = to_row(fake_job(), fetched_at="t2", **kw)
    c = to_row(fake_job(title="Senior Engineer"), fetched_at="t2", **kw)
    assert a["content_hash"] == b["content_hash"] != c["content_hash"]
    assert a["job_id"] == c["job_id"]


def test_collection_methods():
    assert collection_method("meta", FakeScraper()) == "stealth_browser"
    assert collection_method("jazzhr", CloakScraper()) == "tls_impersonation"
    assert collection_method("icims", FakeScraper()) == "html"
    assert collection_method("lever", FakeScraper()) == "public_api"
