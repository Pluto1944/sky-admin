from __future__ import annotations

import threading

import pytest

from modules.coc_sync.official.api_client import CocApiError
from modules.farm_system.registration import FarmRegistrationService, RegistrationError
from modules.farm_system.repository import FarmAccountRepository, FarmClanRepository
from modules.farm_system.rounds import FarmRoundService
from modules.farm_system.service import FarmAuthService
from shared.db.connection import Database


PREP_TIME = "20261012T031500.000Z"


class FakeCocClient:
    def __init__(self, payload=None, error=None, barrier=None):
        self.payload = payload
        self.error = error
        self.barrier = barrier
        self.calls = 0

    def get_current_war(self, clan_tag):
        self.calls += 1
        if self.barrier:
            self.barrier.wait(timeout=5)
        if self.error:
            raise self.error
        return self.payload


def _account(db, username: str, role: str = "member"):
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


def _open_round(
    db, creator, *, kind="preparation_start",
    scheduled_at="2026-10-12T11:15:00+08:00",
):
    service = FarmRoundService(db.conn)
    row = service.create_round(
        creator,
        {"scheduled_at": scheduled_at, "business_time_kind": kind},
    )
    return service.update_round(creator, row["id"], {"status": "open"})


def _war(clan_tag, opponent_tag, *, state="preparation", war_type=None,
         prep_time=PREP_TIME, attacks_per_member=2):
    payload = {
        "state": state,
        "teamSize": 15,
        "attacksPerMember": attacks_per_member,
        "preparationStartTime": prep_time,
        "startTime": "20261013T021500.000Z",
        "endTime": "20261014T021500.000Z",
        "clan": {"tag": clan_tag, "name": "本方", "members": []},
        "opponent": {"tag": opponent_tag, "name": "对手", "members": []},
    }
    if war_type is not None:
        payload["type"] = war_type
    return payload


def _setup_pair(db, score_a=-1, score_b=2):
    creator = dict(_account(db, "creator.one", "creator"))
    first = dict(_account(db, "member.one"))
    second = dict(_account(db, "member.two"))
    clan_a = _clan(db, creator, first, "#AAA", "一部落")
    clan_b = _clan(db, creator, second, "#BBB", "二部落")
    db.conn.execute("UPDATE farm_clans SET score = ? WHERE id = ?", (score_a, clan_a["id"]))
    db.conn.execute("UPDATE farm_clans SET score = ? WHERE id = ?", (score_b, clan_b["id"]))
    db.conn.commit()
    round_row = _open_round(db, creator)
    return creator, first, second, clan_a, clan_b, round_row


def test_f0_sample_accepts_search_time_against_preparation_start(db):
    creator = dict(_account(db, "creator.one", "creator"))
    first = dict(_account(db, "member.one"))
    second = dict(_account(db, "member.two"))
    _clan(db, creator, first, "#R88U8", "样本一")
    _clan(db, creator, second, "#U2UL", "样本二")
    round_row = _open_round(
        db, creator, kind="preparation_start",
        scheduled_at="2026-10-10T11:00:00+08:00",
    )
    payload = _war("#R88U8", "#U2UL", prep_time="20261010T031139.000Z")

    result = FarmRegistrationService(db.conn, FakeCocClient(payload)).register(
        first, round_row["id"], "#R88U8"
    )
    assert result["registration_status"] == "internal_matched"


def test_internal_match_settles_both_sides_and_is_idempotent(db):
    _, first, second, clan_a, clan_b, round_row = _setup_pair(db)
    client = FakeCocClient(_war("#AAA", "#BBB"))
    service = FarmRegistrationService(db.conn, client, choose_tie_winner=lambda pair: pair[0])

    result = service.register(first, round_row["id"], "#AAA")
    repeated = service.register(first, round_row["id"], "#AAA")

    assert result["result"] == "win"
    assert result["score_before"] == -1 and result["score_after"] == 0
    assert repeated["reused"] is True
    assert client.calls == 1
    assert db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan_a["id"],)).fetchone()[0] == 0
    assert db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan_b["id"],)).fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM farm_matches").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM farm_score_ledger").fetchone()[0] == 2
    other = service.register(second, round_row["id"], "#BBB")
    assert other["result"] == "loss" and other["reused"] is True
    assert db.conn.execute("SELECT time_locked_at FROM farm_rounds").fetchone()[0]


