from fleet.ids import board_id, canonical_url, job_id, shard_of


def test_job_id_is_stable_and_never_random():
    a = job_id("greenhouse", "stripe", "123", None)
    assert a == job_id("greenhouse", "stripe", "123", None)
    assert a.startswith("j_") and len(a) == 26


def test_job_id_depends_on_board_and_system():
    assert job_id("greenhouse", "stripe", "123", None) != job_id("greenhouse", "airbnb", "123", None)
    assert job_id("greenhouse", "stripe", "123", None) != job_id("lever", "stripe", "123", None)


def test_slug_case_does_not_change_identity():
    assert job_id("workday", "NGC/Ext", "R1", None) == job_id("workday", "ngc/ext", "R1", None)


def test_falls_back_to_canonical_url_when_no_id():
    a = job_id("icims", "acme", None, "https://Careers-Acme.icims.com/jobs/42/?utm_source=x&gh_src=y#apply")
    b = job_id("icims", "acme", "", "https://careers-acme.icims.com/jobs/42")
    assert a == b


def test_no_id_and_no_url_is_an_error():
    import pytest
    with pytest.raises(ValueError):
        job_id("lever", "acme", None, None)


def test_canonical_url_keeps_meaningful_params_sorted():
    assert canonical_url("https://x.com/job?b=2&a=1&utm_medium=z") == "https://x.com/job?a=1&b=2"


def test_board_id_and_sharding_are_deterministic():
    assert board_id(" Greenhouse ", "Stripe") == "greenhouse:stripe"
    assert shard_of("greenhouse:stripe", 20) == shard_of("greenhouse:stripe", 20)
    assert {shard_of(f"greenhouse:c{i}", 4) for i in range(200)} == {0, 1, 2, 3}
