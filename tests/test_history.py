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
    s1 = run({}, BoardRead(B, True, {"a": job("a", "h1")}), now="t1").state
    r = run(s1, BoardRead(B, True, {"a": job("a", "h2")}), now="t2")
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
