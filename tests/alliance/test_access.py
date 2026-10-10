from __future__ import annotations

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
    db, alliance_id: int, tag: str, *, verification: str = "unverified", order: int = 0,
):
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, clan_name, category, sort_order, status,
            verification_status, source, created_at, updated_at)
           VALUES (?, ?, ?, 'combat', ?, 'active', ?, 'manual', ?, ?)""",
        (alliance_id, tag, f"部落{tag}", order, verification, NOW, NOW),
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
