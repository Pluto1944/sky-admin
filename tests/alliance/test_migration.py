from __future__ import annotations

import json
import sqlite3

import pytest

from modules.alliance.migration import (
    SKY_ALLIANCE_KEY,
    apply_sky_migration,
    build_existing_user_assignments,
    build_sky_manifest,
    preview_sky_migration,
)
from modules.alliance.plans import ensure_plan_catalog


CLANS = [
    {"tag": "#AAA", "name": "一营", "category": "combat", "enabled": True},
    {"tag": "bbb", "name": "二营", "category": "farm", "enabled": True},
    {"tag": "#OFF", "name": "停用", "category": "normal", "enabled": False},
]


def _add_wechat_user(db, openid: str, role: str = "member") -> int:
    cursor = db.conn.execute(
        "INSERT INTO wechat_users (openid, role) VALUES (?, ?)", (openid, role)
    )
    db.conn.commit()
    return int(cursor.lastrowid)


def _alliance_id(db) -> int:
    return int(
        db.conn.execute(
            "SELECT id FROM alliances WHERE alliance_key = ?", (SKY_ALLIANCE_KEY,)
        ).fetchone()[0]
    )


def test_alliance_core_tables_are_created(db):
    for table in (
        "alliance_plans",
        "alliances",
        "alliance_members",
        "alliance_clans",
        "alliance_visits",
        "alliance_audit_events",
    ):
        assert db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    visit_columns = {
        row[1] for row in db.conn.execute("PRAGMA table_info(alliance_visits)")
    }
    assert {"is_hidden", "hidden_at"} <= visit_columns


def test_manifest_only_contains_enabled_clans_in_config_order():
    manifest = build_sky_manifest(CLANS)
    assert [(row["clan_tag"], row["sort_order"]) for row in manifest["clans"]] == [
        ("#AAA", 0),
        ("#BBB", 1),
    ]
    assert manifest["config_hash"] == build_sky_manifest(CLANS)["config_hash"]


def test_migration_is_idempotent_and_does_not_infer_legacy_roles(db):
    _add_wechat_user(db, "member-openid", "member")
    _add_wechat_user(db, "legacy-admin-openid", "admin")

    first = apply_sky_migration(db.conn, CLANS, now="2026-10-09T00:00:00+00:00")
    second = apply_sky_migration(db.conn, CLANS, now="2026-10-09T00:05:00+00:00")

    assert first["alliance"]["id"] == second["alliance"]["id"]
    assert second["changes"]["member_assignments_to_apply"] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM alliances").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM alliance_clans").fetchone()[0] == 2
    assert db.conn.execute("SELECT COUNT(*) FROM alliance_members").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM alliance_audit_events").fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT role FROM wechat_users WHERE openid = 'legacy-admin-openid'"
    ).fetchone()[0] == "admin"


def test_explicit_memberships_are_applied_and_audited(db):
    member_id = _add_wechat_user(db, "member-openid")
    leader_id = _add_wechat_user(db, "leader-openid")
    assignments = [
        {"user_id": member_id, "role": "member"},
        {"user_id": leader_id, "role": "leader"},
    ]

    result = apply_sky_migration(db.conn, CLANS, assignments)

    rows = db.conn.execute(
        "SELECT user_id, role, status FROM alliance_members ORDER BY user_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (member_id, "member", "active"),
        (leader_id, "leader", "active"),
    ]
    assert result["applied_members_by_role"] == {"member": 1, "leader": 1}


def test_existing_sky_users_default_to_admin_with_reviewed_overrides(db):
    first = _add_wechat_user(db, "first", "member")
    second = _add_wechat_user(db, "second", "admin")

    assignments = build_existing_user_assignments(
        db.conn, [{"user_id": second, "role": "leader"}]
    )

    assert assignments == [
        {"user_id": first, "role": "admin"},
        {"user_id": second, "role": "leader"},
    ]


