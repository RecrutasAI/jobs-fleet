import json

from fleet.patches import parse_bamboohr_widget

WIDGET = json.dumps({"version": None, "success": True, "departments": [
    {"id": 19933, "label": "ATL", "positions": [
        {"id": 996, "name": "BIM/VDC Manager ", "url": "https://aceelectric.bamboohr.com/careers/996",
         "location": "Greater Atlanta, GA"},
        {"id": 997, "name": "Foreman", "location": ""}]},
    {"id": 19937, "label": "STB", "positions": [
        {"id": 996, "name": "BIM/VDC Manager", "url": "x", "location": "dup"},
        {"id": 601, "name": "", "url": "no title"}]},
]})


def test_reads_json_widget():
    jobs = parse_bamboohr_widget(WIDGET, "aceelectric")
    assert [j["ats_id"] for j in jobs] == ["996", "997"]
    assert jobs[0] == {"ats_id": "996", "title": "BIM/VDC Manager",
                       "url": "https://aceelectric.bamboohr.com/careers/996",
                       "location": "Greater Atlanta, GA", "department": "ATL"}
    assert jobs[1]["url"] == "https://aceelectric.bamboohr.com/careers/997"
    assert jobs[1]["location"] is None


def test_html_falls_back_to_upstream_parser():
    assert parse_bamboohr_widget("<div class='BambooHR-ATS-board'></div>", "x") is None


def test_empty_board():
    assert parse_bamboohr_widget('{"departments": []}', "x") == []


def test_workday_posting_day():
    from datetime import date

    from fleet.patches import workday_posted_at
    today = date(2026, 10, 11)
    assert workday_posted_at("2026-08-19", "Posted 30+ Days Ago", today).date() == date(2026, 8, 19)
    assert workday_posted_at(None, "Posted Today", today).date() == today
    assert workday_posted_at(None, "Posted Yesterday", today).date() == date(2026, 10, 10)
    assert workday_posted_at(None, "Posted 3 Days Ago", today).date() == date(2026, 10, 8)
    assert workday_posted_at(None, "Posted 30+ Days Ago", today) is None      # not a date
    assert workday_posted_at(None, None, today) is None
    assert workday_posted_at("garbage", "Posted 2 Days Ago", today).date() == date(2026, 10, 9)


def test_workday_retries_wait_out_throttling():
    import ats_scrapers.scrapers.workday as upstream

    from fleet.patches import WORKDAY_LIMITS, tune_workday

    tune_workday()
    for name, value in WORKDAY_LIMITS.items():
        assert getattr(upstream, name) == value
    # The retry waits add up to a real pause (~2 min), not the upstream ~5 s.
    waits = [min(upstream.MAX_RETRY_DELAY, upstream.RETRY_BACKOFF ** a) for a in range(upstream.MAX_RETRIES)]
    assert sum(waits) >= 100
