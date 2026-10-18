import json
from datetime import datetime, timezone

from modules.sync_queue.refresh_policy import (
    cwl_page_interval_seconds,
    low_current_war_interval_seconds,
    low_cwl_interval_seconds,
    paid_current_war_interval_seconds,
)


NOW = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
TS = "2026-10-05T00:00:00+00:00"


def test_current_war_page_policy_matches_high_quality_automatic_cadence():
    assert paid_current_war_interval_seconds(None, NOW) == 5 * 60
    assert paid_current_war_interval_seconds({"status": "in_war"}, NOW) == 2 * 60
    assert paid_current_war_interval_seconds({
        "status": "preparation",
        "data_json": '{"start_time":"20261005T001500.000Z"}',
    }, NOW) == 2 * 60
    assert paid_current_war_interval_seconds({
        "status": "preparation",
        "data_json": '{"start_time":"20261005T020000.000Z"}',
    }, NOW) == 30 * 60


def test_low_current_war_policy_targets_lifecycle_boundaries():
    assert low_current_war_interval_seconds(None, NOW) == 6 * 60 * 60
    assert low_current_war_interval_seconds({
        "status": "preparation",
        "data_json": '{"start_time":"20261005T001500.000Z"}',
    }, NOW) == 17 * 60
    assert low_current_war_interval_seconds({
        "status": "in_war",
        "expected_end_at": "20261005T030000.000Z",
    }, NOW) == 3 * 60 * 60 + 2 * 60


def _seed_cwl(db, state: str, payload: dict) -> None:
    group = {"rounds": [{"war_tags": ["#WAR1"]}]}
    db.conn.execute(
        """INSERT INTO cwl_live_group_cache
           (period, clan_tag, team_index, team_alias, category, status,
            data_json, attempted_at)
           VALUES ('2026-10', '#2QQ', 0, '一队', 'combat', 'active', ?, ?)""",
        (json.dumps(group), TS),
    )
    db.conn.execute(
        """INSERT INTO cwl_live_war_cache
           (war_tag, season, state, status, data_json, attempted_at)
           VALUES ('#WAR1', '2026-10', ?, ?, ?, ?)""",
        (state, payload.get("status", "unknown"), json.dumps(payload), TS),
    )
    db.conn.commit()


def test_cwl_page_and_low_policy_separate_live_progress_from_finalization(db):
    _seed_cwl(db, "inWar", {
        "status": "in_war",
        "end_time": "20261005T030000.000Z",
    })
    assert cwl_page_interval_seconds(db.conn, "2026-10", "#2QQ") == 2 * 60
    assert low_cwl_interval_seconds(db.conn, "2026-10", "#2QQ", NOW) == 3 * 60 * 60 + 2 * 60
