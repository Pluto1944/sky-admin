"""服务运行身份持久化与聚合。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Mapping

from shared.runtime_identity import RuntimeIdentity


DEFAULT_STALE_AFTER_SECONDS = 15 * 60


def utc_now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def record_service_runtime(
    conn: sqlite3.Connection,
    identity: RuntimeIdentity,
    *,
    heartbeat_at: str | None = None,
) -> None:
    """写入启动身份；同一组件重启时替换旧身份。"""
    heartbeat = heartbeat_at or utc_now_iso()
    conn.execute(
        """INSERT INTO service_runtime
           (component, release_version, git_commit, git_describe,
            tracked_dirty, started_at, heartbeat_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(component) DO UPDATE SET
             release_version = excluded.release_version,
             git_commit = excluded.git_commit,
             git_describe = excluded.git_describe,
             tracked_dirty = excluded.tracked_dirty,
             started_at = excluded.started_at,
             heartbeat_at = excluded.heartbeat_at""",
        (
            identity.component,
            identity.release_version,
            identity.git_commit,
            identity.git_describe,
            int(identity.tracked_dirty),
            identity.started_at,
            heartbeat,
        ),
    )
    conn.commit()


def touch_service_runtime(
    conn: sqlite3.Connection,
    component: str,
    *,
    heartbeat_at: str | None = None,
) -> None:
    conn.execute(
        "UPDATE service_runtime SET heartbeat_at = ? WHERE component = ?",
        (heartbeat_at or utc_now_iso(), component),
    )
    conn.commit()


def get_service_runtime(conn: sqlite3.Connection, component: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM service_runtime WHERE component = ?", (component,)
    ).fetchone()
    if row is None:
        return None
    value = dict(row)
    value["tracked_dirty"] = bool(value.get("tracked_dirty"))
    return value


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_system_version(
    api_identity: RuntimeIdentity,
    scheduler_runtime: Mapping | None,
    *,
    worker_runtime: Mapping | None = None,
    worker_required: bool = False,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> dict:
    """合并 API 进程身份与调度器心跳，生成统一运行状态。"""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    api = api_identity.as_dict()
    api["health"] = "healthy"

    scheduler = dict(scheduler_runtime) if scheduler_runtime else None
    scheduler_healthy = False
    if scheduler is not None:
        scheduler["tracked_dirty"] = bool(scheduler.get("tracked_dirty"))
        heartbeat = _parse_utc(scheduler.get("heartbeat_at"))
        age = max(0, int((current - heartbeat).total_seconds())) if heartbeat else None
        scheduler["heartbeat_age_seconds"] = age
        scheduler_healthy = age is not None and age <= stale_after_seconds
        scheduler["health"] = "healthy" if scheduler_healthy else "stale"
    else:
        scheduler = {
            "component": "scheduler",
            "health": "missing",
            "heartbeat_age_seconds": None,
        }

    worker = dict(worker_runtime) if worker_runtime else None
    worker_healthy = False
    if worker is not None:
        worker["tracked_dirty"] = bool(worker.get("tracked_dirty"))
        heartbeat = _parse_utc(worker.get("heartbeat_at"))
        age = max(0, int((current - heartbeat).total_seconds())) if heartbeat else None
        worker["heartbeat_age_seconds"] = age
        worker_healthy = age is not None and age <= stale_after_seconds
        worker["health"] = "healthy" if worker_healthy else "stale"
    else:
        worker = {
            "component": "sync_worker",
            "health": "missing",
            "heartbeat_age_seconds": None,
        }

    checked = [scheduler]
    if worker_required:
        checked.append(worker)
    same_release = all(
        component.get("release_version") == api_identity.release_version
        for component in checked
    )
    same_commit = all(
        component.get("git_commit") == api_identity.git_commit
        for component in checked
    )
    clean = not api_identity.tracked_dirty and all(
        not bool(component.get("tracked_dirty")) for component in checked
    )
    required_healthy = scheduler_healthy and (worker_healthy if worker_required else True)
    consistent = required_healthy and same_release and same_commit and clean
    healthy = required_healthy

    return {
        "status": "ok" if healthy and consistent else "degraded",
        "release_version": api_identity.release_version,
        "healthy": healthy,
        "consistent": consistent,
        "worker_required": bool(worker_required),
        "checked_at": current.isoformat(timespec="seconds"),
        "components": {"api": api, "scheduler": scheduler, "sync_worker": worker},
    }
