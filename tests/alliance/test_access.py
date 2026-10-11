from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import api_server.alliance_routes as alliance_routes
import api_server.routes as legacy_routes
from modules.alliance.access import (
    ensure_sky_admin_membership,
    list_alliance_contexts,
    resolve_alliance_context,
)
from modules.alliance.migration import SKY_ALLIANCE_KEY, apply_sky_migration


CLANS = [
    {"tag": "#AAA", "name": "一营", "category": "combat", "enabled": True},
]
NOW = "2026-10-10T00:00:00+00:00"


def _user(db, openid: str) -> int:
    cursor = db.conn.execute(
        """INSERT INTO wechat_users (openid, role, created_at, updated_at)
           VALUES (?, 'member', ?, ?)""",
        (openid, NOW, NOW),
    )
    db.conn.commit()
    return int(cursor.lastrowid)


def _sky_id(db) -> int:
    return int(db.conn.execute(
        "SELECT id FROM alliances WHERE alliance_key = ?", (SKY_ALLIANCE_KEY,)
    ).fetchone()[0])


def _paid_alliance(db, key: str = "paid-a", name: str = "A联盟") -> int:
    cursor = db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES (?, ?, 'active', 'paid', ?, ?)""",
        (key, name, NOW, NOW),
    )
    return int(cursor.lastrowid)


def _membership(db, alliance_id: int, user_id: int, role: str, status: str = "active"):
    db.conn.execute(
        """INSERT INTO alliance_members
           (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (alliance_id, user_id, role, status, NOW, NOW, NOW),
    )


