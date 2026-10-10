from fleet.scrape import classify_failure


def test_workday_maintenance_is_unavailable_not_an_error():
    assert classify_failure("workday", "ScraperError: non-JSON", "https://community.workday.com/maintenance-page") == "unavailable"
    assert classify_failure("workday", "x", "https://www.myworkday.com/wday/drs/outage?t=broadcom&s=ext") == "unavailable"


def test_other_failures_stay_errors():
    assert classify_failure("workday", "ScraperError: 404", None) == "error"
    assert classify_failure("workday", "x", "https://broadcom.wd1.myworkdayjobs.com/en-US/ext") == "error"
    assert classify_failure("greenhouse", "HTTP 500", None) == "error"
