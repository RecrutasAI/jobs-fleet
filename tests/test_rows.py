from datetime import UTC, datetime
from types import SimpleNamespace

from fleet.rows import ROW_FIELDS, collection_method, to_row


class FakeScraper:
    fetch_engine = "httpx"


class CloakScraper:
    fetch_engine = "cloak"


def fake_job(**kw):
    base = {"url": "https://job-boards.greenhouse.io/acme/jobs/1?gh_src=x", "title": "Engineer", "company": "Acme",
                "ats_id": "1", "location": "Austin, TX", "country_iso": "US", "posted_at": datetime(2026, 10, 1, tzinfo=UTC),
                "description": "Build things"}
    base.update(kw)
    return SimpleNamespace(**base)


def test_row_has_every_field_and_provenance():
    row = to_row(fake_job(), ats="greenhouse", slug="acme", board="greenhouse:acme",
                 scraper=FakeScraper(), scraper_version="0.3.0", fetched_at="2026-10-10T00:00:00+00:00")
    assert set(ROW_FIELDS) <= set(row)
    assert row["url"] == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert row["collection_method"] == "public_api" and row["scraper"] == "FakeScraper"
    assert row["posted_at"] == "2026-10-01T00:00:00+00:00" and row["schema_version"] == 2


def test_content_hash_changes_only_with_content():
    kw = {"ats": "greenhouse", "slug": "acme", "board": "greenhouse:acme", "scraper": FakeScraper(), "scraper_version": "v"}
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


def test_location_fields_are_derived():
    kw = {"ats": "lever", "slug": "acme", "board": "lever:acme", "scraper": FakeScraper(), "scraper_version": "v", "fetched_at": "t"}
    us = to_row(fake_job(location="Houston, TX, United States", country_iso=None), **kw)
    assert (us["country_iso"], us["us_state"], us["city"], us["is_us"], us["countries"]) == ("US", "TX", "Houston", True, "US")
    ca = to_row(fake_job(location="Montréal, QC, ca", country_iso=None), **kw)
    assert ca["country_iso"] == "CA" and ca["is_us"] is False
    remote = to_row(fake_job(location="Remote (US)", country_iso=None, is_remote=None), **kw)
    assert remote["is_remote"] is True and remote["is_us"] is True
    unknown = to_row(fake_job(location="San Diego", country_iso=None), **kw)
    assert unknown["country_iso"] is None and unknown["is_us"] is False


def test_location_fields_do_not_change_the_content_hash():
    kw = {"ats": "lever", "slug": "acme", "board": "lever:acme", "scraper": FakeScraper(), "scraper_version": "v", "fetched_at": "t"}
    a = to_row(fake_job(country_iso=None), **kw)
    b = to_row(fake_job(country_iso="US"), **kw)
    assert a["content_hash"] == b["content_hash"]


def test_oracle_rows_get_the_job_page_not_the_search_page():
    from fleet.rows import oracle_job_url
    site = "https://eigx.fa.us6.oraclecloud.com/?keyword=&lang=en&mode=jobs&site_number=CX_1"
    assert oracle_job_url(site, "eigx.fa.us6.oraclecloud.com:52165") == \
        "https://eigx.fa.us6.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/52165"
    other = "https://edmn.fa.us2.oraclecloud.com/?mode=jobs&site_number=CX_1001"
    assert oracle_job_url(other, "edmn.fa.us2.oraclecloud.com:9") .endswith("/sites/CX_1001/job/9")
    page = "https://x.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/7"
    assert oracle_job_url(page, "x:7") == page                      # already a job page
    assert oracle_job_url(site, None) == site                       # nothing to build from
    row = to_row(fake_job(url=site, ats_id="eigx.fa.us6.oraclecloud.com:52165"), ats="oracle", slug="eigx",
                 board="oracle:eigx", scraper=FakeScraper(), scraper_version="v", fetched_at="t")
    assert row["url"].endswith("/sites/CX_1/job/52165")


def test_registry_name_wins_over_the_scrapers_slug():
    kw = {"ats": "greenhouse", "slug": "extrahopnetworks", "board": "greenhouse:extrahopnetworks",
          "scraper": FakeScraper(), "scraper_version": "v", "fetched_at": "t"}
    a = to_row(fake_job(company="extrahopnetworks"), company="ExtraHop", **kw)
    b = to_row(fake_job(company="extrahopnetworks"), **kw)
    assert a["company_name"] == "ExtraHop" and b["company_name"] == "extrahopnetworks"
    assert a["content_hash"] == b["content_hash"]                   # a name fix is not a posting change
