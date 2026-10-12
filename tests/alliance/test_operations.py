from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.alliance.access import resolve_alliance_context
from modules.alliance.free_alliance import create_free_alliance, free_alliance_capability
from modules.alliance.migration import apply_sky_migration
from modules.alliance.operations import (
    add_managed_clan,
    AllianceOperationError,
    create_share_link,
    free_registration_policy,
    grant_alliance_plan,
    join_from_share,
    leave_alliance,
    list_alliance_members,
    list_share_links,
    manual_set_clan_verification,
    platform_admin_capability,
    platform_dashboard,
    reconcile_expired_plan_grants,
    remove_managed_clan,
    remove_alliance_member,
    set_alliance_member_role,
    set_alliance_status,
    share_preview,
    update_platform_settings,
)
from modules.sync_queue.planner import SyncPlanner


NOW = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
NOW_TEXT = NOW.isoformat(timespec="seconds")


@pytest.fixture
def ops(db, monkeypatch):
    apply_sky_migration(db.conn, [], now=NOW_TEXT)
    ids = {}
    for openid in ("operator", "owner", "member", "other-owner", "blocked"):
        cursor = db.conn.execute(
            """INSERT INTO wechat_users (openid, role, created_at, updated_at)
               VALUES (?, 'member', ?, ?)""",
            (openid, NOW_TEXT, NOW_TEXT),
        )
        ids[openid] = int(cursor.lastrowid)
    db.conn.commit()
    monkeypatch.setenv("M5_FREE_ALLIANCE_ENABLED", "true")
    monkeypatch.setenv("M5_FREE_ALLIANCE_OPENIDS", "operator,owner,other-owner")
    return db, ids


def _alliance(db, owner_id: int, key: str, plan: str = "free") -> int:
    cursor = db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_by_user_id, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?, ?, ?)""",
        (key, key, plan, owner_id, NOW_TEXT, NOW_TEXT),
    )
    alliance_id = int(cursor.lastrowid)
    db.conn.execute(
        """INSERT INTO alliance_members
           (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
           VALUES (?, ?, 'leader', 'active', ?, ?, ?)""",
        (alliance_id, owner_id, NOW_TEXT, NOW_TEXT, NOW_TEXT),
    )
    db.conn.commit()
    return alliance_id


def _clan(db, alliance_id: int, tag: str, order: int = 0):
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, clan_name, category, sort_order, status,
            verification_status, source, created_at, updated_at)
           VALUES (?, ?, ?, 'combat', ?, 'active', 'unverified', 'manual', ?, ?)""",
        (alliance_id, tag, tag, order, NOW_TEXT, NOW_TEXT),
    )
    db.conn.commit()


def test_public_free_registration_is_capacity_controlled(ops):
    db, _ = ops
    assert free_registration_policy(db.conn)["public_open"] is False
    update_platform_settings(
        db.conn, "operator", free_registration_enabled=True,
        free_registration_limit=1, now=NOW,
    )
    policy = free_registration_policy(db.conn)
    assert policy["public_open"] is True
    assert policy["limit"] == 1

    capability = free_alliance_capability(db.conn, "member")
    assert capability["allowed"] is True
    created = create_free_alliance(db.conn, "member", now=NOW)
    assert created > 0
    assert free_alliance_capability(db.conn, "blocked")["can_create"] is False


def test_share_join_is_member_only_idempotent_and_blocked_users_stay_blocked(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "share-a")
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    assert share_preview(db.conn, shared["token"], now=NOW)["name"] == "share-a"

    first = join_from_share(db.conn, "member", shared["token"], now=NOW)
    second = join_from_share(db.conn, "member", shared["token"], now=NOW)
    assert first == {"alliance_id": alliance_id, "joined": True, "role": "member"}
    assert second["joined"] is False
    assert db.conn.execute(
        "SELECT use_count FROM alliance_share_links WHERE alliance_id=?",
        (alliance_id,),
    ).fetchone()[0] == 1
    row = db.conn.execute(
        "SELECT role, status FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (alliance_id, ids["member"]),
    ).fetchone()
    assert tuple(row) == ("member", "active")

    db.conn.execute(
        """INSERT INTO alliance_members
           (alliance_id, user_id, role, status, created_at, updated_at)
           VALUES (?, ?, 'member', 'blocked', ?, ?)""",
        (alliance_id, ids["blocked"], NOW_TEXT, NOW_TEXT),
    )
    db.conn.commit()
    with pytest.raises(AllianceOperationError, match="无法通过分享重新加入"):
        join_from_share(db.conn, "blocked", shared["token"], now=NOW)


