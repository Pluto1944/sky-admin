from datetime import datetime, timezone

from modules.sync_queue.planner import ShadowSyncPlanner, SyncPlanner, _current_war_policy


NOW = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
TS = "2026-10-05T00:00:00+00:00"


def _seed_alliance(db, key: str, name: str, plan_code: str) -> int:
    db.conn.execute(
        """INSERT OR IGNORE INTO alliance_plans
           (plan_code, display_name, max_clans, sync_tier, entitlements_json,
            status, created_at, updated_at)
           VALUES (?, ?, 100, ?, '{}', 'active', ?, ?)""",
        (plan_code, plan_code, "internal" if plan_code == "internal" else "low", TS, TS),
    )
    cursor = db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?, ?)""",
        (key, name, plan_code, TS, TS),
    )
    return int(cursor.lastrowid)


def _seed_clan_and_cwl(db, alliance_id: int, tag: str) -> None:
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, clan_name, category, sort_order, status,
            verification_status, source, created_at, updated_at)
           VALUES (?, ?, 'shared', 'combat', 0, 'active', 'verified', 'manual', ?, ?)""",
        (alliance_id, tag, TS, TS),
    )
    season = db.conn.execute(
        """INSERT INTO alliance_cwl_seasons
           (alliance_id, period, status, created_at, updated_at, confirmed_at)
           VALUES (?, '2026-10', 'active', ?, ?, ?)""",
        (alliance_id, TS, TS, TS),
    ).lastrowid
    db.conn.execute(
        """INSERT INTO alliance_cwl_teams
           (season_id, team_index, clan_tag, clan_name_snapshot, team_alias,
            category, sort_order, source, created_at, updated_at)
           VALUES (?, 0, ?, 'shared', 'shared', 'combat', 0, 'manual', ?, ?)""",
        (season, tag, TS, TS),
    )


def test_planner_deduplicates_shared_clan_and_cwl_targets(db):
    internal = _seed_alliance(db, "internal", "Internal", "internal")
    free = _seed_alliance(db, "free", "Free", "free")
    _seed_clan_and_cwl(db, internal, "#2qq")
    _seed_clan_and_cwl(db, free, "2QQ")
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, updated_at,
            attempted_at, failure_count)
           VALUES ('#2QQ', 'shared', 'combat', 'in_war', '{}', ?, ?, 0)""",
        (TS, TS),
    )
    db.conn.commit()

    planner = ShadowSyncPlanner(db.conn)
    first = planner.run(now=NOW)
    second = planner.run(now=NOW)

    assert first["interests"]["active"] == 8
    assert first["targets"]["active"] == 4
    assert first["tasks_planned"] == 4
    assert second["tasks_planned"] == 0
    rows = db.conn.execute(
        "SELECT resource_type, priority, desired_interval_seconds, alliance_count "
        "FROM sync_targets WHERE status = 'active' ORDER BY resource_type"
    ).fetchall()
    by_type = {row["resource_type"]: dict(row) for row in rows}
    assert by_type["current_war"]["priority"] == "realtime"
    assert by_type["current_war"]["desired_interval_seconds"] == 120
    assert by_type["current_war"]["alliance_count"] == 2
    assert by_type["cwl_live"]["alliance_count"] == 2


def test_planner_only_reads_local_state_and_deactivates_suspended_alliances(db):
    alliance_id = _seed_alliance(db, "internal", "Internal", "internal")
    _seed_clan_and_cwl(db, alliance_id, "#2QQ")
    db.conn.commit()
    planner = ShadowSyncPlanner(db.conn)
    planner.run(now=NOW)

    db.conn.execute("UPDATE alliances SET status = 'suspended' WHERE id = ?", (alliance_id,))
    db.conn.commit()
    result = planner.run(now=NOW)

    assert result["interests"]["active"] == 0
    assert result["targets"]["active"] == 0
    assert result["tasks_planned"] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM sync_targets WHERE status = 'active'"
    ).fetchone()[0] == 0


def test_cwl_shadow_interest_stops_after_legacy_live_window(db):
    alliance_id = _seed_alliance(db, "internal", "Internal", "internal")
    _seed_clan_and_cwl(db, alliance_id, "#2QQ")
    db.conn.commit()

    result = ShadowSyncPlanner(db.conn).run(
        now=datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    )

    assert result["interests"]["active"] == 3
    assert db.conn.execute(
        "SELECT COUNT(*) FROM sync_interests WHERE resource_type = 'cwl_live' AND status = 'active'"
    ).fetchone()[0] == 0


def test_current_war_shadow_policy_matches_near_start_and_error_backoff():
    near_start = {
        "status": "preparation",
        "data_json": '{"start_time": "20261005T001500.000Z"}',
        "failure_count": 0,
    }
    assert _current_war_policy("internal", near_start, NOW) == ("realtime", 120)
    assert _current_war_policy(
        "internal", {"status": "error", "failure_count": 3}, NOW
    ) == ("scheduled", 1200)
    assert _current_war_policy("low", near_start, NOW) == ("scheduled", 17 * 60)


def test_live_cutover_only_creates_live_tasks_for_selected_types(db):
    alliance_id = _seed_alliance(db, "internal", "Internal", "internal")
    _seed_clan_and_cwl(db, alliance_id, "#2QQ")
    db.conn.commit()

    result = SyncPlanner(db.conn).run(
        now=NOW, live_resource_types=("clan_profile", "current_war"),
    )

    assert result["live_tasks_planned"] == 2
    assert result["shadow_tasks_planned"] == 2
    modes = {
        row["resource_type"]: row["planning_mode"]
        for row in db.conn.execute("SELECT resource_type, planning_mode FROM sync_targets")
    }
    assert modes == {
        "clan_profile": "live",
        "clan_members": "shadow",
        "current_war": "live",
        "cwl_live": "shadow",
    }
