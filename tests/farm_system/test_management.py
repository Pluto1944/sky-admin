from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import HTTPException

from api_server.farm_system_routes import require_farm_manager
from modules.farm_system.management import (
    ClanProfileUnavailableError,
    FarmManagementService,
    FarmPermissionError,
)
from modules.farm_system.repository import FarmAccountRepository
from modules.farm_system.service import FarmAuthService


def _account(db, username: str, role: str):
    email = username if "@" in username else f"{username}@example.com"
    return FarmAuthService(FarmAccountRepository(db.conn)).create_account(
        username=email,
        display_name=username,
        password="strong-password",
        role=role,
    )


def _cache_profile(db, tag="#YCOC", official_tag="#YC0C", name="测试部落"):
    profile = {"clan_tag": official_tag, "name": name}
    db.conn.execute(
        """INSERT INTO clan_profile_cache
           (clan_tag, clan_name, category, status, data_json, error, updated_at, attempted_at)
           VALUES (?, ?, 'farm', 'success', ?, NULL, '2026-10-11T00:00:00Z', '2026-10-11T00:00:00Z')""",
        (tag, name, json.dumps(profile)),
    )
    db.conn.commit()


def test_member_cannot_use_management_api_dependency(db):
    member = dict(_account(db, "member.one", "member"))
    with pytest.raises(HTTPException) as exc:
        require_farm_manager(member)
    assert exc.value.status_code == 403


def test_admin_cannot_modify_creator_or_promote_member(db):
    creator = dict(_account(db, "creator.one", "creator"))
    admin = dict(_account(db, "admin.one", "admin"))
    member = dict(_account(db, "member.one", "member"))
    service = FarmManagementService(db.conn)

    with pytest.raises(FarmPermissionError):
        service.update_account(admin, creator["id"], {"status": "disabled"})
    with pytest.raises(FarmPermissionError):
        service.update_account(admin, member["id"], {"role": "admin"})
    with pytest.raises(FarmPermissionError):
        service.update_account(creator, creator["id"], {"status": "disabled"})
    with pytest.raises(FarmPermissionError):
        service.create_account(
            creator,
            {"username": "creator.two@example.com", "display_name": "创建者二",
             "password": "strong-password", "role": "creator"},
        )


def test_create_clan_requires_cached_official_profile_and_normalizes_o_to_zero(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    service = FarmManagementService(db.conn)

    with pytest.raises(ClanProfileUnavailableError):
        service.create_clan(creator, {"clan_tag": "#YCOC", "account_id": member["id"]})

    _cache_profile(db)
    clan = service.create_clan(
        creator, {"clan_tag": "YCOC", "account_id": member["id"]}
    )
    assert clan["clan_tag"] == "#YC0C"
    assert clan["score"] == 0

    with pytest.raises(sqlite3.IntegrityError):
        service.create_clan(
            creator, {"clan_tag": "#YC0C", "account_id": member["id"]}
        )


def test_transfer_keeps_score_and_member_only_sees_own_clans(db):
    creator = dict(_account(db, "creator.one", "creator"))
    first = dict(_account(db, "member.one", "member"))
    second = dict(_account(db, "member.two", "member"))
    _cache_profile(db)
    service = FarmManagementService(db.conn)
    clan = service.create_clan(
        creator, {"clan_tag": "#YCOC", "account_id": first["id"]}
    )
    db.conn.execute("UPDATE farm_clans SET score = 7 WHERE id = ?", (clan["id"],))
    db.conn.commit()

    transferred = service.transfer_clan(creator, "#YC0C", second["id"])
    assert transferred["account_id"] == second["id"]
    assert transferred["score"] == 7
    assert service.list_own_clans(first) == []
    assert [row["clan_tag"] for row in service.list_own_clans(second)] == ["#YC0C"]


def test_transfer_rejects_missing_or_disabled_target(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    _cache_profile(db)
    service = FarmManagementService(db.conn)
    service.create_clan(creator, {"clan_tag": "#YC0C", "account_id": member["id"]})

    with pytest.raises(LookupError):
        service.transfer_clan(creator, "#YC0C", 99999)
    FarmAccountRepository(db.conn).set_status(member["id"], "disabled")
    with pytest.raises(ValueError):
        service.transfer_clan(creator, "#YC0C", member["id"])