def test_expired_share_cannot_join(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "share-expired")
    shared = create_share_link(db.conn, "owner", alliance_id, expires_days=1, now=NOW)
    with pytest.raises(AllianceOperationError, match="已过期"):
        join_from_share(db.conn, "member", shared["token"], now=NOW + timedelta(days=2))


def test_share_list_marks_elapsed_link_expired_without_returning_token(ops, monkeypatch):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "share-list-expired")
    create_share_link(db.conn, "owner", alliance_id, expires_days=1, now=NOW)
    monkeypatch.setattr(
        "modules.alliance.operations._now",
        lambda value=None: NOW + timedelta(days=2) if value is None else value,
    )

    links = list_share_links(db.conn, "owner", alliance_id)
    assert links[0]["status"] == "expired"
    assert links[0]["can_revoke"] is False
    assert "token" not in links[0]


def test_manual_verification_unlocks_management_and_rejects_conflict(ops):
    db, ids = ops
    first = _alliance(db, ids["owner"], "verify-a")
    second = _alliance(db, ids["other-owner"], "verify-b")
    _clan(db, first, "#2QQ")
    _clan(db, second, "#2QQ")

    result = manual_set_clan_verification(
        db.conn, "operator", first, "#2QQ", "verified", note="manual", now=NOW,
    )
    assert result["verification_status"] == "verified"
    assert resolve_alliance_context(db.conn, "owner", first).clan("#2QQ").management_allowed
    with pytest.raises(AllianceOperationError, match="已由联盟"):
        manual_set_clan_verification(
            db.conn, "operator", second, "#2QQ", "verified", now=NOW,
        )


def test_suspended_alliance_cannot_reactivate_with_verified_clan_conflict(ops):
    db, ids = ops
    first = _alliance(db, ids["owner"], "restore-a")
    second = _alliance(db, ids["other-owner"], "restore-b")
    _clan(db, first, "#2QQ")
    _clan(db, second, "#2QQ")
    manual_set_clan_verification(db.conn, "operator", first, "#2QQ", "verified", now=NOW)
    set_alliance_status(db.conn, "operator", first, "suspended", now=NOW)
    manual_set_clan_verification(db.conn, "operator", second, "#2QQ", "verified", now=NOW)

    with pytest.raises(AllianceOperationError, match="认证冲突"):
        set_alliance_status(db.conn, "operator", first, "active", now=NOW)
    assert db.conn.execute(
        "SELECT status FROM alliances WHERE id=?", (first,),
    ).fetchone()[0] == "suspended"


def test_leader_can_promote_transfer_and_remove_member(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "roles-a")
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    join_from_share(db.conn, "member", shared["token"], now=NOW)
    member_id = int(db.conn.execute(
        "SELECT id FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (alliance_id, ids["member"]),
    ).fetchone()[0])

    set_alliance_member_role(db.conn, "owner", alliance_id, member_id, "admin", now=NOW)
    assert db.conn.execute(
        "SELECT role FROM alliance_members WHERE id=?", (member_id,),
    ).fetchone()[0] == "admin"
    set_alliance_member_role(db.conn, "owner", alliance_id, member_id, "leader", now=NOW)
    assert resolve_alliance_context(db.conn, "member", alliance_id).role == "leader"
    old_owner = db.conn.execute(
        "SELECT role FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (alliance_id, ids["owner"]),
    ).fetchone()[0]
    assert old_owner == "admin"
    result = remove_alliance_member(
        db.conn, "member", alliance_id,
        int(db.conn.execute(
            "SELECT id FROM alliance_members WHERE alliance_id=? AND user_id=?",
            (alliance_id, ids["owner"]),
        ).fetchone()[0]),
        now=NOW,
    )
    assert result["status"] == "removed"


