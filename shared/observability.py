"""Best-effort observability for scheduler jobs and external requests.

The request timer is deliberately independent from SQLite.  Network clients
only append sanitized events to the active in-process collector; the scheduler
flushes them after the business job has finished.  Metrics failures must never
change a synchronization result.
"""
from __future__ import annotations

import json
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator
from urllib.error import HTTPError, URLError


DEFAULT_RETENTION_DAYS = 30
_MAX_TEXT_LENGTH = 500


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _limited(value: object | None, limit: int = _MAX_TEXT_LENGTH) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


@dataclass(frozen=True)
class ExternalRequestEvent:
    job_id: str
    provider: str
    operation: str
    resource_key: str | None
    outcome: str
    http_status: int | None
    duration_ms: int
    error_type: str | None
    started_at: str


@dataclass
class RequestCollector:
    job_id: str
    events: list[ExternalRequestEvent]


_collector: ContextVar[RequestCollector | None] = ContextVar(
    "external_request_collector", default=None,
)


class ExternalRequestObservation:
    """Mutable result used when a client handles an error without raising it."""

    def __init__(self) -> None:
        self.outcome = "success"
        self.http_status: int | None = None
        self.error_type: str | None = None

    def mark_failed(
        self,
        outcome: str = "error",
        *,
        http_status: int | None = None,
        error_type: str | None = None,
    ) -> None:
        self.outcome = outcome
        self.http_status = http_status
        self.error_type = _limited(error_type, 120)

    def set_http_status(self, status: object) -> None:
        if isinstance(status, int) and 100 <= status <= 599:
            self.http_status = status


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _classify_exception(exc: BaseException) -> tuple[str, int | None, str]:
    chain = list(_exception_chain(exc))
    http_status: int | None = None
    for item in chain:
        code = getattr(item, "code", None)
        if isinstance(code, int) and 100 <= code <= 599:
            http_status = code
            break
        response = getattr(item, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 100 <= status_code <= 599:
            http_status = status_code
            break

    error_type = type(chain[0]).__name__
    if http_status == 429:
        return "rate_limited", http_status, error_type
    if http_status is not None:
        return "http_error", http_status, error_type
    if any(
        isinstance(item, (TimeoutError, subprocess.TimeoutExpired))
        or "timeout" in type(item).__name__.lower()
        for item in chain
    ):
        return "timeout", None, error_type
    if any(isinstance(item, URLError) for item in chain):
        return "network_error", None, error_type
    if any(isinstance(item, json.JSONDecodeError) for item in chain):
        return "invalid_response", None, error_type
    return "error", None, error_type


@contextmanager
def capture_external_requests(job_id: str) -> Iterator[RequestCollector]:
    """Collect instrumented network calls made inside one scheduler job."""
    collector = RequestCollector(job_id=job_id, events=[])
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)


@contextmanager
def observe_external_request(
    provider: str,
    operation: str,
    *,
    resource_key: str | None = None,
    expected_http_statuses: tuple[int, ...] = (),
) -> Iterator[ExternalRequestObservation]:
    """Time one external request when a scheduler collector is active.

    Callers may use ``mark_failed`` for failures represented by return values.
    Raised exceptions are classified automatically, including wrapped causes.
    No event is persisted here and no credentials or response bodies are kept.
    """
    collector = _collector.get()
    observation = ExternalRequestObservation()
    if collector is None:
        yield observation
        return

    started_at = _utc_now_iso()
    started = time.monotonic()
    try:
        yield observation
    except BaseException as exc:
        if observation.outcome == "success":
            outcome, status, error_type = _classify_exception(exc)
            if status in expected_http_statuses:
                outcome = "expected_http_status"
            observation.mark_failed(
                outcome, http_status=status, error_type=error_type,
            )
        raise
    finally:
        collector.events.append(
            ExternalRequestEvent(
                job_id=collector.job_id,
                provider=_limited(provider, 80) or "unknown",
                operation=_limited(operation, 120) or "request",
                resource_key=_limited(resource_key, 180),
                outcome=observation.outcome,
                http_status=observation.http_status,
                duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                error_type=observation.error_type,
                started_at=started_at,
            )
        )


def start_job_run(conn, job_id: str, started_at: str) -> int:
    cursor = conn.execute(
        "INSERT INTO sync_job_runs (job_id, started_at, status) VALUES (?, ?, 'running')",
        (job_id, started_at),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_job_run(
    conn,
    *,
    run_id: int,
    job_id: str,
    finished_at: str,
    status: str,
    duration_ms: int,
    reason: str,
    events: list[ExternalRequestEvent],
) -> None:
    successful_outcomes = {"success", "expected_http_status"}
    failures = sum(event.outcome not in successful_outcomes for event in events)
    rate_limited = sum(
        event.outcome == "rate_limited" or event.http_status == 429
        for event in events
    )
    with conn:
        if events:
            conn.executemany(
                """INSERT INTO external_request_events
                   (run_id, job_id, provider, operation, resource_key, outcome,
                    http_status, duration_ms, error_type, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        event.job_id,
                        event.provider,
                        event.operation,
                        event.resource_key,
                        event.outcome,
                        event.http_status,
                        event.duration_ms,
                        event.error_type,
                        event.started_at,
                    )
                    for event in events
                ],
            )
        conn.execute(
            """UPDATE sync_job_runs
               SET finished_at = ?, status = ?, duration_ms = ?, reason = ?,
                   external_request_count = ?, external_failure_count = ?,
                   rate_limited_count = ?
               WHERE id = ? AND job_id = ?""",
            (
                finished_at,
                status,
                max(0, int(duration_ms)),
                _limited(reason, 1000),
                len(events),
                failures,
                rate_limited,
                run_id,
                job_id,
            ),
        )


def prune_observability_history(
    conn,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Delete old run rows; request events are removed by ON DELETE CASCADE."""
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = (current.astimezone(timezone.utc) - timedelta(days=retention_days)).isoformat(
        timespec="seconds"
    )
    with conn:
        cursor = conn.execute(
            "DELETE FROM sync_job_runs WHERE started_at < ?",
            (cutoff,),
        )
    return max(0, int(cursor.rowcount))