def _clan(
    db, alliance_id: int, tag: str, *, category: str = "combat",
    verification: str = "unverified", order: int = 0,
):
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, clan_name, category, sort_order, status,
            verification_status, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'active', ?, 'manual', ?, ?)""",
        (alliance_id, tag, f"部落{tag}", category, order, verification, NOW, NOW),
    )


def _war_archive(db, clan_tag: str, war_key: str, *, player_tag: str | None = None):
    item = {
        "clan_tag": clan_tag,
        "clan_name": f"部落{clan_tag}",
        "category": "combat",
        "status": "war_ended",
        "state": "warEnded",
        "war_type": "random",
        "result": "win",
        "team_size": 15,
        "attacks_per_member": 2,
        "end_time": "20261009T230000.000Z",
        "opponent": {"tag": "#ENEMY", "name": "对手"},
        "rows": [],
        "synced_at": NOW,
    }
    db.conn.execute(
        """INSERT INTO war_history_cache
           (clan_tag, war_key, clan_name, category, opponent_tag, opponent_name,
            status, result, end_time, data_json, updated_at)
           VALUES (?, ?, ?, 'combat', '#ENEMY', '对手', 'war_ended', 'win', ?, ?, ?)""",
        (clan_tag, war_key, f"部落{clan_tag}", item["end_time"], json.dumps(item), NOW),
    )
    if player_tag:
        db.conn.execute(
            """INSERT INTO member_war_facts
               (clan_tag, war_key, player_tag, end_time, status, category,
                offense_effective_attacks, offense_effective_3stars,
                defense_effective_attacks, defense_effective_3stars, updated_at)
               VALUES (?, ?, ?, ?, 'war_ended', 'combat', 2, 1, 2, 1, ?)""",
            (clan_tag, war_key, player_tag, item["end_time"], NOW),
        )


def test_sky_join_grants_admin_once_but_never_repromotes_or_restores(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "new-sky-user")

    assert ensure_sky_admin_membership(db.conn, "new-sky-user", now=NOW) is True
    row = db.conn.execute(
        "SELECT role, status FROM alliance_members WHERE user_id = ?", (user_id,)
    ).fetchone()
    assert tuple(row) == ("admin", "active")
    assert ensure_sky_admin_membership(db.conn, "new-sky-user", now=NOW) is False
    assert db.conn.execute(
        "SELECT COUNT(*) FROM alliance_audit_events WHERE action='sky_auto_admin_join'"
    ).fetchone()[0] == 1

    db.conn.execute(
        "UPDATE alliance_members SET role='member' WHERE user_id = ?", (user_id,)
    )
    db.conn.commit()
    ensure_sky_admin_membership(db.conn, "new-sky-user", now=NOW)
    assert db.conn.execute(
        "SELECT role FROM alliance_members WHERE user_id = ?", (user_id,)
    ).fetchone()[0] == "member"

    db.conn.execute(
        "UPDATE alliance_members SET status='removed' WHERE user_id = ?", (user_id,)
    )
    db.conn.commit()
    ensure_sky_admin_membership(db.conn, "new-sky-user", now=NOW)
    assert resolve_alliance_context(db.conn, "new-sky-user", _sky_id(db)) is None


def test_wechat_login_adds_new_sky_user_without_overwriting_existing_role(db, monkeypatch):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    monkeypatch.setattr(legacy_routes, "_wechat_code2openid", lambda _code: "login-user")

    response = legacy_routes.wechat_login({"code": "test-code"}, db)
    user_id = db.conn.execute(
        "SELECT id FROM wechat_users WHERE openid='login-user'"
    ).fetchone()[0]
    membership = db.conn.execute(
        "SELECT role FROM alliance_members WHERE user_id = ?", (user_id,)
    ).fetchone()
    assert response["token"]
    assert membership["role"] == "admin"

    db.conn.execute(
        "UPDATE alliance_members SET role='member' WHERE user_id = ?", (user_id,)
    )
    db.conn.commit()
    legacy_routes.wechat_login({"code": "test-code"}, db)
    assert db.conn.execute(
        "SELECT role FROM alliance_members WHERE user_id = ?", (user_id,)
    ).fetchone()[0] == "member"


def test_context_uses_per_alliance_roles_and_caps_unverified_admin(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "multi")
    sky_id = _sky_id(db)
    paid_id = _paid_alliance(db)
    _membership(db, sky_id, user_id, "member")
    _membership(db, paid_id, user_id, "admin")
    _clan(db, paid_id, "#BBB", verification="unverified")
    db.conn.commit()

    contexts = list_alliance_contexts(db.conn, "multi")
    assert {item.alliance_id: item.role for item in contexts} == {
        sky_id: "member", paid_id: "admin",
    }
    paid = resolve_alliance_context(db.conn, "multi", paid_id)
    assert paid is not None
    assert paid.clan("#BBB").effective_access == "member"

    db.conn.execute(
        """UPDATE alliance_clans SET verification_status='verified'
           WHERE alliance_id = ? AND clan_tag = '#BBB'""",
        (paid_id,),
    )
    db.conn.commit()
    assert resolve_alliance_context(db.conn, "multi", paid_id).clan("#BBB").effective_access == "management"


def test_visit_without_active_membership_does_not_grant_access(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "visitor")
    sky_id = _sky_id(db)
    db.conn.execute(
        """INSERT INTO alliance_visits
           (alliance_id, user_id, is_default, first_visited_at, last_visited_at)
           VALUES (?, ?, 1, ?, ?)""",
        (sky_id, user_id, NOW, NOW),
    )
    db.conn.commit()

    assert list_alliance_contexts(db.conn, "visitor") == []
    assert resolve_alliance_context(db.conn, "visitor", sky_id) is None


def test_visit_switches_default_only_for_active_membership(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "switcher")
    sky_id = _sky_id(db)
    ensure_sky_admin_membership(db.conn, "switcher", now=NOW)
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    db.conn.commit()

    result = alliance_routes.visit_alliance(
        paid_id, user={"openid": "switcher"}, db=db,
    )
    defaults = db.conn.execute(
        "SELECT alliance_id FROM alliance_visits WHERE user_id=? AND is_default=1",
        (user_id,),
    ).fetchall()
    assert result["id"] == paid_id
    assert result["is_default"] is True
    assert [row["alliance_id"] for row in defaults] == [paid_id]

    outsider_id = _paid_alliance(db, key="paid-b", name="B联盟")
    with pytest.raises(HTTPException) as exc:
        alliance_routes.visit_alliance(
            outsider_id, user={"openid": "switcher"}, db=db,
        )
    assert exc.value.status_code == 404


def test_members_endpoint_whitelists_management_fields_per_clan(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    admin_id = _user(db, "admin")
    member_id = _user(db, "member")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, admin_id, "admin")
    _membership(db, paid_id, member_id, "member")
    _clan(db, paid_id, "#BBB", verification="verified")
    db.conn.execute(
        """INSERT INTO accounts
           (player_tag, account_name, town_hall_level, clan_tag, clan_role,
            trophies, coc_raw, last_activity_at, player_name, history_score,
            membership_status, last_synced_at)
           VALUES ('#P1', '玩家一', 18, '#BBB', 'member', 5000,
                   '{"donations": 50, "donationsReceived": 25}',
                   ?, '归属人', 12, 'member', ?)""",
        (NOW, NOW),
    )
    db.conn.commit()

    admin = alliance_routes.alliance_members(
        paid_id, user={"openid": "admin"}, db=db,
    )["members"][0]
    ordinary = alliance_routes.alliance_members(
        paid_id, user={"openid": "member"}, db=db,
    )["members"][0]

    assert admin["data_level"] == "management"
    assert admin["management"]["player_name"] == "归属人"
    assert admin["player_name"] == "归属人"
    assert ordinary["data_level"] == "member"
    assert "management" not in ordinary
    assert "player_name" not in ordinary
    assert ordinary["donations"] == 50


def test_unverified_admin_and_cross_alliance_url_cannot_read_management(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    admin_id = _user(db, "admin")
    outsider_id = _user(db, "outsider")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, admin_id, "admin")
    _clan(db, paid_id, "#BBB", verification="unverified")
    db.conn.commit()

    response = alliance_routes.alliance_members(
        paid_id, user={"openid": "admin"}, db=db,
    )
    assert response["members"] == []

    with pytest.raises(HTTPException) as exc:
        alliance_routes.alliance_clans(
            paid_id, user={"openid": "outsider"}, db=db,
        )
    assert exc.value.status_code == 404


def test_current_wars_are_scoped_to_subscribed_clans(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "paid-user")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    _clan(db, paid_id, "#BBB")
    db.conn.commit()

    result = alliance_routes.alliance_current_wars(
        paid_id, user={"openid": "paid-user"}, db=db,
    )
    assert [item["clan_tag"] for item in result["clans"]] == ["#BBB"]
    assert result["clans"][0]["status"] == "sync_pending"

    with pytest.raises(HTTPException) as exc:
        alliance_routes.alliance_current_war_detail(
            paid_id, "#AAA", user={"openid": "paid-user"}, db=db,
        )
    assert exc.value.status_code == 404


def test_war_history_is_scoped_to_current_alliance(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "history-user")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    _clan(db, paid_id, "#BBB", category="combat")
    _war_archive(db, "#BBB", "war-bbb")
    _war_archive(db, "#AAA", "war-aaa")
    db.conn.commit()

    result = alliance_routes.alliance_war_history(
        paid_id, user={"openid": "history-user"}, db=db,
    )
    assert [item["clan_tag"] for item in result["wars"]] == ["#BBB"]
    assert result["alliance_id"] == paid_id

    detail = alliance_routes.alliance_war_history_detail(
        paid_id, "#BBB", "war-bbb", user={"openid": "history-user"}, db=db,
    )
    assert detail["clan_tag"] == "#BBB"
    assert detail["is_history"] is True

    with pytest.raises(HTTPException) as exc:
        alliance_routes.alliance_war_history_detail(
            paid_id, "#AAA", "war-aaa", user={"openid": "history-user"}, db=db,
        )
    assert exc.value.status_code == 404


def test_war_stats_selects_current_alliance_combat_clan_without_sky_special_case(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "stats-user")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    _clan(db, paid_id, "#NORMAL", category="normal", order=0)
    _clan(db, paid_id, "#CAMP", category="combat", order=1)
    db.conn.execute(
        """INSERT INTO accounts
           (player_tag, account_name, town_hall_level, clan_tag, membership_status)
           VALUES ('#P1', '战营玩家', 18, '#CAMP', 'member')"""
    )
    _war_archive(db, "#CAMP", "war-camp", player_tag="#P1")
    db.conn.commit()

    result = alliance_routes.alliance_war_stats(
        paid_id, user={"openid": "stats-user"}, db=db,
    )
    assert result["alliance_id"] == paid_id
    assert result["clan_tag"] == "#CAMP"
    assert result["combat_clans"] == [
        {"clan_tag": "#CAMP", "clan_name": "部落#CAMP"},
    ]
    assert result["stats"][0]["offense_5_sample"] == {"three_stars": 1, "attacks": 2}

    with pytest.raises(HTTPException) as exc:
        alliance_routes.alliance_war_stats(
            paid_id, clan_tag="#NORMAL", user={"openid": "stats-user"}, db=db,
        )
    assert exc.value.status_code == 404


def test_war_stats_returns_empty_when_current_alliance_has_no_combat_clan(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "no-camp-user")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    _clan(db, paid_id, "#NORMAL", category="normal")
    db.conn.commit()

    result = alliance_routes.alliance_war_stats(
        paid_id, user={"openid": "no-camp-user"}, db=db,
    )
    assert result["clan_tag"] is None
    assert result["combat_clans"] == []
    assert result["stats"] == []


def test_farm_config_only_returns_current_alliance_farm_clans(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "farm-user")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    _clan(db, paid_id, "#FARM", category="farm", order=1)
    _clan(db, paid_id, "#COMBAT", category="combat", order=2)
    db.conn.executemany(
        """INSERT INTO farm_stats
           (clan_tag, clan_name, category, member_count, stats_json, updated_at)
           VALUES (?, ?, 'farm', ?, ?, ?)""",
        [
            ("#FARM", "联盟互刷部落", 40, '{"member_count": 40}', NOW),
            ("#OUTSIDE", "联盟外部落", 50, '{"member_count": 50}', NOW),
        ],
    )
    db.conn.commit()

    result = alliance_routes.alliance_farm_config(
        paid_id, user={"openid": "farm-user"}, db=db,
    )

    assert result["alliance_id"] == paid_id
    assert [item["clan_tag"] for item in result["clans"]] == ["#FARM"]
    assert result["clans"][0]["clan_name"] == "部落#FARM"


def test_farm_config_returns_empty_when_alliance_has_no_farm_clan(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    user_id = _user(db, "no-farm-user")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, user_id, "member")
    _clan(db, paid_id, "#COMBAT")
    db.conn.commit()

    result = alliance_routes.alliance_farm_config(
        paid_id, user={"openid": "no-farm-user"}, db=db,
    )

    assert result["clans"] == []


def test_sky_cwl_keeps_legacy_shell_teams_while_other_alliances_stay_scoped(db):
    apply_sky_migration(db.conn, CLANS, now=NOW)
    sky_user = _user(db, "sky-cwl")
    ensure_sky_admin_membership(db.conn, "sky-cwl", now=NOW)
    sky_id = _sky_id(db)
    paid_user = _user(db, "paid-cwl")
    paid_id = _paid_alliance(db)
    _membership(db, paid_id, paid_user, "member")
    _clan(db, paid_id, "#BBB")
    period = legacy_routes._current_cwl_live_period()
    db.conn.executemany(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category, member_count)
           VALUES (?, ?, ?, ?, ?, ?, 15)""",
        [
            (period, 0, "苍穹壳", "苍穹临时壳", "#CWLX", "shell"),
            (period, 1, "外部队", "外部队", "#BBB", "combat"),
        ],
    )
    db.conn.commit()

    sky = alliance_routes.alliance_cwl_live(
        sky_id, user={"openid": "sky-cwl"}, db=db,
    )
    assert {item["clan_tag"] for item in sky["clans"]} == {"#CWLX", "#BBB"}
    detail = alliance_routes.alliance_cwl_live_detail(
        sky_id, "#CWLX", user={"openid": "sky-cwl"}, db=db,
    )
    assert detail["summary"]["clan_tag"] == "#CWLX"

    paid = alliance_routes.alliance_cwl_live(
        paid_id, user={"openid": "paid-cwl"}, db=db,
    )
    assert [item["clan_tag"] for item in paid["clans"]] == ["#BBB"]
    with pytest.raises(HTTPException) as exc:
        alliance_routes.alliance_cwl_live_detail(
            paid_id, "#CWLX", user={"openid": "paid-cwl"}, db=db,
        )
    assert exc.value.status_code == 404
