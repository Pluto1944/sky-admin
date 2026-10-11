#!/usr/bin/env python3
"""Bounded M4 live worker for globally deduplicated synchronization tasks."""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

import config  # noqa: E402
from modules.sync_queue.config import live_resource_types, worker_enabled  # noqa: E402
from modules.sync_queue.handlers import (  # noqa: E402
    SyncTaskExecutionError,
    execute_resource_task,
)
from modules.sync_queue.repository import SyncQueueRepository  # noqa: E402
from shared.db.connection import Database  # noqa: E402
from shared.observability import (  # noqa: E402
    capture_external_requests,
    finish_job_run,
    interrupt_running_job_runs,
    start_job_run,
)
from shared.runtime_identity import capture_runtime_identity  # noqa: E402
from shared.service_runtime import record_service_runtime, touch_service_runtime  # noqa: E402


@dataclass
class TaskOutcome:
    result: dict | None
    error: BaseException | None
    retryable: bool
    events: list


def _execute(task: dict) -> TaskOutcome:
    job_id = f"sync_worker:{task['resource_type']}"
    with capture_external_requests(job_id) as captured:
        try:
            result = execute_resource_task(task["resource_type"], task["resource_key"])
            return TaskOutcome(result=result, error=None, retryable=False, events=captured.events)
        except SyncTaskExecutionError as exc:
            return TaskOutcome(result=None, error=exc, retryable=exc.retryable, events=captured.events)
        except BaseException as exc:  # noqa: BLE001 - every claimed task must be settled
            return TaskOutcome(result=None, error=exc, retryable=True, events=captured.events)


class SyncWorker:
    def __init__(
        self,
        *,
        resource_types: tuple[str, ...],
        concurrency: int = 3,
        lease_seconds: int = 300,
        heartbeat_seconds: int = 30,
        poll_seconds: float = 2.0,
        worker_id: str | None = None,
    ):
        if not resource_types:
            raise ValueError("live resource types must not be empty")
        self.resource_types = resource_types
        self.concurrency = max(1, min(8, int(concurrency)))
        self.lease_seconds = max(60, int(lease_seconds))
        self.heartbeat_seconds = max(10, min(self.lease_seconds // 2, int(heartbeat_seconds)))
        self.poll_seconds = max(0.2, float(poll_seconds))
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.db = Database(config.DB_PATH)
        self.db.init_schema()
        self.queue = SyncQueueRepository(self.db.conn)
        self.executor = ThreadPoolExecutor(
            max_workers=self.concurrency,
            thread_name_prefix="sync-worker",
        )
        self.active: dict[Future, dict] = {}
        self.last_heartbeat = 0.0

    def close(self) -> None:
        self.executor.shutdown(wait=True)
        self.db.close()

    def _claim(self) -> int:
        capacity = self.concurrency - len(self.active)
        if capacity <= 0:
            return 0
        tasks = self.queue.claim_tasks(
            self.worker_id,
            limit=capacity,
            lease_seconds=self.lease_seconds,
            resource_types=self.resource_types,
        )
        for task in tasks:
            job_id = f"sync_worker:{task['resource_type']}"
            run_id = start_job_run(
                self.db.conn,
                job_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            future = self.executor.submit(_execute, task)
            self.active[future] = {"task": task, "run_id": run_id, "started": time.monotonic()}
        return len(tasks)

    def _heartbeat(self) -> None:
        current = time.monotonic()
        if current - self.last_heartbeat < self.heartbeat_seconds:
            return
        for details in self.active.values():
            self.queue.heartbeat(
                details["task"]["id"], self.worker_id,
                lease_seconds=self.lease_seconds,
            )
        touch_service_runtime(self.db.conn, "sync_worker")
        self.last_heartbeat = current

    def _settle(self) -> int:
        settled = 0
        for future in tuple(self.active):
            if not future.done():
                continue
            details = self.active.pop(future)
            task = details["task"]
            outcome = future.result()
            finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            duration_ms = max(0, round((time.monotonic() - details["started"]) * 1000))
            if outcome.error is None:
                self.queue.complete_task(
                    task["id"], self.worker_id,
                    result=outcome.result,
                    external_request_count=len(outcome.events),
                )
                status = "success"
                reason = (outcome.result or {}).get("reason", "")
            else:
                status = self.queue.fail_task(
                    task["id"], self.worker_id,
                    error=outcome.error,
                    error_type=type(outcome.error).__name__,
                    retryable=outcome.retryable,
                    external_request_count=len(outcome.events),
                )
                reason = str(outcome.error)
            finish_job_run(
                self.db.conn,
                run_id=details["run_id"],
                job_id=f"sync_worker:{task['resource_type']}",
                finished_at=finished_at,
                status="success" if outcome.error is None else "failed",
                duration_ms=duration_ms,
                reason=reason,
                events=outcome.events,
            )
            print(
                f"[{finished_at}] {task['resource_type']} task={task['id']} "
                f"status={status} requests={len(outcome.events)}",
                flush=True,
            )
            settled += 1
        return settled

    def run(self, *, once: bool = False) -> dict[str, int]:
        claimed = settled = 0
        while True:
            settled += self._settle()
            self._heartbeat()
            claimed += self._claim()
            if once and not self.active:
                break
            time.sleep(self.poll_seconds)
        return {"claimed": claimed, "settled": settled}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="drain one currently available batch")
    args = parser.parse_args()
    enabled = worker_enabled()
    types = live_resource_types()
    if types and not enabled:
        print(
            "SYNC_QUEUE_LIVE_TYPES is configured but SYNC_QUEUE_WORKER_ENABLED is false",
            file=sys.stderr,
        )
        return 2
    identity = capture_runtime_identity("sync_worker")
    runtime_db = Database(config.DB_PATH)
    runtime_db.init_schema()
    interrupt_running_job_runs(
        runtime_db.conn,
        interrupted_at=identity.started_at,
        reason="M4 Worker 进程重启，上一轮未正常结束",
        job_id_prefix="sync_worker:",
    )
    SyncQueueRepository(runtime_db.conn).interrupt_running_tasks(
        reason="M4 Worker 进程重启",
    )
    record_service_runtime(runtime_db.conn, identity)
    if not enabled or not types:
        if args.once:
            print("sync worker disabled or SYNC_QUEUE_LIVE_TYPES is empty")
            return 0
        # Keep the service visible and healthy while cut-over is empty.
        while True:
            touch_service_runtime(runtime_db.conn, "sync_worker")
            time.sleep(30)

    runtime_db.close()
    worker = SyncWorker(
        resource_types=types,
        concurrency=int(os.getenv("SYNC_QUEUE_WORKER_CONCURRENCY", "3")),
        lease_seconds=int(os.getenv("SYNC_QUEUE_LEASE_SECONDS", "300")),
        heartbeat_seconds=int(os.getenv("SYNC_QUEUE_HEARTBEAT_SECONDS", "30")),
        poll_seconds=float(os.getenv("SYNC_QUEUE_WORKER_POLL_SECONDS", "2")),
    )
    try:
        stats = worker.run(once=args.once)
        if args.once:
            print(f"claimed={stats['claimed']} settled={stats['settled']}")
    finally:
        worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
