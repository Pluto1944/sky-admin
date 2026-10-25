from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from modules.farm_system.clan_sync import FarmClanSyncService
from modules.farm_system.management import FarmManagementService, FarmPermissionError
from modules.farm_system.repository import FarmAccountRepository
from modules.farm_system.rounds import FarmRoundService
from modules.farm_system.service import FarmAuthService


def _account(db, username: str, role: str):
    return dict(FarmAuthService(FarmAccountRepository(db.conn)).create_account(
        username=f"{username}@example.com",
        display_name=username,
        password="strong-password",
        role=role,
    ))


def _profile(db, tag="#2QQ", name="官方部落"):
    db.conn.execute(
        """INSERT INTO clan_profile_cache
           (clan_tag, clan_name, category, status, data_json, error,
            updated_at, attempted_at)
           VALUES (?, ?, 'farm', 'success', ?, NULL, ?, ?)""",
        (tag, name, json.dumps({"clan_tag": tag, "name": name}),
         "2026-10-22T00:00:00+00:00", "2026-10-22T00:00:00+00:00"),
    )
    db.conn.commit()


def test_new_clan_validation_queues_live_profile_sync(db, monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile")
    creator = _account(db, "creator", "creator")
    member = _account(db, "member", "member")

    result = FarmClanSyncService(db.conn).request(creator, "2QQ", member["id"])

    assert result["status"] == "syncing"
    assert result["task_status"] == "pending"
    assert db.conn.execute(
        """SELECT COUNT(*) FROM sync_interests
           WHERE source_type='farm_clan_request' AND resource_key='#2QQ'"""
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM sync_tasks WHERE resource_type='clan_profile' AND status='pending'"
    ).fetchone()[0] == 1


def test_clan_validation_becomes_ready_only_after_official_cache(db, monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile")
    creator = _account(db, "creator", "creator")
    member = _account(db, "member", "member")
    service = FarmClanSyncService(db.conn)
    service.request(creator, "#2QQ", member["id"])

    assert service.status(creator, "#2QQ", member["id"])["status"] == "syncing"
    _profile(db)
    ready = service.status(creator, "#2QQ", member["id"])

    assert ready["status"] == "ready"
    assert ready["clan_name"] == "官方部落"


def test_cached_profile_skips_new_sync_task_and_member_cannot_request(db, monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile")
    creator = _account(db, "creator", "creator")
    member = _account(db, "member", "member")
    _profile(db)
    service = FarmClanSyncService(db.conn)

    ready = service.request(creator, "#2QQ", member["id"])
    assert ready["status"] == "ready"
    assert db.conn.execute("SELECT COUNT(*) FROM sync_tasks").fetchone()[0] == 0
    with pytest.raises(FarmPermissionError):
        service.request(member, "#2QQ", member["id"])


def test_detail_open_queues_only_stale_source_and_farm_opponent_profiles(
    db, monkeypatch,
):
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile")
    creator = dict(_account(db, "creator", "creator"))
    member = dict(_account(db, "member", "member"))
    opponent_owner = dict(_account(db, "opponent", "member"))
    _profile(db, tag="#2QQ", name="本方部落")
    _profile(db, tag="#9PY", name="互刷对手")
    management = FarmManagementService(db.conn)
    source = management.create_clan(
        creator, {"clan_tag": "#2QQ", "account_id": member["id"]}
    )
    management.create_clan(
        creator, {"clan_tag": "#9PY", "account_id": opponent_owner["id"]}
    )
    round_row = FarmRoundService(db.conn).create_round(
        creator, {"scheduled_at": "2026-10-25T20:20:00+08:00"}
    )
    db.conn.execute(
        """UPDATE farm_round_clans
           SET registration_status='internal_matched', opponent_tag='#9PY',
               opponent_name='互刷对手', result='win'
           WHERE round_id=? AND clan_id=?""",
        (round_row["id"], source["id"]),
    )
    db.conn.commit()

    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    result = FarmClanSyncService(db.conn).request_detail_profiles(
        member, "#2QQ", now=now
    )

    assert [item["kind"] for item in result["profiles"]] == ["source", "opponent"]
    assert {item["reason"] for item in result["profiles"]} == {"queued"}
    tasks = db.conn.execute(
        "SELECT resource_type, resource_key, status FROM sync_tasks ORDER BY id"
    ).fetchall()
    assert [(row["resource_type"], row["resource_key"], row["status"]) for row in tasks] == [
        ("clan_profile", "#2QQ", "pending"),
        ("clan_profile", "#9PY", "pending"),
    ]


def test_detail_open_respects_six_hour_profile_ttl_and_global_dedupe(db, monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile")
    creator = dict(_account(db, "creator", "creator"))
    member = dict(_account(db, "member", "member"))
    _profile(db, tag="#2QQ", name="本方部落")
    FarmManagementService(db.conn).create_clan(
        creator, {"clan_tag": "#2QQ", "account_id": member["id"]}
    )
    service = FarmClanSyncService(db.conn)
    cached_at = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)

    fresh = service.request_detail_profiles(
        member, "#2QQ", now=cached_at + timedelta(hours=5, minutes=59)
    )
    stale = service.request_detail_profiles(
        member, "#2QQ", now=cached_at + timedelta(hours=6)
    )
    repeated = service.request_detail_profiles(
        member, "#2QQ", now=cached_at + timedelta(hours=6, minutes=1)
    )

    assert fresh["profiles"][0]["reason"] == "fresh"
    assert stale["profiles"][0]["reason"] == "queued"
    assert repeated["profiles"][0]["reason"] in {"deduplicated", "cooldown"}
    assert db.conn.execute(
        "SELECT COUNT(*) FROM sync_tasks WHERE resource_type='clan_profile'"
    ).fetchone()[0] == 1


def test_detail_profile_refresh_uses_same_clan_access_control(db, monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile")
    creator = dict(_account(db, "creator", "creator"))
    member = dict(_account(db, "member", "member"))
    outsider = dict(_account(db, "outsider", "member"))
    _profile(db, tag="#2QQ", name="本方部落")
    FarmManagementService(db.conn).create_clan(
        creator, {"clan_tag": "#2QQ", "account_id": member["id"]}
    )

    with pytest.raises(FarmPermissionError):
        FarmClanSyncService(db.conn).request_detail_profiles(
            outsider,
            "#2QQ",
            now=datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc),
        )
