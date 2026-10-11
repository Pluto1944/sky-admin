from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import api_server.alliance_routes as alliance_routes
import scripts.scheduler as scheduler
from modules.alliance.access import resolve_alliance_context
from modules.alliance.free_alliance import (
    FreeAllianceError,
    archive_free_alliance,
    create_free_alliance,
    enqueue_initialization,
    free_alliance_capability,
    reconcile_sync_targets,
    rename_free_alliance,
    request_manual_refresh,
    subscribe_free_clan,
    subscription_status,
)
from modules.alliance.migration import apply_sky_migration


NOW = datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)
NOW_TEXT = NOW.isoformat(timespec="seconds")
SKY_CLANS = [{"tag": "#2QQ", "name": "苍穹战营", "category": "combat", "enabled": True}]


def _user(db, openid: str) -> int:
    cursor = db.conn.execute(
        """INSERT INTO wechat_users (openid, role, created_at, updated_at)
           VALUES (?, 'member', ?, ?)""",
        (openid, NOW_TEXT, NOW_TEXT),
    )
    db.conn.commit()
    return int(cursor.lastrowid)


@pytest.fixture
def m5(db, monkeypatch):
    apply_sky_migration(db.conn, SKY_CLANS, now=NOW_TEXT)
    monkeypatch.setenv("M5_FREE_ALLIANCE_ENABLED", "true")
    monkeypatch.setenv("M5_FREE_ALLIANCE_OPENIDS", "owner-a,owner-b")
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv(
        "SYNC_QUEUE_LIVE_TYPES", "clan_profile,clan_members,current_war,cwl_live",
    )
    _user(db, "owner-a")
    _user(db, "owner-b")
    return db


def test_create_rename_subscribe_and_audit_without_granting_management(m5):
    alliance_id = create_free_alliance(m5.conn, "owner-a", now=NOW)
    assert free_alliance_capability(m5.conn, "owner-a")["can_create"] is False
    rename_free_alliance(m5.conn, "owner-a", alliance_id, "秋雨小队", now=NOW)
    clan = subscribe_free_clan(
        m5.conn,
        "owner-a",
        alliance_id,
        clan_tag="2qq",
        clan_name="云深不知处 战营",
        category="combat",
        now=NOW,
    )

    context = resolve_alliance_context(m5.conn, "owner-a", alliance_id)
    assert context is not None
    assert context.alliance_name == "秋雨小队"
    assert context.role == "leader"
    assert context.plan_code == "free"
    assert clan["clan_tag"] == "#2QQ"
    assert context.clan("#2QQ").effective_access == "member"
    assert m5.conn.execute(
        "SELECT COUNT(*) FROM alliance_audit_events WHERE alliance_id=?",
        (alliance_id,),
    ).fetchone()[0] == 3

    with pytest.raises(FreeAllianceError, match="只能创建一个"):
        create_free_alliance(m5.conn, "owner-a", now=NOW)


def test_subscription_rejects_unreviewed_replacement_and_invalid_category(m5):
    alliance_id = create_free_alliance(m5.conn, "owner-a", now=NOW)
    subscribe_free_clan(
        m5.conn, "owner-a", alliance_id,
        clan_tag="#2QQ", category="normal", now=NOW,
    )
    with pytest.raises(FreeAllianceError, match="暂不支持直接更换"):
        subscribe_free_clan(
            m5.conn, "owner-a", alliance_id,
            clan_tag="#9PY", category="normal", now=NOW,
        )
    with pytest.raises(FreeAllianceError, match="仅支持"):
        subscribe_free_clan(
            m5.conn, "owner-a", alliance_id,
            clan_tag="#2QQ", category="other", now=NOW,
        )


def test_shared_clan_initialization_creates_one_target_and_deduplicates_tasks(m5):
    alliance_a = create_free_alliance(m5.conn, "owner-a", now=NOW)
    alliance_b = create_free_alliance(m5.conn, "owner-b", now=NOW)
    for openid, alliance_id in (("owner-a", alliance_a), ("owner-b", alliance_b)):
        subscribe_free_clan(
            m5.conn, openid, alliance_id,
            clan_tag="#9PY", category="combat", now=NOW,
        )
        context = resolve_alliance_context(m5.conn, openid, alliance_id)
        enqueue_initialization(
            m5.conn,
            alliance_id=alliance_id,
            clan_tag="#9PY",
            actor_user_id=context.user_id,
            now=NOW,
        )

    targets = m5.conn.execute(
        """SELECT resource_type, interest_count, alliance_count
           FROM sync_targets WHERE resource_key='#9PY' AND status='active'
           ORDER BY resource_type"""
    ).fetchall()
    assert [(row["resource_type"], row["interest_count"], row["alliance_count"]) for row in targets] == [
        ("clan_members", 2, 2),
        ("clan_profile", 2, 2),
        ("current_war", 2, 2),
    ]
    assert m5.conn.execute(
        """SELECT COUNT(*) FROM sync_tasks
           WHERE resource_key='#9PY' AND mode='live'
             AND status IN ('pending','running','retry_wait')"""
    ).fetchone()[0] == 3


