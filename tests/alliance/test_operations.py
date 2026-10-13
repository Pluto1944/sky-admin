from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.alliance.access import resolve_alliance_context
from modules.alliance.free_alliance import FreeAllianceError, create_free_alliance, free_alliance_capability
from modules.alliance.migration import apply_sky_migration
from modules.alliance.operations import (
    add_alliance_member_by_openid,
    add_managed_clan,
    AllianceOperationError,
    archive_suspended_alliance,
    create_platform_alliance,
    create_share_link,
    delete_browsing_history,
    free_registration_policy,
    grant_alliance_plan,
    join_from_share,
    leave_alliance,
    list_managed_clans,
    list_alliance_members,
    list_share_links,
    list_join_requests,
    manual_set_clan_verification,
    platform_admin_capability,
    platform_add_alliance_member,
    platform_dashboard,
    platform_rename_alliance,
    platform_remove_alliance_member,
    platform_set_alliance_member_role,
    record_share_visit,
    reconcile_expired_plan_grants,
    remove_managed_clan,
    reorder_managed_clans,
    remove_alliance_member,
    request_alliance_join,
    review_join_request,
    set_alliance_member_role,
    set_alliance_status,
    share_preview,
    update_platform_settings,
    update_managed_clan,
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
    db.conn.execute(
        """INSERT INTO platform_admins (user_id, status, note, created_at, updated_at)
           VALUES (?, 'active', 'test operator', ?, ?)""",
        (ids["operator"], NOW_TEXT, NOW_TEXT),
    )
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


def test_platform_admin_dropdown_still_allows_only_one_free_alliance(ops):
    db, _ = ops
    first = create_free_alliance(db.conn, "operator", name="平台测试一", now=NOW)
    capability = free_alliance_capability(db.conn, "operator")
    assert first > 0
    assert capability["unlimited"] is False
    assert capability["can_create"] is False
    with pytest.raises(FreeAllianceError, match="只能创建一个"):
        create_free_alliance(db.conn, "operator", name="平台测试二", now=NOW)


def test_free_creation_allowlist_never_grants_platform_admin(ops):
    db, ids = ops
    db.conn.execute("UPDATE platform_admins SET status='revoked' WHERE user_id=?", (ids["operator"],))
    db.conn.commit()
    assert free_alliance_capability(db.conn, "operator")["allowed"] is True
    assert platform_admin_capability(db.conn, "operator")["allowed"] is False


def test_platform_admin_can_create_multiple_alliances_only_via_platform_operation(ops):
    db, _ = ops
    first = create_platform_alliance(db.conn, "operator", "平台一", now=NOW)
    second = create_platform_alliance(db.conn, "operator", "平台二", now=NOW)
    assert first["alliance_id"] != second["alliance_id"]
    assert db.conn.execute(
        """SELECT COUNT(*) FROM alliances
           WHERE created_by_user_id=(SELECT id FROM wechat_users WHERE openid='operator')
             AND status='active'"""
    ).fetchone()[0] == 2
    # 平台创建的测试联盟不占用个人普通入口的“一人一个”名额。
    capability = free_alliance_capability(db.conn, "operator")
    assert capability["can_create"] is True
    assert capability["existing_alliance_id"] is None


def test_share_join_is_member_only_idempotent_and_blocked_users_stay_blocked(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "share-a")
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    assert share_preview(db.conn, shared["token"], now=NOW)["name"] == "share-a"

    first = join_from_share(db.conn, "member", shared["token"], now=NOW)
    db.conn.execute(
        """UPDATE alliance_visits SET is_default=0, is_hidden=1, hidden_at=?
           WHERE alliance_id=? AND user_id=?""",
        (NOW_TEXT, alliance_id, ids["member"]),
    )
    db.conn.commit()
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
    assert db.conn.execute(
        """SELECT is_hidden FROM alliance_visits
           WHERE alliance_id=? AND user_id=?""",
        (alliance_id, ids["member"]),
    ).fetchone()[0] == 0

    db.conn.execute(
        """INSERT INTO alliance_members
           (alliance_id, user_id, role, status, created_at, updated_at)
           VALUES (?, ?, 'member', 'blocked', ?, ?)""",
        (alliance_id, ids["blocked"], NOW_TEXT, NOW_TEXT),
    )
    db.conn.commit()
    with pytest.raises(AllianceOperationError, match="无法通过分享重新加入"):
        join_from_share(db.conn, "blocked", shared["token"], now=NOW)


def test_share_join_has_no_total_membership_cap_but_keeps_daily_rate_limit(ops):
    db, ids = ops
    for index in range(50):
        alliance_id = _alliance(db, ids["operator"], f"joined-{index}", plan="paid")
        db.conn.execute(
            """INSERT INTO alliance_members
               (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
               VALUES (?, ?, 'member', 'active', ?, ?, ?)""",
            (alliance_id, ids["member"], NOW_TEXT, NOW_TEXT, NOW_TEXT),
        )
    db.conn.commit()

    target_id = _alliance(db, ids["owner"], "joined-target", plan="paid")
    shared = create_share_link(db.conn, "owner", target_id, now=NOW)
    assert join_from_share(db.conn, "member", shared["token"], now=NOW)["joined"] is True
    assert db.conn.execute(
        """SELECT COUNT(*) FROM alliance_members
           WHERE user_id=? AND status='active'""",
        (ids["member"],),
    ).fetchone()[0] == 51

    for index in range(19):
        db.conn.execute(
            """INSERT INTO alliance_audit_events
               (alliance_id, actor_user_id, action, entity_type, entity_id,
                details_json, created_at)
               VALUES (?, ?, 'alliance_share_joined', 'alliance_member', ?, '{}', ?)""",
            (target_id, ids["member"], f"rate-{index}", NOW_TEXT),
        )
    db.conn.commit()
    second_target_id = _alliance(db, ids["other-owner"], "joined-target-2", plan="paid")
    second_share = create_share_link(db.conn, "other-owner", second_target_id, now=NOW)
    with pytest.raises(AllianceOperationError, match="过于频繁"):
        join_from_share(db.conn, "member", second_share["token"], now=NOW)


def test_expired_share_cannot_join(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "share-expired")
    shared = create_share_link(db.conn, "owner", alliance_id, expires_days=1, now=NOW)
    with pytest.raises(AllianceOperationError, match="已过期"):
        join_from_share(db.conn, "member", shared["token"], now=NOW + timedelta(days=2))


def test_browse_share_records_history_and_join_requires_approval(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "browse-a")
    shared = create_share_link(
        db.conn, "owner", alliance_id, share_type="browse", now=NOW,
    )
    preview = share_preview(db.conn, shared["token"], now=NOW)
    assert preview["share_type"] == "browse"
    assert preview["can_join"] is False

    opened = record_share_visit(db.conn, "member", shared["token"], now=NOW)
    assert opened["alliance_id"] == alliance_id
    assert resolve_alliance_context(db.conn, "member", alliance_id) is None
    with pytest.raises(AllianceOperationError, match="不能直接加入"):
        join_from_share(db.conn, "member", shared["token"], now=NOW)

    requested = request_alliance_join(db.conn, "member", alliance_id, now=NOW)
    assert requested["status"] == "pending"
    pending = list_join_requests(db.conn, "owner", alliance_id)["requests"]
    assert [item["id"] for item in pending if item["status"] == "pending"] == [requested["id"]]
    reviewed = review_join_request(
        db.conn, "owner", alliance_id, requested["id"], "approve", now=NOW,
    )
    assert reviewed["status"] == "approved"
    assert resolve_alliance_context(db.conn, "member", alliance_id).role == "member"


def test_browsing_history_can_be_removed_without_changing_membership(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "history-a")
    shared = create_share_link(
        db.conn, "owner", alliance_id, share_type="browse", now=NOW,
    )
    record_share_visit(db.conn, "member", shared["token"], now=NOW)
    assert delete_browsing_history(db.conn, "member", alliance_id)["removed"] is True
    assert db.conn.execute(
        "SELECT 1 FROM alliance_visits WHERE alliance_id=? AND user_id=?",
        (alliance_id, ids["member"]),
    ).fetchone() is None


def test_leader_adds_admin_by_openid_but_admin_can_only_add_member(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "openid-a")
    added = add_alliance_member_by_openid(
        db.conn, "owner", alliance_id, "member", "admin", now=NOW,
    )
    assert added["role"] == "admin"
    with pytest.raises(AllianceOperationError, match="只能添加普通成员"):
        add_alliance_member_by_openid(
            db.conn, "member", alliance_id, "other-owner", "admin", now=NOW,
        )
    ordinary = add_alliance_member_by_openid(
        db.conn, "member", alliance_id, "other-owner", "member", now=NOW,
    )
    assert ordinary["role"] == "member"


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


def test_platform_manual_verification_allows_same_clan_in_multiple_alliances(ops):
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
    duplicate = manual_set_clan_verification(
        db.conn, "operator", second, "#2QQ", "verified", now=NOW,
    )
    assert duplicate["verification_status"] == "verified"
    assert duplicate["also_verified_alliances"] == [
        {"alliance_id": first, "alliance_name": "verify-a"},
    ]
    assert resolve_alliance_context(
        db.conn, "other-owner", second,
    ).clan("#2QQ").management_allowed
    dashboard = platform_dashboard(db.conn, "operator")
    duplicate_summary = dashboard["multi_alliance_verifications"]
    assert len(duplicate_summary) == 1
    assert duplicate_summary[0]["clan_tag"] == "#2QQ"
    assert duplicate_summary[0]["alliance_count"] == 2
    assert set(duplicate_summary[0]["alliance_names"].split(",")) == {"verify-a", "verify-b"}


def test_non_platform_user_cannot_use_manual_verification(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "verify-owner")
    _clan(db, alliance_id, "#2QQ")

    with pytest.raises(AllianceOperationError, match="平台管理员"):
        manual_set_clan_verification(
            db.conn, "member", alliance_id, "#2QQ", "verified", now=NOW,
        )


def test_suspended_alliance_can_reactivate_with_multi_alliance_verification(ops):
    db, ids = ops
    first = _alliance(db, ids["owner"], "restore-a")
    second = _alliance(db, ids["other-owner"], "restore-b")
    _clan(db, first, "#2QQ")
    _clan(db, second, "#2QQ")
    manual_set_clan_verification(db.conn, "operator", first, "#2QQ", "verified", now=NOW)
    set_alliance_status(db.conn, "operator", first, "suspended", now=NOW)
    manual_set_clan_verification(db.conn, "operator", second, "#2QQ", "verified", now=NOW)

    set_alliance_status(db.conn, "operator", first, "active", now=NOW)
    assert db.conn.execute(
        "SELECT status FROM alliances WHERE id=?", (first,),
    ).fetchone()[0] == "active"


def test_platform_archive_requires_suspended_alliance_and_exact_name(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "delete-a")
    _clan(db, alliance_id, "#2QQ")
    shared = create_share_link(db.conn, "owner", alliance_id, now=NOW)
    record_share_visit(db.conn, "member", shared["token"], now=NOW)
    request_alliance_join(db.conn, "member", alliance_id, now=NOW)

    with pytest.raises(AllianceOperationError, match="先停用"):
        archive_suspended_alliance(db.conn, "operator", alliance_id, "delete-a", now=NOW)
    with pytest.raises(AllianceOperationError, match="不支持"):
        set_alliance_status(db.conn, "operator", alliance_id, "archived", now=NOW)

    set_alliance_status(db.conn, "operator", alliance_id, "suspended", now=NOW)
    with pytest.raises(AllianceOperationError, match="完整联盟名称"):
        archive_suspended_alliance(db.conn, "operator", alliance_id, "wrong", now=NOW)

    result = archive_suspended_alliance(
        db.conn, "operator", alliance_id, "delete-a", now=NOW,
    )
    assert result["status"] == "archived"
    assert db.conn.execute(
        "SELECT status FROM alliances WHERE id=?", (alliance_id,),
    ).fetchone()[0] == "archived"
    assert db.conn.execute(
        "SELECT status FROM alliance_clans WHERE alliance_id=?", (alliance_id,),
    ).fetchone()[0] == "inactive"
    assert db.conn.execute(
        "SELECT status FROM alliance_members WHERE alliance_id=?", (alliance_id,),
    ).fetchone()[0] == "left"
    assert db.conn.execute(
        "SELECT status FROM alliance_share_links WHERE alliance_id=?", (alliance_id,),
    ).fetchone()[0] == "revoked"
    assert db.conn.execute(
        "SELECT status FROM alliance_join_requests WHERE alliance_id=?", (alliance_id,),
    ).fetchone()[0] == "cancelled"
    assert not any(
        item["id"] == alliance_id
        for item in platform_dashboard(db.conn, "operator")["alliances"]
    )
    with pytest.raises(AllianceOperationError, match="不能恢复"):
        set_alliance_status(db.conn, "operator", alliance_id, "active", now=NOW)


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

    grace = reconcile_expired_plan_grants(db.conn, now=NOW + timedelta(days=2))
    assert grace == {"expired_grants": 0, "deactivated_clans": 0}
    during_grace = SyncPlanner(db.conn)._clan_interests(NOW + timedelta(days=2))
    assert {item["metadata"]["sync_tier"] for item in during_grace} == {"high"}

    result = reconcile_expired_plan_grants(db.conn, now=NOW + timedelta(days=9))
    assert result == {"expired_grants": 1, "deactivated_clans": 1}
    after = SyncPlanner(db.conn)._clan_interests(NOW + timedelta(days=9))
    assert {item["metadata"]["sync_tier"] for item in after} == {"low"}
    assert db.conn.execute(
        "SELECT plan_code FROM alliances WHERE id=?", (alliance_id,),
    ).fetchone()[0] == "free"
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


def test_free_manager_can_manage_one_clan_and_replace_removed_subscription(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "free-manage")

    listed = list_managed_clans(db.conn, "owner", alliance_id)
    assert listed["can_manage"] is True
    assert listed["can_add"] is True
    assert listed["max_clans"] == 1

    added = add_managed_clan(
        db.conn, "owner", alliance_id, clan_tag="#2QQ", category="combat", now=NOW,
    )
    assert added["category"] == "combat"
    with pytest.raises(AllianceOperationError, match="数量上限"):
        add_managed_clan(
            db.conn, "owner", alliance_id, clan_tag="#9PY", category="farm", now=NOW,
        )

    manual_set_clan_verification(
        db.conn, "operator", alliance_id, "#2QQ", "verified", now=NOW,
    )
    updated = update_managed_clan(
        db.conn, "owner", alliance_id, "#2QQ", category="normal", now=NOW,
    )
    assert updated["category"] == "normal"
    assert updated["verification_status"] == "verified"

    remove_managed_clan(db.conn, "owner", alliance_id, "#2QQ", now=NOW)
    replacement = add_managed_clan(
        db.conn, "owner", alliance_id, clan_tag="#9PY", category="farm", now=NOW,
    )
    assert replacement["clan_tag"] == "#9PY"


def test_alliance_admin_can_edit_but_only_leader_changes_clan_membership(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "admin-clan-boundary", plan="paid")
    grant_alliance_plan(
        db.conn, "operator", alliance_id, plan_code="paid",
        expires_at=(NOW + timedelta(days=365)).isoformat(), now=NOW,
    )
    added = add_alliance_member_by_openid(
        db.conn, "owner", alliance_id, "member", role="admin", now=NOW,
    )
    assert added["role"] == "admin"
    add_managed_clan(
        db.conn, "owner", alliance_id, clan_tag="#2QQ", category="combat", now=NOW,
    )
    listed = list_managed_clans(db.conn, "member", alliance_id)
    assert listed["can_manage"] is True
    assert listed["can_add"] is False
    assert listed["can_remove"] is False
    update_managed_clan(
        db.conn, "member", alliance_id, "#2QQ", category="normal",
        clan_name="管理员别名", now=NOW,
    )
    assert db.conn.execute(
        "SELECT clan_name FROM alliance_clans WHERE alliance_id=? AND clan_tag='#2QQ'",
        (alliance_id,),
    ).fetchone()[0] == "管理员别名"
    reorder_managed_clans(db.conn, "member", alliance_id, ["#2QQ"], now=NOW)
    with pytest.raises(AllianceOperationError, match="角色没有此操作权限"):
        add_managed_clan(
            db.conn, "member", alliance_id, clan_tag="#9PY", category="farm", now=NOW,
        )
    with pytest.raises(AllianceOperationError, match="角色没有此操作权限"):
        remove_managed_clan(db.conn, "member", alliance_id, "#2QQ", now=NOW)


def test_paid_manager_can_reorder_active_clans(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "paid-order", plan="paid")
    grant_alliance_plan(
        db.conn, "operator", alliance_id, plan_code="paid",
        expires_at=(NOW + timedelta(days=365)).isoformat(), now=NOW,
    )
    add_managed_clan(db.conn, "owner", alliance_id, clan_tag="#2QQ", category="combat", now=NOW)
    add_managed_clan(db.conn, "owner", alliance_id, clan_tag="#9PY", category="farm", now=NOW)

    result = reorder_managed_clans(
        db.conn, "owner", alliance_id, ["#9PY", "#2QQ"], now=NOW,
    )
    assert result == {"clan_tags": ["#9PY", "#2QQ"]}
    assert [row["clan_tag"] for row in db.conn.execute(
        """SELECT clan_tag FROM alliance_clans
           WHERE alliance_id=? AND status='active' ORDER BY sort_order, id""",
        (alliance_id,),
    ).fetchall()] == ["#9PY", "#2QQ"]
    with pytest.raises(AllianceOperationError, match="全部有效部落"):
        reorder_managed_clans(db.conn, "owner", alliance_id, ["#2QQ"], now=NOW)


def test_platform_admin_manages_any_alliance_without_plan_clan_limit(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "platform-unlimited", plan="free")
    first = add_managed_clan(
        db.conn, "operator", alliance_id, clan_tag="#2QQ", category="combat",
        platform=True, now=NOW,
    )
    second = add_managed_clan(
        db.conn, "operator", alliance_id, clan_tag="#9PY", category="farm",
        platform=True, now=NOW,
    )
    assert first["clan_tag"] == "#2QQ"
    assert second["clan_tag"] == "#9PY"
    listed = list_managed_clans(db.conn, "operator", alliance_id, platform=True)
    assert listed["actor_role"] == "platform_admin"
    assert listed["unlimited"] is True
    assert listed["can_add"] is True
    assert listed["active_count"] == 2
    assert db.conn.execute(
        "SELECT clan_limit_override FROM alliances WHERE id=?", (alliance_id,),
    ).fetchone()[0] == 2
    with pytest.raises(AllianceOperationError, match="套餐"):
        add_managed_clan(
            db.conn, "owner", alliance_id, clan_tag="#8PR", category="normal", now=NOW,
        )
    update_managed_clan(
        db.conn, "operator", alliance_id, "#9PY", category="flat",
        platform=True, now=NOW,
    )
    reorder_managed_clans(
        db.conn, "operator", alliance_id, ["#9PY", "#2QQ"],
        platform=True, now=NOW,
    )
    remove_managed_clan(
        db.conn, "operator", alliance_id, "#2QQ", platform=True, now=NOW,
    )
    assert db.conn.execute(
        "SELECT category FROM alliance_clans WHERE alliance_id=? AND clan_tag='#9PY'",
        (alliance_id,),
    ).fetchone()[0] == "flat"


def test_internal_or_member_cannot_manage_alliance_clans(ops):
    db, ids = ops
    internal_id = _alliance(db, ids["owner"], "internal-manage", plan="internal")
    with pytest.raises(AllianceOperationError, match="系统配置"):
        add_managed_clan(
            db.conn, "owner", internal_id, clan_tag="#2QQ", category="combat", now=NOW,
        )

    free_id = _alliance(db, ids["other-owner"], "member-manage")
    shared = create_share_link(db.conn, "other-owner", free_id, now=NOW)
    join_from_share(db.conn, "member", shared["token"], now=NOW)
    assert list_managed_clans(db.conn, "member", free_id)["can_manage"] is False
    with pytest.raises(AllianceOperationError, match="角色没有此操作权限"):
        add_managed_clan(
            db.conn, "member", free_id, clan_tag="#2QQ", category="combat", now=NOW,
        )


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


def test_platform_admin_can_rename_alliance_with_audit(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "rename-by-platform")

    result = platform_rename_alliance(
        db.conn, "operator", alliance_id, "新联盟名称", now=NOW,
    )

    assert result["name"] == "新联盟名称"
    assert db.conn.execute(
        "SELECT name FROM alliances WHERE id=?", (alliance_id,),
    ).fetchone()[0] == "新联盟名称"
    assert db.conn.execute(
        """SELECT COUNT(*) FROM platform_audit_events
           WHERE action='alliance_renamed' AND entity_id=?""",
        (str(alliance_id),),
    ).fetchone()[0] == 1
    with pytest.raises(AllianceOperationError, match="平台管理员"):
        platform_rename_alliance(db.conn, "member", alliance_id, "无权修改", now=NOW)


def test_platform_admin_can_assign_leader_and_manage_members(ops):
    db, ids = ops
    alliance_id = _alliance(db, ids["owner"], "platform-members")

    added = platform_add_alliance_member(
        db.conn, "operator", alliance_id, "member", "member", now=NOW,
    )
    platform_set_alliance_member_role(
        db.conn, "operator", alliance_id, added["member_id"], "leader", now=NOW,
    )
    assert resolve_alliance_context(db.conn, "member", alliance_id).role == "leader"
    assert resolve_alliance_context(db.conn, "owner", alliance_id).role == "admin"
    with pytest.raises(AllianceOperationError, match="先把首领移交"):
        platform_remove_alliance_member(
            db.conn, "operator", alliance_id, added["member_id"], now=NOW,
        )
    owner_member_id = int(db.conn.execute(
        "SELECT id FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (alliance_id, ids["owner"]),
    ).fetchone()[0])
    removed = platform_remove_alliance_member(
        db.conn, "operator", alliance_id, owner_member_id, now=NOW,
    )
    assert removed["status"] == "removed"
