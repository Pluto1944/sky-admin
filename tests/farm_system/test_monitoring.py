from __future__ import annotations

from datetime import datetime, timezone

import pytest

from modules.farm_system.management import FarmPermissionError
from modules.farm_system.monitoring import (
    FarmMonitoringService,
    save_monitor_error,
    save_monitor_snapshot,
)
from modules.farm_system.registration import FarmRegistrationService
from tests.farm_system.test_registration import FakeCocClient, _account, _setup_pair, _war


def test_round_creation_seeds_monitor_and_overview(db):
    creator, _, _, _, _, round_row = _setup_pair(db)

    count = db.conn.execute(
        "SELECT COUNT(*) FROM farm_round_monitors WHERE round_id = ?",
        (round_row["id"],),
    ).fetchone()[0]
    overview = FarmMonitoringService(db.conn).overview(creator)

    assert count == 2
    assert overview["war"] == {
        "total": 2,
        "detected": 0,
        "not_detected": 0,
        "unchecked": 2,
        "error": 0,
    }
    assert overview["registration"]["pending"] == 2
    assert overview["can_refresh"] is True


def test_monitor_overview_and_filtered_list_use_separate_status_dimensions(db):
    creator, first, _, clan_a, clan_b, round_row = _setup_pair(db)
    save_monitor_snapshot(
        db.conn,
        round_id=round_row["id"],
        clan_id=clan_a["id"],
        normalized={
            "status": "preparation",
            "preparation_start_time": "20261012T031500.000Z",
            "opponent": {"tag": "#BBB", "name": "二部落"},
        },
        source="test",
    )
    save_monitor_error(
        db.conn,
        round_id=round_row["id"],
        clan_id=clan_b["id"],
        error="temporary",
        source="test",
    )
    db.conn.execute(
        """UPDATE farm_round_clans
           SET registration_status='internal_matched', result='win', score_after=0
           WHERE round_id=? AND clan_id=?""",
        (round_row["id"], clan_a["id"]),
    )
    db.conn.commit()

    service = FarmMonitoringService(db.conn)
    overview = service.overview(creator)
    detected = service.list_clans(creator, status_filter="war_detected")
    unregistered = service.list_clans(
        creator,
        status_filter="unregistered",
        search=first["username"],
    )

    assert overview["war"]["detected"] == 1
    assert overview["war"]["error"] == 1
    assert overview["registration"]["registered"] == 1
    assert overview["results"]["win"] == 1
    assert [item["clan_id"] for item in detected["clans"]] == [clan_a["id"]]
    assert unregistered["total"] == 0


def test_only_super_admin_can_request_monitor_refresh(db):
    creator, first, _, _, _, round_row = _setup_pair(db)
    admin = dict(_account(db, "admin.one", "admin"))
    service = FarmMonitoringService(db.conn)

    with pytest.raises(FarmPermissionError):
        service.request_refresh(admin, round_row["id"])

    result = service.request_refresh(creator, round_row["id"])
    assert result["queued"] == 2
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_audit_logs WHERE action='monitor.refresh_requested'"
    ).fetchone()[0] == 1
    assert first["role"] == "member"


def test_completed_round_cannot_queue_monitor_refresh(db):
    creator, _, _, _, _, round_row = _setup_pair(db)
    db.conn.execute(
        "UPDATE farm_rounds SET status='completed' WHERE id=?", (round_row["id"],)
    )
    db.conn.commit()

    service = FarmMonitoringService(db.conn)
    overview = service.overview(creator, round_row["id"])

    assert overview["can_refresh"] is False
    with pytest.raises(ValueError, match="已完成场次"):
        service.request_refresh(creator, round_row["id"])


def test_monitor_job_processes_a_bounded_due_batch(db):
    creator, _, _, _, _, round_row = _setup_pair(db)
    client = FakeCocClient(_war("#AAA", "#BBB"))
    result = FarmMonitoringService(db.conn, client).run_due(
        now=datetime(2026, 10, 12, 3, 20, tzinfo=timezone.utc),
        limit=1,
    )

    assert result["checked"] == 1
    assert client.calls == 1
    statuses = db.conn.execute(
        "SELECT war_status FROM farm_round_monitors WHERE round_id=? ORDER BY clan_id",
        (round_row["id"],),
    ).fetchall()
    assert [row[0] for row in statuses].count("preparation") == 1
    assert [row[0] for row in statuses].count("unchecked") == 1


def test_registration_immediately_updates_monitor_cache(db):
    creator, first, _, clan_a, _, round_row = _setup_pair(db)
    FarmRegistrationService(
        db.conn,
        FakeCocClient(_war("#AAA", "#OUTSIDE")),
    ).register(first, round_row["id"], "#AAA")

    row = db.conn.execute(
        """SELECT war_status, opponent_tag, source
           FROM farm_round_monitors WHERE round_id=? AND clan_id=?""",
        (round_row["id"], clan_a["id"]),
    ).fetchone()
    assert row["war_status"] == "preparation"
    assert row["opponent_tag"] == "#OUTSIDE"
    assert row["source"] == "registration"
    assert creator["role"] == "creator"
