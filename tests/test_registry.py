from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from fleet import registry

HEADER = "ats,slug,name,careers_url,priority,enabled\n"


def _registry(tmp_path: Path, n: int = 300, priority: int = 2) -> Path:
    f = tmp_path / "boards.csv"
    f.write_text(HEADER + "".join(f"greenhouse,co{i},Co {i},https://job-boards.greenhouse.io/co{i},{priority},true\n"
                                  for i in range(n)))
    return f


def test_shards_cover_every_enabled_board_exactly_once(tmp_path: Path):
    boards = registry.load(_registry(tmp_path))
    seen = [b.id for i in range(7) for b in registry.shard(boards, i, 7)]
    assert sorted(seen) == sorted(b.id for b in boards if b.enabled)


def test_duplicates_and_disabled_boards(tmp_path: Path):
    f = tmp_path / "b.csv"
    f.write_text(HEADER +
                 "greenhouse,Acme,Acme,https://a,1,true\n"
                 "greenhouse,acme,Acme dup,https://a,1,true\n"
                 "lever,beta,Beta,https://b,2,false\n")
    boards = registry.load(f)
    assert [b.name for b in boards] == ["Acme", "Beta"]
    assert registry.shard(boards, 0, 1) == [boards[0]]


def test_url_input_systems_get_the_career_page_but_keep_slug_identity():
    wd = registry.Board("workday", "ngc/ext", "NGC", "https://ngc.wd1.myworkdayjobs.com/ext")
    gh = registry.Board("greenhouse", "stripe", "Stripe", "https://job-boards.greenhouse.io/stripe")
    assert wd.scraper_input == "https://ngc.wd1.myworkdayjobs.com/ext"
    assert gh.scraper_input == "stripe"
    assert wd.id == "workday:ngc/ext"


def test_each_board_is_read_once_per_cadence_and_load_is_spread(tmp_path: Path):
    for priority, every in registry.CADENCE.items():
        boards = registry.load(_registry(tmp_path, priority=priority))
        start = date(2026, 10, 11)
        days = [start + timedelta(d) for d in range(every)]
        reads = Counter(b.id for d in days for b in boards if registry.due(b, d))
        assert set(reads.values()) == {1} and len(reads) == len(boards)
        per_day = [sum(registry.due(b, d) for b in boards) for d in days]
        assert min(per_day) > len(boards) / every * 0.7  # roughly even, never all on one day


def test_shard_with_a_day_keeps_only_due_boards(tmp_path: Path):
    boards = registry.load(_registry(tmp_path, priority=3))
    day = date(2026, 10, 11)
    due = registry.shard(boards, 0, 1, day)
    assert due and len(due) < len(boards)
    assert all(registry.due(b, day) for b in due)


def test_priority_follows_board_size():
    assert [registry.priority_for(n) for n in (0, 19, 20, 99, 100, 5000)] == [3, 3, 2, 2, 1, 1]


def test_reprioritize_uses_clean_reads_only(tmp_path: Path):
    f = tmp_path / "b.csv"
    f.write_text(HEADER +
                 "greenhouse,big,Big,https://a,2,true\n"
                 "greenhouse,small,Small,https://b,2,true\n"
                 "greenhouse,broken,Broken,https://c,1,true\n"
                 "greenhouse,empty,Empty,https://d,1,true\n"
                 "greenhouse,unread,Unread,https://e,2,false\n")
    runs = [
        {"board_id": "greenhouse:big", "status": "ok", "jobs": 450},
        {"board_id": "greenhouse:small", "status": "ok", "jobs": 4},
        {"board_id": "greenhouse:broken", "status": "error", "jobs": 0},
        {"board_id": "greenhouse:empty", "status": "ok", "jobs": 0, "suspect_empty": True},
    ]
    assert registry.reprioritize(f, runs) == 2
    by_slug = {b.slug: b for b in registry.load(f)}
    assert {s: b.priority for s, b in by_slug.items()} == {"big": 1, "small": 3, "broken": 1, "empty": 1, "unread": 2}
    assert by_slug["unread"].enabled is False  # other columns untouched


def test_closed_boards_are_turned_off_and_kept(tmp_path):
    import csv

    from fleet.registry import disable_closed

    path = tmp_path / "boards.csv"
    path.write_text(
        "ats,slug,name,careers_url,priority,enabled\n"
        "paycom,aaa,A,https://a,2,true\n"
        "paycom,bbb,B,https://b,2,true\n"
    )
    runs = [{"board_id": "paycom:aaa", "status": "closed"}, {"board_id": "paycom:bbb", "status": "error"}]
    assert disable_closed(path, runs) == 1
    with open(path) as f:
        rows = {r["slug"]: r for r in csv.DictReader(f)}
    assert rows["aaa"]["enabled"] == "false" and rows["bbb"]["enabled"] == "true"
    assert disable_closed(path, runs) == 0   # already off


def test_adp_boards_are_read_by_their_careers_url():
    from fleet.registry import Board
    url = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=7e680810-90b3-483a-bc7f-ab0bb"
    assert Board(ats="adp", slug="7e680810-90b3-483a-bc7f-ab0bb/190", name="X", careers_url=url).scraper_input == url
