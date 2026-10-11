from fleet.history import SUSPECT_EMPTY_MIN, BoardRead, merge

B = "greenhouse:acme"


def job(jid, h="h1"):
    return {"job_id": jid, "content_hash": h, "title": jid}


def run(prev, *reads, now="t"):
    return merge(prev, list(reads), now)


def test_first_run_opens_everything():
    r = run({}, BoardRead(B, True, {"a": job("a"), "b": job("b")}), now="t1")
    assert {e["event"] for e in r.events} == {"opened"}
    assert r.state["a"]["first_seen"] == "t1" and r.state["a"]["closed_at"] is None


def test_unchanged_job_keeps_first_seen_and_emits_nothing():
    s1 = run({}, BoardRead(B, True, {"a": job("a")}), now="t1").state
    r = run(s1, BoardRead(B, True, {"a": job("a")}), now="t2")
    assert r.events == []
    assert r.state["a"]["first_seen"] == "t1" and r.state["a"]["last_seen"] == "t2"


def test_changed_content_emits_changed():
    s1 = run({}, BoardRead(B, True, {"a": {**job("a", "h1"), "title": "Engineer"}}), now="t1").state
    r = run(s1, BoardRead(B, True, {"a": {**job("a", "h2"), "title": "Senior Engineer"}}), now="t2")
    assert [e["event"] for e in r.events] == ["changed"]


def test_missing_job_on_a_good_read_closes_it():
    s1 = run({}, BoardRead(B, True, {"a": job("a"), "b": job("b")}), now="t1").state
    r = run(s1, BoardRead(B, True, {"a": job("a")}), now="t2")
    assert [(e["event"], e["job_id"]) for e in r.events] == [("closed", "b")]
    assert r.state["b"]["closed_at"] == "t2"


def test_failed_read_never_closes_jobs():
    s1 = run({}, BoardRead(B, True, {"a": job("a")}), now="t1").state
    r = run(s1, BoardRead(B, False, {}, error="HTTP 500"), now="t2")
    assert r.events == [] and r.state["a"]["closed_at"] is None


def test_sudden_empty_board_is_suspect_not_closed():
    jobs = {f"j{i}": job(f"j{i}") for i in range(SUSPECT_EMPTY_MIN)}
    s1 = run({}, BoardRead(B, True, jobs), now="t1").state
    r = run(s1, BoardRead(B, True, {}), now="t2")
    assert r.suspect_boards == [B] and r.events == []
    assert all(s["closed_at"] is None for s in r.state.values())


def test_small_board_going_empty_does_close():
    s1 = run({}, BoardRead(B, True, {"a": job("a")}), now="t1").state
    r = run(s1, BoardRead(B, True, {}), now="t2")
    assert [e["event"] for e in r.events] == ["closed"]


def test_closed_job_coming_back_is_reopened_with_original_first_seen():
    s1 = run({}, BoardRead(B, True, {"a": job("a")}), now="t1").state
    s2 = run(s1, BoardRead(B, True, {}), now="t2").state
    r = run(s2, BoardRead(B, True, {"a": job("a")}), now="t3")
    assert [e["event"] for e in r.events] == ["reopened"]
    assert r.state["a"]["first_seen"] == "t1" and r.state["a"]["closed_at"] is None


def test_other_boards_are_untouched():
    other = "lever:beta"
    s1 = run({}, BoardRead(B, True, {"a": job("a")}), BoardRead(other, True, {"z": job("z")}), now="t1").state
    r = run(s1, BoardRead(B, True, {}), now="t2")  # only acme was read this run
    assert r.state["z"]["closed_at"] is None


def _hash(row):
    return "|".join(str(row.get(k)) for k in ("title", "description", "location"))


def jobd(jid, **kw):
    r = {"job_id": jid, "title": "Eng", "description": "Build", "location": "Austin, TX"} | kw
    r["content_hash"] = _hash(r)
    return r


def test_a_field_missing_on_one_read_is_not_a_change_and_is_kept():
    s1 = merge({}, [BoardRead(B, True, {"a": jobd("a")})], "t1", rehash=_hash).state
    r = merge(s1, [BoardRead(B, True, {"a": jobd("a", description=None)})], "t2", rehash=_hash)
    assert r.events == [] and r.state["a"]["description"] == "Build"


def test_workday_location_summary_does_not_erase_the_real_location():
    s1 = merge({}, [BoardRead(B, True, {"a": jobd("a")})], "t1", rehash=_hash).state
    r = merge(s1, [BoardRead(B, True, {"a": jobd("a", location="2 Locations")})], "t2", rehash=_hash)
    assert r.events == [] and r.state["a"]["location"] == "Austin, TX"


def test_a_real_difference_is_still_a_change():
    s1 = merge({}, [BoardRead(B, True, {"a": jobd("a")})], "t1", rehash=_hash).state
    r = merge(s1, [BoardRead(B, True, {"a": jobd("a", description="Build and lead")})], "t2", rehash=_hash)
    assert [e["event"] for e in r.events] == ["changed"] and r.state["a"]["description"] == "Build and lead"


def test_carried_location_brings_its_country_along():
    s1 = merge({}, [BoardRead(B, True, {"a": jobd("a", country_iso="US", is_us=True, us_state="TX")})], "t1", rehash=_hash).state
    r = merge(s1, [BoardRead(B, True, {"a": jobd("a", location="2 Locations", country_iso=None, is_us=False, us_state=None)})],
              "t2", rehash=_hash)
    a = r.state["a"]
    assert (a["location"], a["country_iso"], a["is_us"], a["us_state"]) == ("Austin, TX", "US", True, "TX")


def test_a_field_filled_in_for_the_first_time_is_not_a_change():
    s1 = merge({}, [BoardRead(B, True, {"a": jobd("a", description=None)})], "t1", rehash=_hash).state
    r = merge(s1, [BoardRead(B, True, {"a": jobd("a", description="Build")})], "t2", rehash=_hash)
    assert r.events == [] and r.state["a"]["description"] == "Build"


def test_published_posting_day_stays_when_read_a_day_apart():
    from fleet.history import fill_from_prior
    prior = {"posted_at": "2026-10-08T00:00:00+00:00"}
    assert fill_from_prior({"posted_at": "2026-10-09T00:00:00+00:00"}, prior, None)["posted_at"] == prior["posted_at"]
    assert fill_from_prior({"posted_at": None}, prior, None)["posted_at"] == prior["posted_at"]
    assert fill_from_prior({"posted_at": "2026-10-01T00:00:00+00:00"}, prior, None)["posted_at"].startswith("2026-10-01")  # reposted
