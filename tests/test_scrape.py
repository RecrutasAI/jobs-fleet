from fleet.scrape import classify_failure


def test_workday_maintenance_is_unavailable_not_an_error():
    assert classify_failure("workday", "ScraperError: non-JSON", "https://community.workday.com/maintenance-page") == "unavailable"
    assert classify_failure("workday", "x", "https://www.myworkday.com/wday/drs/outage?t=broadcom&s=ext") == "unavailable"


def test_other_failures_stay_errors():
    assert classify_failure("workday", "ScraperError: 404", None) == "error"
    assert classify_failure("workday", "x", "https://broadcom.wd1.myworkdayjobs.com/en-US/ext") == "error"
    assert classify_failure("greenhouse", "HTTP 500", None) == "error"


def test_workday_boards_are_read_a_couple_at_a_time(monkeypatch):
    import asyncio

    from fleet import scrape
    from fleet.registry import Board

    live = {"now": 0, "peak": 0}

    class FakeScraper:
        async def afetch(self):
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            await asyncio.sleep(0.02)
            live["now"] -= 1
            return []

    monkeypatch.setattr(scrape, "get_scraper", lambda ats, inp: FakeScraper())
    monkeypatch.setattr(scrape.md, "version", lambda _: "test")
    boards = [Board(ats="workday", slug=f"t{i}/site", name=f"T{i}", careers_url="") for i in range(8)]
    asyncio.run(scrape.read_boards(boards))
    assert live["peak"] == scrape.VENDOR_CONCURRENCY["workday"]

def test_closed_paycom_site_is_closed_not_an_error():
    from fleet.scrape import classify_failure
    target = "https://www.paycomonline.net/v4/ats/web.php/Jobs/JobsNotExist/jobsNotExist"
    assert classify_failure("paycom", "ScraperError: Paycom page omitted the public portal configuration", target) == "closed"
    assert classify_failure("paycom", "ScraperError: boom", None) == "error"