def test_equal_score_random_is_saved_once(db):
    _, first, _, _, _, round_row = _setup_pair(db, score_a=0, score_b=0)
    calls = []

    def choose(pair):
        calls.append(pair)
        return pair[1]

    client = FakeCocClient(_war("#AAA", "#BBB"))
    service = FarmRegistrationService(db.conn, client, choose_tie_winner=choose)
    first_result = service.register(first, round_row["id"], "#AAA")
    second_result = service.register(first, round_row["id"], "#AAA")

    assert first_result["result"] == "loss"
    assert second_result["result"] == "loss"
    assert len(calls) == 1
    match = db.conn.execute("SELECT tie_break_used, tie_break_value FROM farm_matches").fetchone()
    assert match["tie_break_used"] == 1 and match["tie_break_value"] is not None


def test_external_opponent_is_final_without_score_change(db):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one"))
    clan = _clan(db, creator, member, "#AAA", "一部落")
    db.conn.execute("UPDATE farm_clans SET score = 4 WHERE id = ?", (clan["id"],))
    db.conn.commit()
    round_row = _open_round(db, creator)
    result = FarmRegistrationService(
        db.conn, FakeCocClient(_war("#AAA", "#OUTSIDE"))
    ).register(member, round_row["id"], "#AAA")

    assert result["registration_status"] == "match_failed"
    assert result["score_before"] == result["score_after"] == 4
    assert db.conn.execute("SELECT COUNT(*) FROM farm_score_ledger").fetchone()[0] == 0
    assert db.conn.execute("SELECT match_type FROM farm_matches").fetchone()[0] == "failed_external"


@pytest.mark.parametrize(
    ("payload", "error", "expected"),
    [
        ({"state": "notInWar"}, None, "not_in_war"),
        (_war("#AAA", "#BBB", war_type="cwl", attacks_per_member=1), None, "war_mismatch"),
        (_war("#AAA", "#BBB", prep_time="20261010T031500.000Z"), None, "war_mismatch"),
        (None, CocApiError("temporary"), "fetch_failed"),
    ],
)
def test_retryable_results_never_change_score(db, payload, error, expected):
    creator = dict(_account(db, "creator.one", "creator"))
    member = dict(_account(db, "member.one"))
    clan = _clan(db, creator, member, "#AAA", "一部落")
    round_row = _open_round(db, creator)
    result = FarmRegistrationService(
        db.conn, FakeCocClient(payload, error=error)
    ).register(member, round_row["id"], "#AAA")

    assert result["registration_status"] == expected
    assert db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan["id"],)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM farm_matches").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM farm_score_ledger").fetchone()[0] == 0


def test_member_cannot_register_another_accounts_clan(db):
    _, first, second, _, _, round_row = _setup_pair(db)
    client = FakeCocClient(_war("#BBB", "#AAA"))
    with pytest.raises(RegistrationError) as exc:
        FarmRegistrationService(db.conn, client).register(first, round_row["id"], "#BBB")
    assert exc.value.status_code == 404
    assert client.calls == 0


def test_second_ledger_failure_rolls_back_whole_settlement(db):
    _, first, _, clan_a, clan_b, round_row = _setup_pair(db)

    def fail():
        raise RuntimeError("injected ledger failure")

    service = FarmRegistrationService(
        db.conn, FakeCocClient(_war("#AAA", "#BBB")), before_second_ledger=fail
    )
    with pytest.raises(RuntimeError, match="injected"):
        service.register(first, round_row["id"], "#AAA")

    assert db.conn.execute("SELECT COUNT(*) FROM farm_matches").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM farm_score_ledger").fetchone()[0] == 0
    scores = [
        db.conn.execute("SELECT score FROM farm_clans WHERE id = ?", (clan_id,)).fetchone()[0]
        for clan_id in (clan_a["id"], clan_b["id"])
    ]
    assert scores == [-1, 2]


def test_concurrent_registration_creates_one_match(tmp_path):
    path = tmp_path / "farm-concurrent.db"
    setup = Database(str(path))
    setup.init_schema()
    _, first, _, _, _, round_row = _setup_pair(setup)
    setup.close()

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker():
        database = Database(str(path))
        try:
            service = FarmRegistrationService(
                database.conn,
                FakeCocClient(_war("#AAA", "#BBB"), barrier=barrier),
                choose_tie_winner=lambda pair: pair[0],
            )
            results.append(service.register(first, round_row["id"], "#AAA"))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            database.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    check = Database(str(path))
    try:
        assert not errors
        assert len(results) == 2
        assert check.conn.execute("SELECT COUNT(*) FROM farm_matches").fetchone()[0] == 1
        assert check.conn.execute("SELECT COUNT(*) FROM farm_score_ledger").fetchone()[0] == 2
    finally:
        check.close()