def test_member_validation_rejects_unknown_user_and_multiple_leaders(db):
    first = _add_wechat_user(db, "one")
    second = _add_wechat_user(db, "two")
    with pytest.raises(ValueError, match="does not exist"):
        apply_sky_migration(db.conn, CLANS, [{"user_id": 999, "role": "member"}])
    with pytest.raises(ValueError, match="at most one"):
        apply_sky_migration(
            db.conn,
            CLANS,
            [{"user_id": first, "role": "leader"}, {"user_id": second, "role": "leader"}],
        )


def test_plan_limits_and_role_enums_are_database_constraints(db):
    apply_sky_migration(db.conn, CLANS)
    user_id = _add_wechat_user(db, "user")
    now = "2026-10-09T00:00:00+00:00"
    db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_by_user_id, created_at, updated_at)
           VALUES ('free-1', '我的部落', 'active', 'free', ?, ?, ?)""",
        (user_id, now, now),
    )
    free_id = int(db.conn.execute("SELECT id FROM alliances WHERE alliance_key='free-1'").fetchone()[0])
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, status, created_at, updated_at)
           VALUES (?, '#ONE', 'active', ?, ?)""",
        (free_id, now, now),
    )
    db.conn.executemany(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, status, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?)""",
        [(free_id, "#TWO", now, now), (free_id, "#THREE", now, now)],
    )
    with pytest.raises(sqlite3.IntegrityError, match="active clan limit"):
        db.conn.execute(
            """INSERT INTO alliance_clans
               (alliance_id, clan_tag, status, created_at, updated_at)
               VALUES (?, '#FOUR', 'active', ?, ?)""",
            (free_id, now, now),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
        db.conn.execute(
            """INSERT INTO alliance_members
               (alliance_id, user_id, role, status, created_at, updated_at)
               VALUES (?, ?, 'owner', 'active', ?, ?)""",
            (free_id, user_id, now, now),
        )


def test_database_separates_user_and_platform_free_alliance_limits(db):
    apply_sky_migration(db.conn, CLANS)
    user_id = _add_wechat_user(db, "creator")
    now = "2026-10-09T00:00:00+00:00"
    db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, creation_source,
            created_by_user_id, created_at, updated_at)
           VALUES ('free-a', 'A', 'active', 'free', 'user', ?, ?, ?)""",
        (user_id, now, now),
    )
    db.conn.execute(
        """CREATE UNIQUE INDEX idx_alliances_one_active_free_per_creator
           ON alliances(created_by_user_id)
           WHERE plan_code='free' AND status='active'
             AND created_by_user_id IS NOT NULL"""
    )
    db.conn.commit()
    db._migrate()
    db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, creation_source,
            created_by_user_id, created_at, updated_at)
           VALUES ('platform-b', 'B', 'active', 'free', 'platform', ?, ?, ?)""",
        (user_id, now, now),
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM alliances WHERE created_by_user_id=? AND status='active'",
        (user_id,),
    ).fetchone()[0] == 2
    assert db.conn.execute(
        """SELECT COUNT(*) FROM sqlite_master
           WHERE type='index' AND name='idx_alliances_one_active_user_free'"""
    ).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
        db.conn.execute(
            """INSERT INTO alliances
               (alliance_key, name, status, plan_code, creation_source,
                created_by_user_id, created_at, updated_at)
               VALUES ('free-c', 'C', 'active', 'free', 'user', ?, ?, ?)""",
            (user_id, now, now),
        )


def test_migration_removes_legacy_global_verification_triggers(db):
    for name in (
        "trg_alliance_clans_one_verified_insert",
        "trg_alliance_clans_one_verified_update",
        "trg_alliances_one_verified_on_activate",
    ):
        db.conn.execute(
            f"""CREATE TRIGGER {name}
                BEFORE UPDATE ON alliances
                BEGIN SELECT 1; END"""
        )
    db.conn.commit()

    db._migrate()

    assert db.conn.execute(
        """SELECT COUNT(*) FROM sqlite_master
           WHERE type='trigger' AND name IN (?, ?, ?)""",
        (
            "trg_alliance_clans_one_verified_insert",
            "trg_alliance_clans_one_verified_update",
            "trg_alliances_one_verified_on_activate",
        ),
    ).fetchone()[0] == 0


def test_plan_change_cannot_bypass_active_clan_limit(db):
    apply_sky_migration(db.conn, CLANS)
    sky_id = _alliance_id(db)
    now = "2026-10-09T00:00:00+00:00"
    db.conn.executemany(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, status, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?)""",
        [(sky_id, "#CCC", now, now), (sky_id, "#DDD", now, now)],
    )
    with pytest.raises(sqlite3.IntegrityError, match="plan change"):
        db.conn.execute(
            "UPDATE alliances SET plan_code = 'free' WHERE alliance_key = ?",
            (SKY_ALLIANCE_KEY,),
        )


