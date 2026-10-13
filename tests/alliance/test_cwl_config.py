from __future__ import annotations

import json

import pytest

from modules.alliance import cwl_config
from modules.alliance.access import resolve_alliance_context
from modules.alliance.cwl_config import (
    CwlConfigError,
    add_team,
    amend_frozen_team,
    confirm_season,
    correct_frozen_tag,
    create_season,
    season_payload,
    sync_sky_league_teams,
)
from modules.alliance.migration import SKY_ALLIANCE_KEY, apply_sky_migration


NOW = "2026-10-11T00:00:00+00:00"


def _bootstrap_plans(db):
    apply_sky_migration(
        db.conn,
        [{"tag": "#2QQ", "name": "战营", "category": "combat", "enabled": True}],
        now=NOW,
    )


def _context(db, *, plan="paid", role="admin", key="test-alliance"):
    user_id = db.conn.execute(
        "INSERT INTO wechat_users (openid, role, created_at, updated_at) VALUES (?, 'member', ?, ?)",
        (f"{key}-user", NOW, NOW),
    ).lastrowid
    alliance_id = db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?, ?)""",
        (key, key, plan, NOW, NOW),
    ).lastrowid
    db.conn.execute(
        """INSERT INTO alliance_members
           (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
           VALUES (?, ?, ?, 'active', ?, ?, ?)""",
        (alliance_id, user_id, role, NOW, NOW, NOW),
    )
    db.conn.commit()
    return resolve_alliance_context(db.conn, f"{key}-user", int(alliance_id))


def test_schema_and_plan_entitlements_are_ready(db):
    _bootstrap_plans(db)
    tables = {
        row[0]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"alliance_cwl_seasons", "alliance_cwl_teams"} <= tables
    team_columns = {
        row[1] for row in db.conn.execute("PRAGMA table_info(alliance_cwl_teams)").fetchall()
    }
    assert "manager_names" in team_columns
    entitlements = {
        row["plan_code"]: json.loads(row["entitlements_json"])
        for row in db.conn.execute(
            "SELECT plan_code, entitlements_json FROM alliance_plans"
        ).fetchall()
    }
    assert entitlements["free"]["max_cwl_teams"] == 1
    assert entitlements["paid"]["max_cwl_teams"] == 20
    assert entitlements["internal"]["cwl_registration"] is True


def test_free_plan_limit_and_confirmation(db, monkeypatch):
    _bootstrap_plans(db)
    monkeypatch.setattr(cwl_config, "current_period", lambda: "2026-10")
    context = _context(db, plan="free", key="free-cwl")

    create_season(db.conn, context, "2026-10")
    add_team(
        db.conn,
        context,
        "2026-10",
        clan_tag="#AAA",
        clan_name="一队",
        team_alias="一队",
        category="combat",
    )
    with pytest.raises(CwlConfigError, match="最多配置 1"):
        add_team(
            db.conn,
            context,
            "2026-10",
            clan_tag="#BBB",
            clan_name="二队",
            team_alias="二队",
            category="shell",
        )

    confirmed = confirm_season(db.conn, context, "2026-10")
    assert confirmed["status"] == "active"
    assert confirmed["team_count"] == 1


def test_group_detection_freezes_and_correction_is_audited(db, monkeypatch):
    _bootstrap_plans(db)
    monkeypatch.setattr(cwl_config, "current_period", lambda: "2026-10")
    context = _context(db, key="frozen-cwl")
    create_season(db.conn, context, "2026-10")
    team = add_team(
        db.conn,
        context,
        "2026-10",
        clan_tag="#AAA",
        clan_name="一队",
        team_alias="一队",
        category="combat",
    )
    confirm_season(db.conn, context, "2026-10")
    db.conn.execute(
        """INSERT INTO cwl_live_group_cache
           (period, clan_tag, team_index, team_alias, team_name, category,
            status, attempted_at, raw_status)
           VALUES ('2026-10', '#AAA', 0, '一队', '一队', 'combat',
                   'in_progress', ?, 'collecting')""",
        (NOW,),
    )
    db.conn.commit()

    assert season_payload(db.conn, context, "2026-10", include_draft=True)["status"] == "frozen"
    with pytest.raises(CwlConfigError, match="已冻结"):
        add_team(
            db.conn,
            context,
            "2026-10",
            clan_tag="#BBB",
            clan_name="二队",
            team_alias="二队",
            category="shell",
        )

    corrected = correct_frozen_tag(
        db.conn,
        context,
        "2026-10",
        team["id"],
        clan_tag="#CCC",
        reason="录入时复制了错误标签",
    )
    assert corrected["clan_tag"] == "#CCC"
    audit = db.conn.execute(
        "SELECT details_json FROM alliance_audit_events WHERE action='amend_frozen_cwl_team'"
    ).fetchone()
    assert json.loads(audit[0])["before"]["clan_tag"] == "#AAA"

    amended = amend_frozen_team(
        db.conn,
        context,
        "2026-10",
        team["id"],
        clan_tag="#CCC",
        team_alias="一队新别名",
        manager_names="管理甲、管理乙",
        category="shell",
    )
    assert amended["team_alias"] == "一队新别名"
    assert amended["manager_names"] == "管理甲、管理乙"
    assert amended["category"] == "shell"


def test_sky_legacy_snapshot_migrates_idempotently_and_keeps_shells(db):
    _bootstrap_plans(db)
    db.conn.executemany(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category, member_count)
           VALUES ('2026-10', ?, ?, ?, ?, ?, 15)""",
        [
            (0, "战营", "战营", "#2QQ", "combat"),
            (1, "临时壳", "临时壳", "#SHELL", "shell"),
        ],
    )
    db.conn.commit()

    first = sync_sky_league_teams(db.conn)
    second = sync_sky_league_teams(db.conn)
    sky_id = db.conn.execute(
        "SELECT id FROM alliances WHERE alliance_key = ?", (SKY_ALLIANCE_KEY,)
    ).fetchone()[0]
    tags = {
        row[0]
        for row in db.conn.execute(
            """SELECT teams.clan_tag
               FROM alliance_cwl_teams AS teams
               JOIN alliance_cwl_seasons AS seasons ON seasons.id = teams.season_id
               WHERE seasons.alliance_id = ? AND seasons.period = '2026-10'""",
            (sky_id,),
        ).fetchall()
    }
    assert first == {"periods": 1, "teams": 2, "skipped_frozen": 0}
    assert second == first
    assert tags == {"#2QQ", "#SHELL"}


def test_member_cannot_manage_but_can_read_confirmed_season(db, monkeypatch):
    _bootstrap_plans(db)
    monkeypatch.setattr(cwl_config, "current_period", lambda: "2026-10")
    admin = _context(db, key="role-cwl")
    create_season(db.conn, admin, "2026-10")
    add_team(
        db.conn,
        admin,
        "2026-10",
        clan_tag="#AAA",
        clan_name="一队",
        team_alias="一队",
        category="combat",
    )
    confirm_season(db.conn, admin, "2026-10")
    db.conn.execute(
        "UPDATE alliance_members SET role='member' WHERE alliance_id = ? AND user_id = ?",
        (admin.alliance_id, admin.user_id),
    )
    db.conn.commit()
    member = resolve_alliance_context(db.conn, admin.openid, admin.alliance_id)

    assert season_payload(db.conn, member, "2026-10")["team_count"] == 1
    with pytest.raises(CwlConfigError, match="管理权限"):
        create_season(db.conn, member, "2026-11")