def test_only_alliance_management_can_list_user_members(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "member-list-a")
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    join_from_share(db.conn, "member", shared["token"], now=NOW)

    result = list_alliance_members(db.conn, "owner", alliance_id)
    assert result["actor_role"] == "leader"
    assert len(result["members"]) == 2
    with pytest.raises(AllianceOperationError, match="角色没有此操作权限"):
        list_alliance_members(db.conn, "member", alliance_id)


def test_member_can_leave_and_rejoin_but_leader_must_transfer_first(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "leave-a")
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    join_from_share(db.conn, "member", shared["token"], now=NOW)

    assert leave_alliance(db.conn, "member", alliance_id, now=NOW)["status"] == "left"
    assert resolve_alliance_context(db.conn, "member", alliance_id) is None
    rejoined = join_from_share(db.conn, "member", shared["token"], now=NOW)
    assert rejoined == {"alliance_id": alliance_id, "joined": True, "role": "member"}
    with pytest.raises(AllianceOperationError, match="先移交首领"):
        leave_alliance(db.conn, "owner", alliance_id, now=NOW)


def test_paid_expiry_downgrades_sync_and_preserves_rows(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "paid-a", plan="paid")
    _clan(db, alliance_id, "#2QQ", order=0)
    _clan(db, alliance_id, "#9PY", order=1)
    expiry = NOW + timedelta(days=1)
    grant_alliance_plan(
        db.conn, "operator", alliance_id, plan_code="paid",
        expires_at=expiry.isoformat(), now=NOW,
    )
    before = SyncPlanner(db.conn)._clan_interests(NOW)
    assert {item["metadata"]["sync_tier"] for item in before} == {"high"}

    result = reconcile_expired_plan_grants(db.conn, now=NOW + timedelta(days=2))
    assert result == {"expired_grants": 1, "deactivated_clans": 1}
    after = SyncPlanner(db.conn)._clan_interests(NOW + timedelta(days=2))
    assert {item["metadata"]["sync_tier"] for item in after} == {"low"}
    assert db.conn.execute(
        "SELECT COUNT(*) FROM alliance_clans WHERE alliance_id=?", (alliance_id,),
    ).fetchone()[0] == 2
    assert db.conn.execute(
        "SELECT COUNT(*) FROM alliance_clans WHERE alliance_id=? AND status='active'",
        (alliance_id,),
    ).fetchone()[0] == 1


def test_paid_manager_can_add_and_remove_clans_without_deleting_public_cache(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "paid-manage", plan="paid")
    grant_alliance_plan(
        db.conn, "operator", alliance_id, plan_code="paid",
        expires_at=(NOW + timedelta(days=365)).isoformat(), now=NOW,
    )
    added = add_managed_clan(
        db.conn, "owner", alliance_id, clan_tag="#2QQ", category="combat", now=NOW,
    )
    assert added["verification_status"] == "unverified"
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, updated_at)
           VALUES ('#2QQ', '#2QQ', 'combat', 'not_in_war', '{}', ?)""",
        (NOW_TEXT,),
    )
    db.conn.commit()
    removed = remove_managed_clan(db.conn, "owner", alliance_id, "#2QQ", now=NOW)
    assert removed["status"] == "removed"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM current_war_cache WHERE clan_tag='#2QQ'"
    ).fetchone()[0] == 1


def test_platform_dashboard_requires_operator_and_exposes_no_openid(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "dashboard-a")
    _clan(db, alliance_id, "#2QQ")
    manual_set_clan_verification(db.conn, "operator", alliance_id, "#2QQ", "verified", now=NOW)
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    join_from_share(db.conn, "member", shared["token"], now=NOW)
    assert platform_admin_capability(db.conn, "operator")["allowed"] is True
    result = platform_dashboard(db.conn, "operator")
    assert result["alliances"]
    assert result["alliances"][0]["verified_count"] == 1
    assert "openid" not in result["alliances"][0]
    with pytest.raises(AllianceOperationError, match="平台管理员"):
        platform_dashboard(db.conn, "member")