def test_memberships_and_subscriptions_are_isolated_by_alliance(db):
    apply_sky_migration(db.conn, CLANS)
    user_id = _add_wechat_user(db, "multi-alliance-user")
    now = "2026-10-09T00:00:00+00:00"
    db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES ('paid-a', 'A联盟', 'active', 'premium', ?, ?)""",
        (now, now),
    )
    sky_id = _alliance_id(db)
    paid_id = int(db.conn.execute("SELECT id FROM alliances WHERE alliance_key='paid-a'").fetchone()[0])
    db.conn.executemany(
        """INSERT INTO alliance_members
           (alliance_id, user_id, role, status, created_at, updated_at)
           VALUES (?, ?, ?, 'active', ?, ?)""",
        [(sky_id, user_id, "member", now, now), (paid_id, user_id, "admin", now, now)],
    )
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, status, created_at, updated_at)
           VALUES (?, '#AAA', 'active', ?, ?)""",
        (paid_id, now, now),
    )

    roles = db.conn.execute(
        "SELECT alliance_id, role FROM alliance_members WHERE user_id = ? ORDER BY alliance_id",
        (user_id,),
    ).fetchall()
    assert [tuple(row) for row in roles] == [(sky_id, "member"), (paid_id, "admin")]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM alliance_clans WHERE clan_tag = '#AAA' AND status = 'active'"
    ).fetchone()[0] == 2