def test_initialization_reuses_fresh_cache_and_manual_refresh_has_shared_cooldown(m5):
    alliance_id = create_free_alliance(m5.conn, "owner-a", now=NOW)
    subscribe_free_clan(
        m5.conn, "owner-a", alliance_id,
        clan_tag="#2QQ", category="combat", now=NOW,
    )
    m5.conn.execute(
        """INSERT INTO clan_profile_cache
           (clan_tag, clan_name, category, status, data_json, updated_at, attempted_at)
           VALUES ('#2QQ', '缓存部落', 'combat', 'success', '{}', ?, ?)""",
        (NOW_TEXT, NOW_TEXT),
    )
    m5.conn.commit()
    context = resolve_alliance_context(m5.conn, "owner-a", alliance_id)
    initialized = enqueue_initialization(
        m5.conn, alliance_id=alliance_id, clan_tag="#2QQ",
        actor_user_id=context.user_id, now=NOW,
    )
    assert next(item for item in initialized if item["resource_type"] == "clan_profile")["reason"] == "cache_fresh"
    assert m5.conn.execute(
        "SELECT COUNT(*) FROM sync_tasks WHERE resource_type='clan_profile' AND resource_key='#2QQ'"
    ).fetchone()[0] == 0

    first = request_manual_refresh(
        m5.conn, "owner-a", alliance_id, "#2QQ", now=NOW + timedelta(minutes=2),
    )
    second = request_manual_refresh(
        m5.conn, "owner-a", alliance_id, "#2QQ", now=NOW + timedelta(minutes=3),
    )
    assert first[0]["reason"] in {"queued", "deduplicated"}
    assert second[0]["accepted"] is False
    assert second[0]["reason"] in {"deduplicated", "cooldown"}


def test_archive_is_audited_and_never_deletes_shared_facts(m5):
    alliance_a = create_free_alliance(m5.conn, "owner-a", now=NOW)
    alliance_b = create_free_alliance(m5.conn, "owner-b", now=NOW)
    for openid, alliance_id in (("owner-a", alliance_a), ("owner-b", alliance_b)):
        subscribe_free_clan(
            m5.conn, openid, alliance_id,
            clan_tag="#9PY", category="combat", now=NOW,
        )
    m5.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, updated_at)
           VALUES ('#9PY', '共享部落', 'combat', 'not_in_war', '{}', ?)""",
        (NOW_TEXT,),
    )
    m5.conn.commit()
    reconcile_sync_targets(m5.conn, now=NOW)

    archive_free_alliance(m5.conn, "owner-a", alliance_a, now=NOW)
    reconcile_sync_targets(m5.conn, now=NOW)
    target = m5.conn.execute(
        """SELECT status, alliance_count FROM sync_targets
           WHERE resource_type='current_war' AND resource_key='#9PY'"""
    ).fetchone()
    assert tuple(target) == ("active", 1)
    assert m5.conn.execute(
        "SELECT COUNT(*) FROM current_war_cache WHERE clan_tag='#9PY'"
    ).fetchone()[0] == 1
    assert m5.conn.execute(
        """SELECT COUNT(*) FROM alliance_audit_events
           WHERE alliance_id=? AND action='free_alliance_archived'""",
        (alliance_a,),
    ).fetchone()[0] == 1

    archive_free_alliance(m5.conn, "owner-b", alliance_b, now=NOW)
    reconcile_sync_targets(m5.conn, now=NOW)
    assert m5.conn.execute(
        """SELECT status FROM sync_targets
           WHERE resource_type='current_war' AND resource_key='#9PY'"""
    ).fetchone()[0] == "inactive"
    assert m5.conn.execute(
        "SELECT COUNT(*) FROM current_war_cache WHERE clan_tag='#9PY'"
    ).fetchone()[0] == 1


def test_route_payload_exposes_capability_and_async_status(m5):
    response = alliance_routes.my_alliances(user={"openid": "owner-a"}, db=m5)
    assert response["features"]["free_alliance"]["can_create"] is True
    created = alliance_routes.create_my_free_alliance(
        alliance_routes.FreeAllianceCreateInput(name=None),
        user={"openid": "owner-a"}, db=m5,
    )
    alliance_id = created["id"]
    saved = alliance_routes.save_free_subscription(
        alliance_id,
        alliance_routes.FreeClanSubscriptionInput(
            clan_tag="#2QQ", category="combat", clan_name=None,
        ),
        user={"openid": "owner-a"}, db=m5,
    )
    assert saved["clan"]["clan_tag"] == "#2QQ"
    assert {item["state"] for item in saved["sync"]} <= {
        "pending", "running", "retry_wait", "ready", "partial", "failed",
    }
    assert len(subscription_status(m5.conn, alliance_id, "#2QQ")) == 3


def test_free_only_clan_is_excluded_from_daily_player_detail_scan(m5, monkeypatch):
    monkeypatch.setattr(scheduler.config, "CLANS", [])
    alliance_id = create_free_alliance(m5.conn, "owner-a", now=NOW)
    subscribe_free_clan(
        m5.conn, "owner-a", alliance_id,
        clan_tag="#9PY", category="normal", now=NOW,
    )
    assert "#9PY" not in scheduler._player_detail_clan_tags(m5)

    m5.conn.execute(
        "UPDATE alliances SET plan_code='paid' WHERE id=?", (alliance_id,),
    )
    m5.conn.commit()
    assert "#9PY" in scheduler._player_detail_clan_tags(m5)
