from pathlib import Path

from fleet import registry


def test_seed_registry_loads_100_unique_boards():
    boards = registry.load()
    assert len(boards) == 100
    assert len({b.id for b in boards}) == 100
    assert all(b.careers_url.startswith("https://") for b in boards)


def test_shards_cover_every_enabled_board_exactly_once():
    boards = registry.load()
    seen = [b.id for i in range(7) for b in registry.shard(boards, i, 7)]
    assert sorted(seen) == sorted(b.id for b in boards if b.enabled)


def test_duplicates_and_disabled_boards(tmp_path: Path):
    f = tmp_path / "b.csv"
    f.write_text("ats,slug,name,careers_url,priority,enabled\n"
                 "greenhouse,Acme,Acme,https://a,1,true\n"
                 "greenhouse,acme,Acme dup,https://a,1,true\n"
                 "lever,beta,Beta,https://b,2,false\n")
    boards = registry.load(f)
    assert [b.name for b in boards] == ["Acme", "Beta"]
    assert registry.shard(boards, 0, 1) == [boards[0]]
