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


def test_apple_locations_keep_state_and_country():
    from fleet.location import parse
    from fleet.patches import apple_location
    # Real record (2026-10-12): the place is in `name`, city and state are empty.
    cupertino = {"postLocationId": "postLocation-CUP", "city": "", "stateProvince": "", "countryName": "United States of America",
                 "name": "Cupertino", "countryID": "iso-country-USA"}
    assert apple_location(cupertino) == "Cupertino, United States of America"
    assert parse(apple_location(cupertino)).is_us
    assert apple_location({"city": "Austin", "stateProvince": "Texas", "countryName": "United States", "name": ""}) == "Austin, Texas, United States"
    assert apple_location({"countryName": "India", "name": "India"}) == "India"
    assert apple_location({"name": "Shanghai, China", "countryName": "China"}) == "Shanghai, China"


class _FakeResp:
    def __init__(self, status, text="{}", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class _FakeSession:
    """httpcloak.Session stand-in: answers from a queue and records what was sent."""

    def __init__(self, answers):
        self.answers, self.sent = list(answers), []

    async def get_async(self, url, **kw):
        self.sent.append(("GET", url, kw))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    async def post_async(self, url, **kw):
        return await self.get_async(url, **kw)

    def close(self):
        pass


def _client(answers):
    from fleet.patches import CloakClient

    c = CloakClient.__new__(CloakClient)
    c._session = _FakeSession(answers)
    return c


def test_workday_reads_through_the_cloak_client():
    import ats_scrapers.scrapers.workday as upstream
    import httpx

    from fleet.patches import CloakClient, get_scraper

    get_scraper("workday", "https://nvidia.wd5.myworkdayjobs.com/nvidiaexternalcareersite")
    assert upstream.httpx.AsyncClient is CloakClient
    assert upstream.httpx.HTTPError is httpx.HTTPError   # the reader's except clauses still catch


def test_cloak_client_drops_the_readers_user_agent_and_keeps_the_rest():
    import asyncio

    c = _client([_FakeResp(200, '{"total": 3}')])
    r = asyncio.run(c.post("https://x/jobs", json={"offset": 0}, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}))
    assert r.status_code == 200 and r.json() == {"total": 3}
    _, _, kw = c._session.sent[0]
    assert kw["headers"] == {"Content-Type": "application/json"} and kw["json"] == {"offset": 0}


def test_cloak_client_waits_out_a_detail_429(monkeypatch):
    import asyncio

    from fleet import patches

    waits = []

    async def no_sleep(s):
        waits.append(s)

    monkeypatch.setattr(patches.asyncio, "sleep", no_sleep)
    c = _client([_FakeResp(429), _FakeResp(429, headers={"Retry-After": "5"}), _FakeResp(200, '{"jobPostingInfo": {}}')])
    r = asyncio.run(c.get("https://x/job/1", headers={"Accept": "application/json"}))
    assert r.status_code == 200 and waits == [2.0, 5.0]


def test_cloak_client_gives_up_on_a_detail_after_the_last_wait(monkeypatch):
    import asyncio

    from fleet import patches

    async def no_sleep(s):
        pass

    monkeypatch.setattr(patches.asyncio, "sleep", no_sleep)
    c = _client([_FakeResp(429)] * (len(patches.DETAIL_429_WAITS_S) + 1))
    assert asyncio.run(c.get("https://x/job/1")).status_code == 429   # the reader then keeps the listing row
    assert c._session.answers == []


def test_cloak_client_failure_is_an_httpx_transport_error():
    import asyncio

    import httpx
    import pytest

    c = _client([RuntimeError("connection reset")])
    with pytest.raises(httpx.TransportError, match="connection reset"):
        asyncio.run(c.post("https://x/jobs", json={}))


def test_cloak_client_bad_json_is_a_value_error():
    import pytest

    from fleet.patches import _CloakResponse

    with pytest.raises(ValueError):
        _CloakResponse(200, "<html>", {}).json()