def test_database_allows_same_clan_verified_by_multiple_alliances(db):
    apply_sky_migration(db.conn, CLANS)
    now = "2026-10-09T00:00:00+00:00"
    db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES ('paid-verified', '认证测试联盟', 'active', 'premium', ?, ?)""",
        (now, now),
    )
    paid_id = int(db.conn.execute(
        "SELECT id FROM alliances WHERE alliance_key='paid-verified'"
    ).fetchone()[0])
    db.conn.execute(
        """INSERT INTO alliance_clans
           (alliance_id, clan_tag, status, verification_status, created_at, updated_at)
           VALUES (?, '#AAA', 'active', 'verified', ?, ?)""",
        (paid_id, now, now),
    )

    assert db.conn.execute(
        """SELECT COUNT(*) FROM alliance_clans
           WHERE clan_tag='#AAA' AND status='active' AND verification_status='verified'"""
    ).fetchone()[0] == 2


def test_plan_catalog_defines_three_user_tiers_and_migrates_legacy_paid(db):
    apply_sky_migration(db.conn, CLANS)
    now = "2026-10-09T00:00:00+00:00"
    plans = {
        row["plan_code"]: dict(row)
        for row in db.conn.execute(
            """SELECT plan_code, max_clans, sync_tier, status
               FROM alliance_plans"""
        ).fetchall()
    }
    assert (plans["free"]["max_clans"], plans["free"]["sync_tier"]) == (3, "low")
    assert (plans["standard"]["max_clans"], plans["standard"]["sync_tier"]) == (10, "low")
    assert (plans["premium"]["max_clans"], plans["premium"]["sync_tier"]) == (10, "high")

    db.conn.execute(
        """INSERT INTO alliance_plans
           (plan_code, display_name, max_clans, sync_tier, entitlements_json,
            status, created_at, updated_at)
           VALUES ('paid', '旧付费版', 10, 'high', '{}', 'active', ?, ?)""",
        (now, now),
    )
    alliance_id = db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES ('legacy-paid', '旧付费联盟', 'active', 'paid', ?, ?)""",
        (now, now),
    ).lastrowid
    db.conn.execute(
        """INSERT INTO alliance_plan_grants
           (alliance_id, plan_code, status, starts_at, expires_at,
            created_at, updated_at)
           VALUES (?, 'paid', 'active', ?, '2027-10-09T00:00:00+00:00', ?, ?)""",
        (alliance_id, now, now, now),
    )

    migrated = ensure_plan_catalog(db.conn, now=now)

    assert migrated["migrated_alliances"] == 1
    assert migrated["migrated_grants"] == 1
    assert db.conn.execute(
        "SELECT plan_code FROM alliances WHERE id=?", (alliance_id,),
    ).fetchone()[0] == "premium"
    assert db.conn.execute(
        "SELECT plan_code FROM alliance_plan_grants WHERE alliance_id=?", (alliance_id,),
    ).fetchone()[0] == "premium"
    assert tuple(db.conn.execute(
        "SELECT display_name, status FROM alliance_plans WHERE plan_code='paid'",
    ).fetchone()) == ("历史付费版", "inactive")


def test_plan_catalog_preserves_internal_operational_configuration(db):
    apply_sky_migration(db.conn, CLANS)
    db.conn.execute(
        """UPDATE alliance_plans
           SET max_clans=55,
               entitlements_json='{"max_cwl_teams": 42, "custom_internal": true}'
           WHERE plan_code='internal'"""
    )

    ensure_plan_catalog(db.conn, now="2026-10-19T00:00:00+00:00")

    row = db.conn.execute(
        """SELECT max_clans, sync_tier, entitlements_json
           FROM alliance_plans WHERE plan_code='internal'"""
    ).fetchone()
    assert row["max_clans"] == 55
    assert row["sync_tier"] == "internal"
    assert json.loads(row["entitlements_json"]) == {
        "max_cwl_teams": 42,
        "custom_internal": True,
    }


def test_preview_is_read_only_and_reports_config_drift(db):
    apply_sky_migration(db.conn, CLANS)
    before = db.conn.total_changes
    changed = [dict(item) for item in CLANS]
    changed[0]["name"] = "一营新名"

    preview = preview_sky_migration(db.conn, changed)

    assert db.conn.total_changes == before
    assert preview["changes"]["clans_to_insert_or_update"] == ["#AAA"]
    assert preview["legacy_wechat_users"]["legacy_role_inference_used"] is False


def test_config_clans_removed_from_manifest_are_deactivated(db):
    apply_sky_migration(db.conn, CLANS)
    apply_sky_migration(db.conn, CLANS[:1])
    status = db.conn.execute(
        "SELECT status FROM alliance_clans WHERE alliance_id = ? AND clan_tag = '#BBB'",
        (_alliance_id(db),),
    ).fetchone()[0]
    assert status == "inactive"


def test_current_config_round_trips_to_sky_mapping(db):
    import config

    manifest = build_sky_manifest(config.CLANS)
    apply_sky_migration(db.conn, config.CLANS)
    rows = db.conn.execute(
        """SELECT clan_tag, clan_name, category, sort_order, verification_status
           FROM alliance_clans WHERE alliance_id = ? AND status = 'active'
           ORDER BY sort_order""",
        (_alliance_id(db),),
    ).fetchall()
    assert [dict(row) for row in rows] == manifest["clans"]
