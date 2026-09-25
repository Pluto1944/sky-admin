from datetime import datetime, timezone

from scripts.scheduler import JOBS, _next_run_iso, _parse_next_run_at


def test_war_layout_runs_at_next_0900_shanghai():
    before = datetime(2026, 9, 22, 0, 30, tzinfo=timezone.utc)  # 08:30 CST
    after = datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc)  # 10:00 CST
    assert _next_run_iso(JOBS["war_layout"], before) == "2026-09-22T01:00:00+00:00"
    assert _next_run_iso(JOBS["war_layout"], after) == "2026-09-23T01:00:00+00:00"


def test_war_layout_is_excluded_from_broad_manual_all():
    assert JOBS["war_layout"]["include_in_all"] is False


def test_next_run_parser_honors_persisted_timestamp():
    expected = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc).timestamp()
    assert _parse_next_run_at({"next_run_at": "2026-09-23T01:00:00+00:00"}) == expected
    assert _parse_next_run_at({"next_run_at": "invalid"}) is None
