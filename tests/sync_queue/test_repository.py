from datetime import datetime, timedelta, timezone

import pytest

from modules.sync_queue.repository import SyncQueueError, SyncQueueRepository


NOW = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)


def _interest(source: str, resource: str, priority: str, interval: int) -> dict:
    return {
        "source_type": "test",
        "source_key": source,
        "alliance_id": None,
        "resource_type": "current_war",
        "resource_key": resource,
        "priority": priority,
        "desired_interval_seconds": interval,
        "metadata": {"source": source},
    }


def _build_targets(repo: SyncQueueRepository, interests: list[dict]) -> None:
    repo.reconcile_interests(interests, managed_source_types=("test",), now=NOW)
    repo.rebuild_targets(now=NOW)


def test_reconcile_and_target_aggregation_globally_deduplicates(db):
    repo = SyncQueueRepository(db.conn)
    result = repo.reconcile_interests(
        [
            _interest("alliance-1", "#2QQ", "scheduled", 1800),
            _interest("alliance-2", "#2QQ", "realtime", 120),
        ],
        managed_source_types=("test",),
        now=NOW,
    )
    assert result == {
        "inserted": 2,
        "updated": 0,
        "deactivated": 0,
        "unchanged": 0,
        "active": 2,
    }

    targets = repo.rebuild_targets(now=NOW)
    assert targets["active"] == 1
    row = db.conn.execute("SELECT * FROM sync_targets").fetchone()
    assert row["resource_key"] == "#2QQ"
    assert row["priority"] == "realtime"
    assert row["desired_interval_seconds"] == 120
    assert row["interest_count"] == 2

    unchanged = repo.reconcile_interests(
        [
            _interest("alliance-1", "#2QQ", "scheduled", 1800),
            _interest("alliance-2", "#2QQ", "realtime", 120),
        ],
        managed_source_types=("test",),
        now=NOW + timedelta(minutes=1),
    )
    assert unchanged["unchanged"] == 2


def test_shadow_planning_is_due_based_and_does_not_create_live_work(db):
    repo = SyncQueueRepository(db.conn)
    _build_targets(repo, [_interest("one", "#2QQ", "realtime", 120)])

    first = repo.plan_due_tasks(mode="shadow", now=NOW)
    second = repo.plan_due_tasks(mode="shadow", now=NOW + timedelta(seconds=60))
    third = repo.plan_due_tasks(mode="shadow", now=NOW + timedelta(seconds=120))

    assert len(first) == 1
    assert first[0]["status"] == "shadowed"
    assert first[0]["finished_at"] is not None
    assert second == []
    assert len(third) == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM sync_tasks WHERE mode = 'live'"
    ).fetchone()[0] == 0


def test_claim_respects_priority_and_retry_backoff(db):
    repo = SyncQueueRepository(db.conn)
    _build_targets(
        repo,
        [
            _interest("slow", "#SLOW", "backfill", 3600),
            _interest("fast", "#FAST", "realtime", 120),
        ],
    )
    assert len(repo.plan_due_tasks(mode="live", now=NOW)) == 2

    claimed = repo.claim_tasks("worker-a", limit=1, lease_seconds=30, now=NOW)
    assert [task["resource_key"] for task in claimed] == ["#FAST"]
    task_id = claimed[0]["id"]
    assert claimed[0]["attempt_count"] == 1

    status = repo.fail_task(
        task_id,
        "worker-a",
        error="temporary",
        error_type="Timeout",
        base_backoff_seconds=60,
        now=NOW,
    )
    assert status == "retry_wait"
    assert repo.claim_tasks(
        "worker-a", priorities=("realtime",), now=NOW + timedelta(seconds=59)
    ) == []

    retried = repo.claim_tasks(
        "worker-a", priorities=("realtime",), now=NOW + timedelta(seconds=60)
    )
    assert retried[0]["id"] == task_id
    assert retried[0]["attempt_count"] == 2
    repo.complete_task(
        task_id,
        "worker-a",
        result={"ok": True},
        external_request_count=1,
        now=NOW + timedelta(seconds=61),
    )
    row = db.conn.execute("SELECT * FROM sync_tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["status"] == "succeeded"
    attempts = db.conn.execute(
        "SELECT status, duration_ms FROM sync_attempts WHERE task_id = ? ORDER BY attempt_no",
        (task_id,),
    ).fetchall()
    assert [item["status"] for item in attempts] == ["failed", "succeeded"]
    assert [item["duration_ms"] for item in attempts] == [0, 1000]


def test_expired_lease_is_recovered_and_owner_is_enforced(db):
    repo = SyncQueueRepository(db.conn)
    _build_targets(repo, [_interest("one", "#2QQ", "interactive", 600)])
    task = repo.plan_due_tasks(mode="live", now=NOW)[0]
    claimed = repo.claim_tasks("worker-a", lease_seconds=30, now=NOW)[0]
    assert claimed["id"] == task["id"]

    with pytest.raises(SyncQueueError):
        repo.complete_task(task["id"], "worker-b", now=NOW + timedelta(seconds=1))

    assert repo.recover_expired_leases(now=NOW + timedelta(seconds=31)) == 1
    recovered = db.conn.execute(
        "SELECT status, lease_owner FROM sync_tasks WHERE id = ?", (task["id"],)
    ).fetchone()
    assert dict(recovered) == {"status": "retry_wait", "lease_owner": None}
    attempt = db.conn.execute(
        "SELECT status, error_type FROM sync_attempts WHERE task_id = ?", (task["id"],)
    ).fetchone()
    assert dict(attempt) == {"status": "interrupted", "error_type": "LeaseExpired"}


def test_retryable_failure_stops_at_max_attempts(db):
    repo = SyncQueueRepository(db.conn)
    _build_targets(repo, [_interest("one", "#2QQ", "realtime", 120)])
    task = repo.plan_due_tasks(mode="live", now=NOW, max_attempts=2)[0]

    repo.claim_tasks("worker", now=NOW)
    assert repo.fail_task(
        task["id"], "worker", error="one", base_backoff_seconds=10, now=NOW
    ) == "retry_wait"
    repo.claim_tasks("worker", now=NOW + timedelta(seconds=10))
    assert repo.fail_task(
        task["id"],
        "worker",
        error="two",
        base_backoff_seconds=10,
        now=NOW + timedelta(seconds=11),
    ) == "dead"
    assert repo.claim_tasks("worker", now=NOW + timedelta(hours=1)) == []
    assert db.conn.execute(
        "SELECT attempt_count FROM sync_tasks WHERE id = ?", (task["id"],)
    ).fetchone()[0] == 2


def test_stale_interest_deactivates_target_and_cancels_pending_live_task(db):
    repo = SyncQueueRepository(db.conn)
    _build_targets(repo, [_interest("one", "#2QQ", "scheduled", 300)])
    task = repo.plan_due_tasks(mode="live", now=NOW)[0]

    result = repo.reconcile_interests(
        [], managed_source_types=("test",), now=NOW + timedelta(minutes=1)
    )
    assert result["deactivated"] == 1
    targets = repo.rebuild_targets(now=NOW + timedelta(minutes=1))
    assert targets["deactivated"] == 1
    assert db.conn.execute(
        "SELECT status FROM sync_tasks WHERE id = ?", (task["id"],)
    ).fetchone()[0] == "cancelled"


def test_sync_queue_tables_are_part_of_database_reset(db):
    expected = {"sync_interests", "sync_targets", "sync_tasks", "sync_attempts"}
    before = {
        row[0]
        for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert expected <= before
    db.reset()
    after = {
        row[0]
        for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert expected <= after
