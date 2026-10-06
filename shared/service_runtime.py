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

    same_release = scheduler.get("release_version") == api_identity.release_version
    same_commit = scheduler.get("git_commit") == api_identity.git_commit
    clean = not api_identity.tracked_dirty and not bool(scheduler.get("tracked_dirty"))
    consistent = scheduler_healthy and same_release and same_commit and clean
    healthy = scheduler_healthy

    return {
        "status": "ok" if healthy and consistent else "degraded",
        "release_version": api_identity.release_version,
        "healthy": healthy,
        "consistent": consistent,
        "checked_at": current.isoformat(timespec="seconds"),
        "components": {"api": api, "scheduler": scheduler},
    }
