"""Persistent synchronization interests, targets, tasks and leases.

M4.0 uses this repository in shadow mode only.  The live-task methods are
implemented and tested now so a later worker can be introduced without
changing queue semantics while it is already holding production tasks.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence


PRIORITY_RANK = {
    "backfill": 100,
    "scheduled": 200,
    "interactive": 300,
    "realtime": 400,
}
VALID_MODES = {"shadow", "live"}


class SyncQueueError(RuntimeError):
    """Queue state or ownership does not allow the requested operation."""


def _as_utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _as_utc(value).isoformat(timespec="seconds")


def _json(value: object | None) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _limited(value: object | None, limit: int = 1000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _duration_ms(started_at: object, finished_at: datetime) -> int | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = _as_utc(finished_at) - started.astimezone(timezone.utc)
    return max(0, round(elapsed.total_seconds() * 1000))


def _validate_priority(priority: str) -> str:
    if priority not in PRIORITY_RANK:
        raise ValueError(f"unknown sync priority: {priority}")
    return priority


def _begin_immediate(conn: sqlite3.Connection) -> None:
    # Queue claims use a short single-writer critical section.  Callers must
    # not carry an unrelated transaction into a lease operation.
    if conn.in_transaction:
        raise SyncQueueError("queue lease operation requires a clean transaction boundary")
    conn.execute("BEGIN IMMEDIATE")


class SyncQueueRepository:
    """SQLite-backed synchronization queue with global resource dedupe."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_interest(
        self,
        *,
        source_type: str,
        source_key: str,
        resource_type: str,
        resource_key: str,
        priority: str,
        desired_interval_seconds: int,
        alliance_id: int | None = None,
        expires_at: str | None = None,
        metadata: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Create or refresh one independently managed synchronization interest."""
        selected_priority = _validate_priority(str(priority))
        interval = int(desired_interval_seconds)
        if interval <= 0:
            raise ValueError("desired_interval_seconds must be positive")
        keys = tuple(str(value or "").strip() for value in (
            source_type, source_key, resource_type, resource_key,
        ))
        if any(not value for value in keys):
            raise ValueError("sync interest keys must not be empty")
        timestamp = _iso(now)
        with self.conn:
            self.conn.execute(
                """INSERT INTO sync_interests
                   (source_type, source_key, alliance_id, resource_type, resource_key,
                    priority, desired_interval_seconds, status, expires_at,
                    metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                   ON CONFLICT(source_type, source_key, resource_type, resource_key)
                   DO UPDATE SET alliance_id=excluded.alliance_id,
                       priority=excluded.priority,
                       desired_interval_seconds=excluded.desired_interval_seconds,
                       status='active', expires_at=excluded.expires_at,
                       metadata_json=excluded.metadata_json,
                       updated_at=excluded.updated_at""",
                (
                    keys[0], keys[1], alliance_id, keys[2], keys[3],
                    selected_priority, interval, expires_at, _json(metadata),
                    timestamp, timestamp,
                ),
            )
        row = self.conn.execute(
            """SELECT * FROM sync_interests
               WHERE source_type=? AND source_key=?
                 AND resource_type=? AND resource_key=?""",
            keys,
        ).fetchone()
        return dict(row)

    def reconcile_interests(
        self,
        interests: Iterable[Mapping[str, object]],
        *,
        managed_source_types: Sequence[str],
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Upsert one planner's complete interest set and deactivate stale rows."""
        source_types = tuple(dict.fromkeys(str(item) for item in managed_source_types))
        if not source_types:
            raise ValueError("managed_source_types must not be empty")
        timestamp = _iso(now)
        placeholders = ",".join("?" for _ in source_types)
        existing_rows = self.conn.execute(
            f"""SELECT * FROM sync_interests
                WHERE source_type IN ({placeholders})""",
            source_types,
        ).fetchall()
        existing = {
            (row["source_type"], row["source_key"], row["resource_type"], row["resource_key"]): row
            for row in existing_rows
        }
        desired: dict[tuple[str, str, str, str], dict[str, object]] = {}
        for raw in interests:
            source_type = str(raw["source_type"]).strip()
            source_key = str(raw["source_key"]).strip()
            resource_type = str(raw["resource_type"]).strip()
            resource_key = str(raw["resource_key"]).strip()
            if source_type not in source_types:
                raise ValueError(f"unmanaged source_type: {source_type}")
            if not source_key or not resource_type or not resource_key:
                raise ValueError("sync interest keys must not be empty")
            priority = _validate_priority(str(raw["priority"]))
            interval = int(raw["desired_interval_seconds"])
            if interval <= 0:
                raise ValueError("desired_interval_seconds must be positive")
            key = (source_type, source_key, resource_type, resource_key)
            desired[key] = {
                "alliance_id": raw.get("alliance_id"),
                "priority": priority,
                "desired_interval_seconds": interval,
                "expires_at": raw.get("expires_at"),
                "metadata_json": _json(raw.get("metadata")),
            }

        inserted = updated = deactivated = unchanged = 0
        with self.conn:
            for key, item in desired.items():
                row = existing.get(key)
                values = (
                    item["alliance_id"], item["priority"], item["desired_interval_seconds"],
                    item["expires_at"], item["metadata_json"],
                )
                if row is None:
                    self.conn.execute(
                        """INSERT INTO sync_interests
                           (source_type, source_key, alliance_id, resource_type, resource_key,
                            priority, desired_interval_seconds, status, expires_at,
                            metadata_json, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                        (*key[:2], values[0], *key[2:], *values[1:], timestamp, timestamp),
                    )
                    inserted += 1
                    continue
                current = (
                    row["alliance_id"], row["priority"], row["desired_interval_seconds"],
                    row["expires_at"], row["metadata_json"],
                )
                if current == values and row["status"] == "active":
                    unchanged += 1
                    continue
                self.conn.execute(
                    """UPDATE sync_interests
                       SET alliance_id = ?, priority = ?, desired_interval_seconds = ?,
                           status = 'active', expires_at = ?, metadata_json = ?, updated_at = ?
                       WHERE id = ?""",
                    (*values, timestamp, row["id"]),
                )
                updated += 1

            stale = set(existing) - set(desired)
            for key in stale:
                row = existing[key]
                if row["status"] == "inactive":
                    unchanged += 1
                    continue
                self.conn.execute(
                    "UPDATE sync_interests SET status = 'inactive', updated_at = ? WHERE id = ?",
                    (timestamp, row["id"]),
                )
                deactivated += 1
        return {
            "inserted": inserted,
            "updated": updated,
            "deactivated": deactivated,
            "unchanged": unchanged,
            "active": len(desired),
        }

    def rebuild_targets(self, *, now: datetime | None = None) -> dict[str, int]:
        """Aggregate active interests into one target per public resource."""
        current = _as_utc(now)
        timestamp = _iso(current)
        rows = self.conn.execute(
            """SELECT * FROM sync_interests
               WHERE status = 'active' AND (expires_at IS NULL OR expires_at > ?)""",
            (timestamp,),
        ).fetchall()
        grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault((row["resource_type"], row["resource_key"]), []).append(row)

        existing = {
            (row["resource_type"], row["resource_key"]): row
            for row in self.conn.execute("SELECT * FROM sync_targets").fetchall()
        }
        inserted = updated = deactivated = unchanged = 0
        with self.conn:
            for key, interests in grouped.items():
                priority = max(interests, key=lambda row: PRIORITY_RANK[row["priority"]])["priority"]
                interval = min(int(row["desired_interval_seconds"]) for row in interests)
                alliance_ids = sorted({
                    int(row["alliance_id"])
                    for row in interests
                    if row["alliance_id"] is not None
                })
                metadata = _json({
                    "interest_ids": sorted(int(row["id"]) for row in interests),
                    "source_types": sorted({row["source_type"] for row in interests}),
                })
                row = existing.get(key)
                policy = (
                    priority, PRIORITY_RANK[priority], interval, len(interests),
                    len(alliance_ids), metadata,
                )
                if row is None:
                    self.conn.execute(
                        """INSERT INTO sync_targets
                           (resource_type, resource_key, priority, priority_rank,
                            desired_interval_seconds, interest_count, alliance_count,
                            status, metadata_json, next_due_at, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                        (*key, *policy[:5], metadata, timestamp, timestamp, timestamp),
                    )
                    inserted += 1
                    continue
                current_policy = (
                    row["priority"], row["priority_rank"], row["desired_interval_seconds"],
                    row["interest_count"], row["alliance_count"], row["metadata_json"],
                )
                if current_policy == policy and row["status"] == "active":
                    unchanged += 1
                    continue
                accelerate = (
                    row["status"] != "active"
                    or PRIORITY_RANK[priority] > int(row["priority_rank"])
                    or interval < int(row["desired_interval_seconds"])
                )
                self.conn.execute(
                    """UPDATE sync_targets
                       SET priority = ?, priority_rank = ?, desired_interval_seconds = ?,
                           interest_count = ?, alliance_count = ?, status = 'active',
                           metadata_json = ?, next_due_at = CASE WHEN ? THEN ? ELSE next_due_at END,
                           updated_at = ?
                       WHERE id = ?""",
                    (*policy, int(accelerate), timestamp, timestamp, row["id"]),
                )
                updated += 1

            stale = set(existing) - set(grouped)
            for key in stale:
                row = existing[key]
                if row["status"] == "inactive":
                    unchanged += 1
                    continue
                self.conn.execute(
                    """UPDATE sync_targets
                       SET status = 'inactive', next_due_at = NULL, updated_at = ?
                       WHERE id = ?""",
                    (timestamp, row["id"]),
                )
                self.conn.execute(
                    """UPDATE sync_tasks
                       SET status = 'cancelled', finished_at = ?, updated_at = ?,
                           last_error = '同步目标已失效'
                       WHERE target_id = ? AND mode = 'live'
                         AND status IN ('pending', 'retry_wait')""",
                    (timestamp, timestamp, row["id"]),
                )
                deactivated += 1
        return {
            "inserted": inserted,
            "updated": updated,
            "deactivated": deactivated,
            "unchanged": unchanged,
            "active": len(grouped),
        }

    def plan_due_tasks(
        self,
        *,
        mode: str = "shadow",
        now: datetime | None = None,
        limit: int = 1000,
        max_attempts: int = 3,
        resource_types: Sequence[str] | None = None,
    ) -> list[dict]:
        """Create at most one task per due target and advance its schedule."""
        if mode not in VALID_MODES:
            raise ValueError(f"unknown task mode: {mode}")
        if limit <= 0 or max_attempts <= 0:
            raise ValueError("limit and max_attempts must be positive")
        current = _as_utc(now)
        timestamp = _iso(current)
        selected_types = tuple(dict.fromkeys(str(item).strip() for item in (resource_types or ())))
        filters = [
            "status = 'active'",
            "planning_mode = ?",
            "(next_due_at IS NULL OR next_due_at <= ?)",
        ]
        params: list[object] = [mode, timestamp]
        if selected_types:
            placeholders = ",".join("?" for _ in selected_types)
            filters.append(f"resource_type IN ({placeholders})")
            params.extend(selected_types)
        rows = self.conn.execute(
            f"""SELECT * FROM sync_targets
                WHERE {' AND '.join(filters)}
                ORDER BY priority_rank DESC, COALESCE(next_due_at, ''), id
                LIMIT ?""",
            (*params, int(limit)),
        ).fetchall()
        created: list[dict] = []
        task_status = "shadowed" if mode == "shadow" else "pending"
        with self.conn:
            for row in rows:
                slot = row["next_due_at"] or timestamp
                idempotency_key = (
                    f"{mode}:{row['resource_type']}:{row['resource_key']}:{slot}"
                )
                payload = {
                    "target_id": int(row["id"]),
                    "target_metadata": json.loads(row["metadata_json"] or "{}"),
                }
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO sync_tasks
                       (target_id, task_type, resource_type, resource_key, priority,
                        priority_rank, mode, status, idempotency_key, due_at,
                        available_at, max_attempts, payload_json, result_json,
                        created_at, updated_at, finished_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"], row["resource_type"], row["resource_type"],
                        row["resource_key"], row["priority"], row["priority_rank"],
                        mode, task_status, idempotency_key, timestamp, timestamp,
                        max_attempts, _json(payload),
                        _json({"shadow": True}) if mode == "shadow" else None,
                        timestamp, timestamp, timestamp if mode == "shadow" else None,
                    ),
                )
                next_due = _iso(current + timedelta(seconds=int(row["desired_interval_seconds"])))
                self.conn.execute(
                    """UPDATE sync_targets
                       SET last_planned_at = ?, next_due_at = ?, updated_at = ?
                       WHERE id = ?""",
                    (timestamp, next_due, timestamp, row["id"]),
                )
                if cursor.rowcount:
                    task = self.conn.execute(
                        "SELECT * FROM sync_tasks WHERE id = ?", (cursor.lastrowid,)
                    ).fetchone()
                    created.append(dict(task))
        return created

    def enqueue_interactive_task(
        self,
        resource_type: str,
        resource_key: str,
        *,
        cooldown_seconds: int,
        now: datetime | None = None,
        max_attempts: int = 3,
        payload: Mapping[str, object] | None = None,
    ) -> dict:
        """Queue one user-triggered live task with global dedupe and cooldown.

        The cooldown is resource-scoped rather than user-scoped, so multiple
        alliances subscribing to the same clan cannot multiply official API
        traffic.  Existing open work always wins.  A realtime target keeps its
        higher priority; a low-tier scheduled target is temporarily promoted
        only for this one task.
        """
        if cooldown_seconds <= 0 or max_attempts <= 0:
            raise ValueError("cooldown_seconds and max_attempts must be positive")
        current = _as_utc(now)
        timestamp = _iso(current)
        cutoff = _iso(current - timedelta(seconds=cooldown_seconds))
        _begin_immediate(self.conn)
        try:
            target = self.conn.execute(
                """SELECT * FROM sync_targets
                   WHERE resource_type = ? AND resource_key = ? AND status = 'active'""",
                (str(resource_type), str(resource_key)),
            ).fetchone()
            if target is None:
                raise SyncQueueError("同步目标尚未建立")
            if target["planning_mode"] != "live":
                raise SyncQueueError("同步目标尚未进入 live 模式")

            open_task = self.conn.execute(
                """SELECT * FROM sync_tasks
                   WHERE target_id = ? AND mode = 'live'
                     AND status IN ('pending', 'running', 'retry_wait')
                   ORDER BY id DESC LIMIT 1""",
                (target["id"],),
            ).fetchone()
            if open_task is not None:
                self.conn.commit()
                return {"accepted": False, "reason": "deduplicated", "task": dict(open_task)}

            recent = self.conn.execute(
                """SELECT * FROM sync_tasks
                   WHERE target_id = ? AND mode = 'live' AND created_at > ?
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (target["id"], cutoff),
            ).fetchone()
            if recent is not None:
                self.conn.commit()
                return {"accepted": False, "reason": "cooldown", "task": dict(recent)}

            priority = (
                target["priority"]
                if int(target["priority_rank"]) >= PRIORITY_RANK["interactive"]
                else "interactive"
            )
            priority_rank = PRIORITY_RANK[priority]
            bucket = int(current.timestamp()) // cooldown_seconds
            idempotency_key = (
                f"live:interactive:{resource_type}:{resource_key}:{bucket}"
            )
            task_payload = {
                "target_id": int(target["id"]),
                "target_metadata": json.loads(target["metadata_json"] or "{}"),
                "trigger": "interactive",
                **dict(payload or {}),
            }
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO sync_tasks
                   (target_id, task_type, resource_type, resource_key, priority,
                    priority_rank, mode, status, idempotency_key, due_at,
                    available_at, max_attempts, payload_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'live', 'pending', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    target["id"], resource_type, resource_type, resource_key,
                    priority, priority_rank, idempotency_key, timestamp, timestamp,
                    max_attempts, _json(task_payload), timestamp, timestamp,
                ),
            )
            row = self.conn.execute(
                "SELECT * FROM sync_tasks WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            next_due = _iso(
                current + timedelta(seconds=int(target["desired_interval_seconds"]))
            )
            self.conn.execute(
                """UPDATE sync_targets
                   SET last_planned_at = ?, next_due_at = ?, updated_at = ?
                   WHERE id = ?""",
                (timestamp, next_due, timestamp, target["id"]),
            )
            self.conn.commit()
            return {
                "accepted": bool(cursor.rowcount),
                "reason": "queued" if cursor.rowcount else "deduplicated",
                "task": dict(row),
            }
        except Exception:
            self.conn.rollback()
            raise

    def set_target_modes(
        self,
        live_resource_types: Sequence[str],
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Apply the cut-over set and make every mode transition immediately due.

        Pending live work is cancelled on rollback.  A task already running may
        finish under its lease; legacy writers are only re-enabled after the
        same configuration change and process restart, so no new duplicate is
        introduced by this transaction.
        """
        live_types = {
            str(item).strip() for item in live_resource_types if str(item).strip()
        }
        timestamp = _iso(now)
        changed_to_live = changed_to_shadow = unchanged = 0
        with self.conn:
            rows = self.conn.execute(
                "SELECT id, resource_type, planning_mode FROM sync_targets"
            ).fetchall()
            for row in rows:
                desired = "live" if row["resource_type"] in live_types else "shadow"
                if row["planning_mode"] == desired:
                    unchanged += 1
                    continue
                self.conn.execute(
                    """UPDATE sync_targets
                       SET planning_mode = ?, next_due_at = NULL, updated_at = ?
                       WHERE id = ?""",
                    (desired, timestamp, row["id"]),
                )
                if desired == "live":
                    changed_to_live += 1
                else:
                    changed_to_shadow += 1
                    self.conn.execute(
                        """UPDATE sync_tasks
                           SET status = 'cancelled', finished_at = ?, updated_at = ?,
                               last_error = '资源类型已回滚到旧调度路径'
                           WHERE target_id = ? AND mode = 'live'
                             AND status IN ('pending', 'retry_wait')""",
                        (timestamp, timestamp, row["id"]),
                    )
        return {
            "live": changed_to_live,
            "shadow": changed_to_shadow,
            "unchanged": unchanged,
        }

    def prune_shadow_tasks(
        self,
        *,
        retention_days: int = 7,
        now: datetime | None = None,
    ) -> int:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        cutoff = _iso(_as_utc(now) - timedelta(days=retention_days))
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM sync_tasks WHERE mode = 'shadow' AND created_at < ?",
                (cutoff,),
            )
        return max(0, int(cursor.rowcount))

    def _recover_expired_leases_locked(self, timestamp: str) -> int:
        rows = self.conn.execute(
            """SELECT * FROM sync_tasks
               WHERE mode = 'live' AND status = 'running'
                 AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
            (timestamp,),
        ).fetchall()
        for row in rows:
            exhausted = int(row["attempt_count"]) >= int(row["max_attempts"])
            status = "dead" if exhausted else "retry_wait"
            self.conn.execute(
                """UPDATE sync_tasks
                   SET status = ?, available_at = ?, lease_owner = NULL,
                       lease_expires_at = NULL, last_error = 'Worker 租约过期',
                       updated_at = ?, finished_at = CASE WHEN ? THEN ? ELSE NULL END
                   WHERE id = ? AND status = 'running'""",
                (status, timestamp, timestamp, int(exhausted), timestamp, row["id"]),
            )
            self.conn.execute(
                """UPDATE sync_attempts
                   SET status = 'interrupted', finished_at = ?, error_type = 'LeaseExpired',
                       error_message = 'Worker 租约过期'
                   WHERE task_id = ? AND attempt_no = ? AND status = 'running'""",
                (timestamp, row["id"], row["attempt_count"]),
            )
        return len(rows)

    def recover_expired_leases(self, *, now: datetime | None = None) -> int:
        timestamp = _iso(now)
        _begin_immediate(self.conn)
        try:
            recovered = self._recover_expired_leases_locked(timestamp)
            self.conn.commit()
            return recovered
        except Exception:
            self.conn.rollback()
            raise

    def interrupt_running_tasks(
        self,
        *,
        reason: str = "Worker 进程重启",
        now: datetime | None = None,
    ) -> int:
        """Release all leases owned by the previous singleton worker process."""
        timestamp = _iso(now)
        message = _limited(reason) or "Worker 进程重启"
        _begin_immediate(self.conn)
        try:
            rows = self.conn.execute(
                "SELECT * FROM sync_tasks WHERE mode = 'live' AND status = 'running'"
            ).fetchall()
            for row in rows:
                exhausted = int(row["attempt_count"]) >= int(row["max_attempts"])
                status = "dead" if exhausted else "retry_wait"
                self.conn.execute(
                    """UPDATE sync_tasks
                       SET status = ?, available_at = ?, lease_owner = NULL,
                           lease_expires_at = NULL, last_error = ?, updated_at = ?,
                           finished_at = CASE WHEN ? THEN ? ELSE NULL END
                       WHERE id = ? AND status = 'running'""",
                    (
                        status, timestamp, message, timestamp,
                        int(exhausted), timestamp, row["id"],
                    ),
                )
                self.conn.execute(
                    """UPDATE sync_attempts
                       SET status = 'interrupted', finished_at = ?,
                           error_type = 'WorkerRestarted', error_message = ?
                       WHERE task_id = ? AND attempt_no = ? AND status = 'running'""",
                    (timestamp, message, row["id"], row["attempt_count"]),
                )
            self.conn.commit()
            return len(rows)
        except Exception:
            self.conn.rollback()
            raise

    def claim_tasks(
        self,
        worker_id: str,
        *,
        limit: int = 1,
        lease_seconds: int = 120,
        priorities: Sequence[str] | None = None,
        resource_types: Sequence[str] | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """Atomically claim a bounded live-task batch for one worker."""
        worker = worker_id.strip()
        if not worker:
            raise ValueError("worker_id must not be empty")
        if limit <= 0 or lease_seconds <= 0:
            raise ValueError("limit and lease_seconds must be positive")
        selected_priorities = tuple(priorities or PRIORITY_RANK.keys())
        for priority in selected_priorities:
            _validate_priority(priority)
        current = _as_utc(now)
        timestamp = _iso(current)
        lease_expires = _iso(current + timedelta(seconds=lease_seconds))
        placeholders = ",".join("?" for _ in selected_priorities)
        selected_types = tuple(dict.fromkeys(str(item).strip() for item in (resource_types or ())))
        type_filter = ""
        type_params: tuple[object, ...] = ()
        if selected_types:
            type_placeholders = ",".join("?" for _ in selected_types)
            type_filter = f" AND resource_type IN ({type_placeholders})"
            type_params = selected_types
        _begin_immediate(self.conn)
        try:
            self._recover_expired_leases_locked(timestamp)
            rows = self.conn.execute(
                f"""SELECT * FROM sync_tasks
                    WHERE mode = 'live' AND status IN ('pending', 'retry_wait')
                      AND available_at <= ? AND due_at <= ?
                      AND priority IN ({placeholders}){type_filter}
                    ORDER BY priority_rank DESC, due_at, id
                    LIMIT ?""",
                (timestamp, timestamp, *selected_priorities, *type_params, int(limit)),
            ).fetchall()
            claimed: list[dict] = []
            for row in rows:
                attempt_no = int(row["attempt_count"]) + 1
                cursor = self.conn.execute(
                    """UPDATE sync_tasks
                       SET status = 'running', attempt_count = ?, lease_owner = ?,
                           lease_expires_at = ?, started_at = COALESCE(started_at, ?),
                           updated_at = ?
                       WHERE id = ? AND status IN ('pending', 'retry_wait')""",
                    (attempt_no, worker, lease_expires, timestamp, timestamp, row["id"]),
                )
                if cursor.rowcount != 1:
                    continue
                self.conn.execute(
                    """INSERT INTO sync_attempts
                       (task_id, attempt_no, worker_id, status, started_at)
                       VALUES (?, ?, ?, 'running', ?)""",
                    (row["id"], attempt_no, worker, timestamp),
                )
                claimed_row = self.conn.execute(
                    "SELECT * FROM sync_tasks WHERE id = ?", (row["id"],)
                ).fetchone()
                claimed.append(dict(claimed_row))
            self.conn.commit()
            return claimed
        except Exception:
            self.conn.rollback()
            raise

    def heartbeat(
        self,
        task_id: int,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> str:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = _as_utc(now)
        timestamp = _iso(current)
        expires = _iso(current + timedelta(seconds=lease_seconds))
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE sync_tasks SET lease_expires_at = ?, updated_at = ?
                   WHERE id = ? AND mode = 'live' AND status = 'running'
                     AND lease_owner = ?""",
                (expires, timestamp, int(task_id), worker_id),
            )
        if cursor.rowcount != 1:
            raise SyncQueueError("task is not leased by this worker")
        return expires

    def complete_task(
        self,
        task_id: int,
        worker_id: str,
        *,
        result: object | None = None,
        external_request_count: int = 0,
        now: datetime | None = None,
    ) -> None:
        if external_request_count < 0:
            raise ValueError("external_request_count must not be negative")
        current = _as_utc(now)
        timestamp = _iso(current)
        _begin_immediate(self.conn)
        try:
            row = self.conn.execute(
                "SELECT * FROM sync_tasks WHERE id = ?", (int(task_id),)
            ).fetchone()
            if row is None or row["status"] != "running" or row["lease_owner"] != worker_id:
                raise SyncQueueError("task is not leased by this worker")
            attempt = self.conn.execute(
                """SELECT started_at FROM sync_attempts
                   WHERE task_id = ? AND attempt_no = ? AND status = 'running'""",
                (row["id"], row["attempt_count"]),
            ).fetchone()
            duration_ms = _duration_ms(attempt["started_at"], current) if attempt else None
            result_json = _json(result)
            self.conn.execute(
                """UPDATE sync_tasks
                   SET status = 'succeeded', lease_owner = NULL, lease_expires_at = NULL,
                       result_json = ?, last_error = NULL, updated_at = ?, finished_at = ?
                   WHERE id = ?""",
                (result_json, timestamp, timestamp, row["id"]),
            )
            self.conn.execute(
                """UPDATE sync_attempts
                   SET status = 'succeeded', finished_at = ?, external_request_count = ?,
                       duration_ms = ?, result_json = ?
                   WHERE task_id = ? AND attempt_no = ? AND status = 'running'""",
                (
                    timestamp, external_request_count, duration_ms, result_json,
                    row["id"], row["attempt_count"],
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def fail_task(
        self,
        task_id: int,
        worker_id: str,
        *,
        error: object,
        error_type: str | None = None,
        retryable: bool = True,
        base_backoff_seconds: int = 60,
        max_backoff_seconds: int = 3600,
        external_request_count: int = 0,
        now: datetime | None = None,
    ) -> str:
        """Finish an attempt and return the task's new status."""
        if base_backoff_seconds <= 0 or max_backoff_seconds <= 0:
            raise ValueError("backoff values must be positive")
        if external_request_count < 0:
            raise ValueError("external_request_count must not be negative")
        current = _as_utc(now)
        timestamp = _iso(current)
        _begin_immediate(self.conn)
        try:
            row = self.conn.execute(
                "SELECT * FROM sync_tasks WHERE id = ?", (int(task_id),)
            ).fetchone()
            if row is None or row["status"] != "running" or row["lease_owner"] != worker_id:
                raise SyncQueueError("task is not leased by this worker")
            attempt_count = int(row["attempt_count"])
            attempt = self.conn.execute(
                """SELECT started_at FROM sync_attempts
                   WHERE task_id = ? AND attempt_no = ? AND status = 'running'""",
                (row["id"], attempt_count),
            ).fetchone()
            duration_ms = _duration_ms(attempt["started_at"], current) if attempt else None
            can_retry = retryable and attempt_count < int(row["max_attempts"])
            if can_retry:
                new_status = "retry_wait"
                delay = min(
                    max_backoff_seconds,
                    base_backoff_seconds * (2 ** max(0, attempt_count - 1)),
                )
                available_at = _iso(current + timedelta(seconds=delay))
                finished_at = None
            else:
                new_status = "dead" if retryable else "failed"
                available_at = timestamp
                finished_at = timestamp
            message = _limited(error) or "unknown sync error"
            normalized_type = _limited(error_type, 120) or type(error).__name__
            self.conn.execute(
                """UPDATE sync_tasks
                   SET status = ?, available_at = ?, lease_owner = NULL,
                       lease_expires_at = NULL, last_error = ?, updated_at = ?, finished_at = ?
                   WHERE id = ?""",
                (new_status, available_at, message, timestamp, finished_at, row["id"]),
            )
            self.conn.execute(
                """UPDATE sync_attempts
                   SET status = 'failed', finished_at = ?, error_type = ?, error_message = ?,
                       external_request_count = ?, duration_ms = ?
                   WHERE task_id = ? AND attempt_no = ? AND status = 'running'""",
                (
                    timestamp, normalized_type, message, external_request_count, duration_ms,
                    row["id"], attempt_count,
                ),
            )
            self.conn.commit()
            return new_status
        except Exception:
            self.conn.rollback()
            raise

    def summary(self) -> dict:
        """Return sanitized queue counts for diagnostics."""
        targets = {
            row["status"]: int(row["count"])
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS count FROM sync_targets GROUP BY status"
            ).fetchall()
        }
        tasks = {
            f"{row['mode']}:{row['status']}": int(row["count"])
            for row in self.conn.execute(
                "SELECT mode, status, COUNT(*) AS count FROM sync_tasks GROUP BY mode, status"
            ).fetchall()
        }
        priorities = {
            row["priority"]: int(row["count"])
            for row in self.conn.execute(
                """SELECT priority, COUNT(*) AS count FROM sync_targets
                   WHERE status = 'active' GROUP BY priority"""
            ).fetchall()
        }
        return {"targets": targets, "tasks": tasks, "active_priorities": priorities}
