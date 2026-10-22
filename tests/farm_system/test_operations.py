from __future__ import annotations

import pytest

from modules.farm_system.operations import CreatorPermissionError, FarmCreatorOperations
from modules.farm_system.registration import FarmRegistrationService
from modules.farm_system.repository import FarmAccountRepository, FarmClanRepository
from modules.farm_system.rounds import FarmRoundService
from modules.farm_system.service import FarmAuthService
from tests.farm_system.test_registration import FakeCocClient, _setup_pair, _war


def _account(db, username: str, role: str = "member"):
    email = username if "@" in username else f"{username}@example.com"
    return FarmAuthService(FarmAccountRepository(db.conn)).create_account(
        username=email,
        display_name=username,
        password="strong-password",
        role=role,
    )


def test_revoke_match_restores_scores_with_reversal_and_is_idempotent(db):
    creator, first, _, clan_a, clan_b, round_row = _setup_pair(db)
    registration = FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB")))
    registration.register(first, round_row["id"], "#AAA")
    match_id = db.conn.execute("SELECT id FROM farm_matches").fetchone()[0]

    operations = FarmCreatorOperations(db.conn)
    result = operations.revoke_match(creator, match_id, "官方数据登记错误")
    repeated = operations.revoke_match(creator, match_id, "重复请求不会再次冲销")

    assert result["status"] == "revoked" and not result["reused"]
    assert repeated["reused"]
    scores = [
        db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan_id,)).fetchone()[0]
        for clan_id in (clan_a["id"], clan_b["id"])
    ]
    assert scores == [-1, 2]
    assert db.conn.execute("SELECT COUNT(*) FROM farm_score_ledger").fetchone()[0] == 4
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_score_ledger WHERE entry_type = 'reversal'"
    ).fetchone()[0] == 2
    statuses = {
        row[0] for row in db.conn.execute("SELECT registration_status FROM farm_round_clans")
    }
    assert statuses == {"revoked"}


def test_non_creator_cannot_revoke(db):
    creator, first, _, _, _, round_row = _setup_pair(db)
    FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB"))).register(
        first, round_row["id"], "#AAA"
    )
    match_id = db.conn.execute("SELECT id FROM farm_matches").fetchone()[0]
    with pytest.raises(CreatorPermissionError):
        FarmCreatorOperations(db.conn).revoke_match(first, match_id, "无权撤销测试")


def test_revoked_match_stays_blocked_until_creator_reopens(db):
    creator, first, _, clan_a, clan_b, round_row = _setup_pair(db)
    first_client = FakeCocClient(_war("#AAA", "#BBB"))
    FarmRegistrationService(db.conn, first_client).register(first, round_row["id"], "#AAA")
    match_id = db.conn.execute("SELECT id FROM farm_matches").fetchone()[0]
    operations = FarmCreatorOperations(db.conn)
    operations.revoke_match(creator, match_id, "官方结果错误")

    blocked_client = FakeCocClient(_war("#AAA", "#BBB"))
    blocked = FarmRegistrationService(db.conn, blocked_client).register(
        first, round_row["id"], "#AAA"
    )
    assert blocked["registration_status"] == "revoked"
    assert blocked["reused"] is True
    assert blocked_client.calls == 0

    reopened = operations.reopen_match(creator, match_id)
    repeated = operations.reopen_match(creator, match_id)
    assert reopened["status"] == "reopened" and not reopened["reused"]
    assert reopened["round_status"] == "open"
    assert repeated["reused"] is True
    assert {
        row[0] for row in db.conn.execute("SELECT registration_status FROM farm_round_clans")
    } == {"not_registered"}

    registered = FarmRegistrationService(
        db.conn, FakeCocClient(_war("#AAA", "#BBB"))
    ).register(first, round_row["id"], "#AAA")
    duplicate = FarmRegistrationService(
        db.conn, FakeCocClient(_war("#AAA", "#BBB"))
    ).register(first, round_row["id"], "#AAA")
    assert registered["registration_status"] == "internal_matched"
    assert duplicate["reused"] is True
    assert db.conn.execute("SELECT COUNT(*) FROM farm_matches").fetchone()[0] == 2
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_matches WHERE status='revoked'"
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_score_ledger"
    ).fetchone()[0] == 6
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_score_ledger WHERE entry_type='reversal'"
    ).fetchone()[0] == 2
    assert [
        db.conn.execute("SELECT score FROM farm_clans WHERE id=?", (clan_id,)).fetchone()[0]
        for clan_id in (clan_a["id"], clan_b["id"])
    ] == [0, 1]


def test_non_creator_cannot_reopen_match(db):
    creator, first, _, _, _, round_row = _setup_pair(db)
    FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB"))).register(
        first, round_row["id"], "#AAA"
    )
    match_id = db.conn.execute("SELECT id FROM farm_matches").fetchone()[0]
    operations = FarmCreatorOperations(db.conn)
    operations.revoke_match(creator, match_id, "官方结果错误")
    with pytest.raises(CreatorPermissionError):
        operations.reopen_match(first, match_id)


def test_cancel_round_rolls_back_all_matches_when_one_reversal_fails(db):
    creator = dict(_account(db, "creator.one", "creator"))
    owners = [dict(_account(db, f"member.{index}")) for index in range(1, 5)]
    clans = []
    for owner, tag in zip(owners, ("#AAA", "#BBB", "#CCC", "#DDD")):
        clans.append(
            FarmClanRepository(db.conn).create_clan(
                clan_tag=tag,
                clan_name=tag,
                account_id=owner["id"],
                actor_account_id=creator["id"],
            )
        )
    rounds = FarmRoundService(db.conn)
    round_row = rounds.create_round(
        creator,
        {"scheduled_at": "2026-10-12T11:15:00+08:00", "business_time_kind": "preparation_start"},
    )
    rounds.update_round(creator, round_row["id"], {"status": "open"})
    FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB"))).register(
        owners[0], round_row["id"], "#AAA"
    )
    FarmRegistrationService(db.conn, FakeCocClient(_war("#CCC", "#DDD"))).register(
        owners[2], round_row["id"], "#CCC"
    )
    scores_before = [
        db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan["id"],)).fetchone()[0]
        for clan in clans
    ]

    def fail_second(index, match):
        if index == 1:
            raise RuntimeError("injected cancel failure")

    with pytest.raises(RuntimeError, match="injected"):
        FarmCreatorOperations(
            db.conn, before_match_revoke=fail_second
        ).cancel_round(creator, round_row["id"], "整场数据错误")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_matches WHERE status = 'settled'"
    ).fetchone()[0] == 2
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_score_ledger WHERE entry_type = 'reversal'"
    ).fetchone()[0] == 0
    scores_after = [
        db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan["id"],)).fetchone()[0]
        for clan in clans
    ]
    assert scores_after == scores_before
    assert db.conn.execute("SELECT status FROM farm_rounds").fetchone()[0] == "completed"


def test_cancel_round_reverses_all_and_is_idempotent(db):
    creator, first, _, clan_a, clan_b, round_row = _setup_pair(db)
    FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB"))).register(
        first, round_row["id"], "#AAA"
    )
    operations = FarmCreatorOperations(db.conn)
    result = operations.cancel_round(creator, round_row["id"], "整场时间录入错误")
    repeated = operations.cancel_round(creator, round_row["id"], "重复取消请求")

    assert result == {"round_id": round_row["id"], "status": "cancelled", "reused": False}
    assert repeated["reused"]
    assert [
        db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan_id,)).fetchone()[0]
        for clan_id in (clan_a["id"], clan_b["id"])
    ] == [-1, 2]
