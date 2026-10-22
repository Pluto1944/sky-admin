from __future__ import annotations

import json

import pytest

from modules.farm_system.clan_sync import FarmClanSyncService
from modules.farm_system.management import FarmPermissionError
from modules.farm_system.repository import FarmAccountRepository
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
