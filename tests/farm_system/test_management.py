from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import HTTPException

from api_server.farm_system_routes import clan_detail, require_farm_manager
from modules.farm_system.management import (
    ClanProfileUnavailableError,
    FarmManagementService,
    FarmPermissionError,
)
from modules.farm_system.repository import FarmAccountRepository
from modules.farm_system.rounds import FarmRoundService
from modules.farm_system.service import FarmAuthService


def _account(db, username: str, role: str):
    email = username if "@" in username else f"{username}@example.com"
    return FarmAuthService(FarmAccountRepository(db.conn)).create_account(
        username=email,
        display_name=username,
        password="strong-password",
        role=role,
    )


def _cache_profile(db, tag="#YCOC", official_tag="#YC0C", name="测试部落", **fields):
    profile = {"clan_tag": official_tag, "name": name, **fields}
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


def test_clan_list_sorts_by_last_enabled_and_transfer_does_not_change_it(db, monkeypatch):
    creator = dict(_account(db, "creator.one", "creator"))
    first_account = dict(_account(db, "member.one", "member"))
    second_account = dict(_account(db, "member.two", "member"))
    _cache_profile(db, tag="#2QQ", official_tag="#2QQ", name="较早启用")
    _cache_profile(db, tag="#8P8", official_tag="#8P8", name="较晚启用")
    timestamps = iter([
        "2026-10-24T01:00:00+00:00",
        "2026-10-24T02:00:00+00:00",
        "2026-10-24T03:00:00+00:00",
        "2026-10-24T04:00:00+00:00",
        "2026-10-24T05:00:00+00:00",
    ])
    monkeypatch.setattr("modules.farm_system.repository.now_iso", lambda: next(timestamps))
    service = FarmManagementService(db.conn)

    early = service.create_clan(
        creator, {"clan_tag": "#2QQ", "account_id": first_account["id"]}
    )
    late = service.create_clan(
        creator, {"clan_tag": "#8P8", "account_id": first_account["id"]}
    )
    assert [row["id"] for row in service.list_clans(creator)] == [late["id"], early["id"]]

    transferred = service.transfer_clan(creator, "#2QQ", second_account["id"])
    assert transferred["enabled_at"] == "2026-10-24T01:00:00+00:00"
    disabled = service.update_clan(creator, "#2QQ", {"status": "disabled"})
    assert disabled["enabled_at"] == "2026-10-24T01:00:00+00:00"
    enabled = service.update_clan(creator, "#2QQ", {"status": "active"})
    assert enabled["enabled_at"] == "2026-10-24T05:00:00+00:00"
    assert service.list_clans(creator)[0]["id"] == early["id"]


def test_account_reads_cached_clan_detail_without_live_api(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    outsider = dict(_account(db, "member.two", "member"))
    _cache_profile(
        db,
        description="欢迎加入",
        location={"id": 32000006, "name": "China", "country_code": "CN"},
        official_member_count=47,
        clan_level=20,
    )
    _cache_profile(
        db,
        tag="#2QQ",
        official_tag="#2QQ",
        name="互刷对手",
        description="对手部落公告",
        location={"id": 32000006, "name": "China", "country_code": "CN"},
        official_member_count=45,
        clan_level=18,
    )
    service = FarmManagementService(db.conn)
    clan = service.create_clan(
        creator, {"clan_tag": "#YCOC", "account_id": member["id"]}
    )
    round_row = FarmRoundService(db.conn).create_round(
        creator, {"scheduled_at": "2026-10-24T20:20:00+08:00"}
    )
    db.conn.execute(
        """UPDATE farm_round_clans
           SET registration_status='internal_matched', opponent_tag='#2QQ',
               opponent_name='互刷对手', result='win', score_after=1
           WHERE round_id=? AND clan_id=?""",
        (round_row["id"], clan["id"]),
    )
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, error, updated_at,
            attempted_at, failure_count, payload_version)
           VALUES (?, ?, 'farm', 'success', ?, NULL, ?, ?, 0, 1)""",
        (
            "#YCOC", "测试部落",
            json.dumps({
                "status": "preparation", "state": "preparation", "team_size": 50,
                "opponent": {"tag": "#WAR", "name": "官方战争对手"},
                "result": "pending", "rows": [{"position": 1}],
            }),
            "2026-10-24T12:00:00+00:00", "2026-10-24T12:00:00+00:00",
        ),
    )
    db.conn.commit()

    result = service.get_clan_detail(member, "#YC0C")

    assert result["profile_status"] == "success"
    assert result["profile"]["description"] == "欢迎加入"
    assert result["profile"]["location"]["name"] == "China"
    assert result["profile"]["official_member_count"] == 47
    assert result["current_war"]["opponent"]["name"] == "官方战争对手"
    assert "rows" not in result["current_war"]
    assert result["farm_round"]["id"] == round_row["id"]
    assert result["farm_registration"]["opponent_name"] == "互刷对手"
    assert result["farm_registration"]["result"] == "win"
    assert result["opponent"]["source"] == "farm_registration"
    assert result["opponent"]["clan_tag"] == "#2QQ"
    assert result["opponent"]["profile"]["description"] == "对手部落公告"
    payload = clan_detail("#YC0C", member, db)
    assert payload["clan"]["enabled_at"]
    assert payload["profile"]["clan_level"] == 20
    assert payload["current_war_source"] == "current_war_cache"
    assert payload["opponent"]["profile"]["official_member_count"] == 45
    with pytest.raises(FarmPermissionError):
        service.get_clan_detail(outsider, "#YC0C")


def test_clan_detail_does_not_use_normal_war_as_farm_opponent(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    _cache_profile(db)
    service = FarmManagementService(db.conn)
    clan = service.create_clan(
        creator, {"clan_tag": "#YCOC", "account_id": member["id"]}
    )
    round_row = FarmRoundService(db.conn).create_round(
        creator, {"scheduled_at": "2026-10-24T20:20:00+08:00"}
    )
    db.conn.execute(
        """INSERT INTO farm_registration_attempts
           (round_id, clan_id, requested_by, outcome, official_state,
            opponent_tag, opponent_name, duration_ms, summary_json, created_at)
           VALUES (?, ?, ?, 'not_in_war', 'preparation', '#WAR', '登记战争对手', 12, ?, ?)""",
        (
            round_row["id"], clan["id"], member["id"],
            json.dumps({
                "status": "preparation", "state": "preparation",
                "opponent": {"tag": "#WAR", "name": "登记战争对手"},
            }),
            "2026-10-24T12:10:00+00:00",
        ),
    )
    db.conn.commit()

    result = service.get_clan_detail(member, "#YC0C")

    assert result["current_war_source"] == "registration_attempt"
    assert result["current_war"]["opponent"]["name"] == "登记战争对手"
    assert result["current_war_updated_at"] == "2026-10-24T12:10:00+00:00"
    assert result["opponent"] is None
