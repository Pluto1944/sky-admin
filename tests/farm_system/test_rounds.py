from __future__ import annotations

import sqlite3

import pytest

from modules.farm_system.repository import FarmAccountRepository, FarmClanRepository
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


def _clan(db, actor, owner, tag, name):
    return FarmClanRepository(db.conn).create_clan(
        clan_tag=tag,
        clan_name=name,
        account_id=owner["id"],
        actor_account_id=actor["id"],
    )


def test_dashboard_without_round_has_stable_empty_state(db):
    member = dict(_account(db, "member.one", "member"))
    assert FarmRoundService(db.conn).dashboard(member) == {
        "round": None,
        "registered_count": 0,
        "total_count": 0,
        "clans": [],
    }


def test_dashboard_without_round_still_lists_bound_active_clans(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    first = _clan(db, creator, member, "#AAA", "一部落")
    disabled = _clan(db, creator, member, "#BBB", "二部落")
    FarmClanRepository(db.conn).update_clan(
        disabled["clan_tag"], status="disabled", actor_account_id=creator["id"]
    )

    dashboard = FarmRoundService(db.conn).dashboard(member)

    assert dashboard["round"] is None
    assert dashboard["total_count"] == 1
    assert dashboard["registered_count"] == 0
    assert dashboard["clans"] == [
        {
            "clan_id": first["id"],
            "account_id": member["id"],
            "clan_tag": "#AAA",
            "clan_name": "一部落",
            "score_before": 0,
            "current_score": 0,
            "registration_status": "not_registered",
            "match_id": None,
            "opponent_tag": None,
            "opponent_name": None,
            "result": None,
            "score_after": None,
            "registered_at": None,
            "last_attempt_at": None,
            "last_error": None,
        }
    ]


def test_create_round_snapshots_only_active_clans_and_uses_utc(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    first = _clan(db, creator, member, "#AAA", "一部落")
    second = _clan(db, creator, member, "#BBB", "二部落")
    FarmClanRepository(db.conn).update_clan(
        second["clan_tag"], status="disabled", actor_account_id=creator["id"]
    )

    round_row = FarmRoundService(db.conn).create_round(
        creator,
        {"scheduled_at": "2026-10-12T11:15:00+08:00"},
    )
    dashboard = FarmRoundService(db.conn).dashboard(member)

    assert round_row["scheduled_at"] == "2026-10-12T03:15:00+00:00"
    assert round_row["business_time_kind"] == "preparation_start"
    assert dashboard["round"]["scheduled_at_beijing"] == "2026-10-12T11:15:00+08:00"
    assert dashboard["total_count"] == 1
    assert dashboard["clans"][0]["clan_id"] == first["id"]


@pytest.mark.parametrize("kind", ["pending", "war_start", "unknown"])
def test_round_rejects_any_time_kind_other_than_search_start(db, kind):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    _clan(db, creator, member, "#AAA", "一部落")

    with pytest.raises(ValueError, match="固定为开始搜战时间"):
        FarmRoundService(db.conn).create_round(
            creator,
            {
                "scheduled_at": "2026-10-12T11:15:00+08:00",
                "business_time_kind": kind,
            },
        )


def test_only_one_current_round_is_allowed(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    _clan(db, creator, member, "#AAA", "一部落")
    service = FarmRoundService(db.conn)
    service.create_round(creator, {"scheduled_at": "2026-10-12T11:15:00+08:00"})

    with pytest.raises(sqlite3.IntegrityError):
        service.create_round(creator, {"scheduled_at": "2026-10-13T11:15:00+08:00"})


def test_round_ownership_snapshot_does_not_change_after_transfer(db):
    creator = dict(_account(db, "creator.one", "creator"))
    first = dict(_account(db, "member.one", "member"))
    second = dict(_account(db, "member.two", "member"))
    clan = _clan(db, creator, first, "#AAA", "一部落")
    rounds = FarmRoundService(db.conn)
    rounds.create_round(creator, {"scheduled_at": "2026-10-12T11:15:00+08:00"})
    FarmClanRepository(db.conn).transfer(
        clan["clan_tag"], account_id=second["id"], actor_account_id=creator["id"]
    )

    assert rounds.dashboard(first)["total_count"] == 1
    assert rounds.dashboard(second)["total_count"] == 0


def test_locked_round_time_cannot_be_changed(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    _clan(db, creator, member, "#AAA", "一部落")
    service = FarmRoundService(db.conn)
    row = service.create_round(creator, {"scheduled_at": "2026-10-12T11:15:00+08:00"})
    db.conn.execute(
        "UPDATE farm_rounds SET time_locked_at = '2026-10-12T04:00:00+00:00' WHERE id = ?",
        (row["id"],),
    )
    db.conn.commit()

    with pytest.raises(ValueError, match="不能修改统一时间"):
        service.update_round(
            creator, row["id"], {"scheduled_at": "2026-10-12T11:20:00+08:00"}
        )


def test_open_round_time_can_be_changed_before_first_final_registration(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one", "member"))
    _clan(db, creator, member, "#AAA", "一部落")
    service = FarmRoundService(db.conn)
    row = service.create_round(creator, {"scheduled_at": "2026-10-12T11:15:00+08:00"})
    service.update_round(creator, row["id"], {"status": "open"})

    updated = service.update_round(
        creator, row["id"], {"scheduled_at": "2026-10-12T11:20:00+08:00"}
    )

    assert updated["status"] == "open"
    assert updated["scheduled_at"] == "2026-10-12T03:20:00+00:00"
    assert updated["time_locked_at"] is None
