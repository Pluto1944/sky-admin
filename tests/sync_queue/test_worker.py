from datetime import datetime, timezone
import sys

import config
from modules.sync_queue.repository import SyncQueueRepository
from modules.sync_queue.handlers import SyncTaskExecutionError
from scripts import sync_worker
from shared.db.connection import Database


NOW = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def test_worker_rejects_live_types_when_enable_switch_is_off(monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "current_war")
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", ["sync_worker.py", "--once"])

    assert sync_worker.main() == 2


def _queued_database(path) -> None:
    db = Database(str(path))
    db.init_schema()
    repo = SyncQueueRepository(db.conn)
    repo.reconcile_interests(
        [{
            "source_type": "test",
            "source_key": "one",
            "alliance_id": None,
            "resource_type": "current_war",
            "resource_key": "#2QQ",
            "priority": "realtime",
            "desired_interval_seconds": 120,
        }],
        managed_source_types=("test",),
        now=NOW,
    )
    repo.rebuild_targets(now=NOW)
    repo.set_target_modes(("current_war",), now=NOW)
    repo.plan_due_tasks(mode="live", now=NOW)
    db.close()


def test_worker_completes_claimed_task_and_attempt(monkeypatch, tmp_path):
    path = tmp_path / "worker.db"
    _queued_database(path)
    monkeypatch.setattr(config, "DB_PATH", str(path))
    monkeypatch.setattr(
        sync_worker,
        "execute_resource_task",
        lambda resource_type, resource_key: {
            "status": "success", "reason": f"{resource_type}:{resource_key}",
        },
    )
    worker = sync_worker.SyncWorker(
        resource_types=("current_war",), concurrency=1, poll_seconds=0.01,
        worker_id="test-worker",
    )
    try:
        result = worker.run(once=True)
    finally:
        worker.close()

    check = Database(str(path))
    task = check.conn.execute("SELECT * FROM sync_tasks WHERE mode = 'live'").fetchone()
    attempt = check.conn.execute("SELECT * FROM sync_attempts").fetchone()
    run = check.conn.execute(
        "SELECT * FROM sync_job_runs WHERE job_id = 'sync_worker:current_war'"
    ).fetchone()
    check.close()
    assert result == {"claimed": 1, "settled": 1}
    assert task["status"] == "succeeded"
    assert attempt["status"] == "succeeded"
    assert run["status"] == "success"


def test_worker_marks_non_retryable_handler_error_failed(monkeypatch, tmp_path):
    path = tmp_path / "worker-failure.db"
    _queued_database(path)
    monkeypatch.setattr(config, "DB_PATH", str(path))

    def fail(_resource_type, _resource_key):
        raise SyncTaskExecutionError("invalid target", retryable=False)

    monkeypatch.setattr(sync_worker, "execute_resource_task", fail)
    worker = sync_worker.SyncWorker(
        resource_types=("current_war",), concurrency=1, poll_seconds=0.01,
        worker_id="test-worker",
    )
    try:
        worker.run(once=True)
    finally:
        worker.close()

    check = Database(str(path))
    task = check.conn.execute("SELECT status, attempt_count FROM sync_tasks").fetchone()
    check.close()
    assert dict(task) == {"status": "failed", "attempt_count": 1}
