"""M5 free single-clan alliance lifecycle and asynchronous synchronization.

All mutations in this module are alliance-private.  Public COC facts remain
keyed by clan/player/war identifiers and synchronization is submitted through
the globally deduplicated M4 queue; no request handler calls an external API.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from modules.coc_sync.official.mapper import normalize_tag
from modules.sync_queue.config import active_live_resource_types
from modules.sync_queue.planner import SyncPlanner
from modules.sync_queue.repository import SyncQueueError, SyncQueueRepository

from .operations import free_registration_policy, platform_admin_capability


FREE_CATEGORIES = ("normal", "combat", "farm", "flat")
FREE_CATEGORY_LABELS = {
    "normal": "实战",
    "combat": "战营",
    "farm": "互刷",
    "flat": "偷矿",
}
INITIAL_RESOURCE_TYPES = ("clan_profile", "clan_members", "current_war")
_TAG_RE = re.compile(r"^#[0289PYLQGRJCUV]{3,14}$")


class FreeAllianceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat(timespec="seconds")


def _enabled() -> bool:
    raw = os.getenv(
        "ALLIANCE_FREE_ENABLED",
        os.getenv("M5_FREE_ALLIANCE_ENABLED", "false"),
    )
    return raw.strip().lower() in {
        "1", "true", "yes", "on",
    }


def _allowlist() -> set[str]:
    return {
        item.strip()
        for item in os.getenv("M5_FREE_ALLIANCE_OPENIDS", "").split(",")
        if item.strip()
    }


def free_alliance_capability(conn: sqlite3.Connection, openid: str) -> dict:
    """Return gray/public free registration capability without exposing allowlists."""
    user = conn.execute(
        "SELECT id FROM wechat_users WHERE openid = ?", (openid,),
    ).fetchone()
    existing = None
    active_existing = None
    if user is not None:
        existing = conn.execute(
            """SELECT id, name, status FROM alliances
               WHERE created_by_user_id = ? AND plan_code = 'free'
               ORDER BY id DESC LIMIT 1""",
            (user["id"],),
        ).fetchone()
        active_existing = conn.execute(
            """SELECT id FROM alliances
               WHERE created_by_user_id = ? AND plan_code = 'free' AND status = 'active'
               ORDER BY id DESC LIMIT 1""",
            (user["id"],),
        ).fetchone()
    enabled = _enabled()
    policy = free_registration_policy(conn)
    platform_admin = platform_admin_capability(conn, openid)["allowed"]
    internal_allowed = openid in _allowlist()
    public_allowed = policy["public_open"] and policy["has_capacity"]
    allowed = enabled and (platform_admin or internal_allowed or public_allowed or bool(
        active_existing is not None
    ))
    return {
        "enabled": enabled,
        "allowed": allowed,
        "mode": "platform" if platform_admin else (
            "internal" if internal_allowed else ("public" if policy["public_open"] else "closed")
        ),
        "unlimited": bool(platform_admin),
        "public_open": policy["public_open"],
        "registration_limit": policy["limit"],
        "registration_remaining": policy["remaining"],
        "can_create": bool(
            allowed and user is not None and (platform_admin or active_existing is None)
        ),
        "existing_alliance_id": int(existing["id"]) if existing else None,
        "existing_status": existing["status"] if existing else None,
    }


def _clean_name(value: str | None) -> str:
    name = (value or "我的部落").strip()
    if not name:
        name = "我的部落"
    if len(name) > 30:
        raise FreeAllianceError("联盟名称不能超过 30 个字符", status_code=422)
    return name


def _tag(value: str) -> str:
    normalized = normalize_tag(value.replace("O", "0").replace("o", "0"))
    if not normalized or not _TAG_RE.fullmatch(normalized):
        raise FreeAllianceError("请输入有效的部落标签", status_code=422)
    return normalized


def _category(value: str) -> str:
    result = str(value or "").strip()
    if result not in FREE_CATEGORIES:
        raise FreeAllianceError("部落标签仅支持实战、战营、互刷或偷矿", status_code=422)
    return result


def _audit(
    conn: sqlite3.Connection,
    *,
    alliance_id: int,
    actor_user_id: int,
    action: str,
    entity_type: str,
    entity_id: str | int | None,
    details: Mapping[str, object] | None,
    timestamp: str,
) -> None:
    conn.execute(
        """INSERT INTO alliance_audit_events
           (event_key, alliance_id, actor_user_id, action, entity_type,
            entity_id, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"m5-{action}-{uuid.uuid4().hex}", alliance_id, actor_user_id,
            action, entity_type, str(entity_id) if entity_id is not None else None,
            json.dumps(dict(details or {}), ensure_ascii=False, sort_keys=True), timestamp,
        ),
    )


def _free_member(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    leader_required: bool = False,
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT users.id AS user_id, alliances.id, alliances.name,
                  alliances.status, alliances.plan_code, members.role
           FROM wechat_users AS users
           JOIN alliance_members AS members
             ON members.user_id = users.id AND members.status = 'active'
           JOIN alliances ON alliances.id = members.alliance_id
           WHERE users.openid = ? AND alliances.id = ?""",
        (openid, int(alliance_id)),
    ).fetchone()
    if row is None:
        raise FreeAllianceError("联盟不存在或当前用户无权访问", status_code=404)
    if row["plan_code"] != "free":
        raise FreeAllianceError("该操作仅适用于免费联盟", status_code=409)
    if row["status"] != "active":
        raise FreeAllianceError("联盟已停用", status_code=409)
    if leader_required and row["role"] != "leader":
        raise FreeAllianceError("只有联盟首领可以执行此操作", status_code=403)
    return row


def _owner(conn: sqlite3.Connection, openid: str, alliance_id: int) -> sqlite3.Row:
    return _free_member(conn, openid, alliance_id, leader_required=True)


def create_free_alliance(
    conn: sqlite3.Connection,
    openid: str,
    *,
    name: str | None = None,
    now: datetime | None = None,
) -> int:
    capability = free_alliance_capability(conn, openid)
    if not capability["allowed"]:
        raise FreeAllianceError("免费联盟注册暂未开放或当前名额已满", status_code=403)
    if not capability["can_create"]:
        raise FreeAllianceError("每个用户只能创建一个有效的免费联盟", status_code=409)
    user = conn.execute(
        "SELECT id FROM wechat_users WHERE openid = ?", (openid,),
    ).fetchone()
    if user is None:
        raise FreeAllianceError("微信账号不存在，请重新登录", status_code=401)
    plan = conn.execute(
        "SELECT 1 FROM alliance_plans WHERE plan_code='free' AND status='active'",
    ).fetchone()
    if plan is None:
        raise FreeAllianceError("免费套餐尚未初始化", status_code=503)
    timestamp = _iso(now)
    display_name = _clean_name(name)
    with conn:
        cursor = conn.execute(
            """INSERT INTO alliances
               (alliance_key, name, status, plan_code, created_by_user_id,
                created_at, updated_at)
               VALUES (?, ?, 'active', 'free', ?, ?, ?)""",
            (f"free-{uuid.uuid4().hex}", display_name, user["id"], timestamp, timestamp),
        )
        alliance_id = int(cursor.lastrowid)
        conn.execute(
            """INSERT INTO alliance_members
               (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
               VALUES (?, ?, 'leader', 'active', ?, ?, ?)""",
            (alliance_id, user["id"], timestamp, timestamp, timestamp),
        )
        conn.execute(
            "UPDATE alliance_visits SET is_default=0 WHERE user_id=?",
            (user["id"],),
        )
        conn.execute(
            """INSERT INTO alliance_visits
               (alliance_id, user_id, is_default, first_visited_at, last_visited_at)
               VALUES (?, ?, 1, ?, ?)""",
            (alliance_id, user["id"], timestamp, timestamp),
        )
        _audit(
            conn, alliance_id=alliance_id, actor_user_id=int(user["id"]),
            action="free_alliance_created", entity_type="alliance",
            entity_id=alliance_id, details={"name": display_name}, timestamp=timestamp,
        )
    return alliance_id


def rename_free_alliance(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    name: str,
    *,
    now: datetime | None = None,
) -> None:
    owner = _owner(conn, openid, alliance_id)
    display_name = _clean_name(name)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliances SET name=?, updated_at=? WHERE id=?",
            (display_name, timestamp, alliance_id),
        )
        _audit(
            conn, alliance_id=alliance_id, actor_user_id=int(owner["user_id"]),
            action="free_alliance_renamed", entity_type="alliance",
            entity_id=alliance_id,
            details={"before": owner["name"], "after": display_name},
            timestamp=timestamp,
        )


def subscribe_free_clan(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    clan_tag: str,
    category: str,
    clan_name: str | None = None,
    now: datetime | None = None,
) -> dict:
    owner = _owner(conn, openid, alliance_id)
    tag = _tag(clan_tag)
    selected_category = _category(category)
    timestamp = _iso(now)
    existing = conn.execute(
        """SELECT * FROM alliance_clans
           WHERE alliance_id=? AND status='active' ORDER BY id LIMIT 1""",
        (alliance_id,),
    ).fetchone()
    if existing is not None and normalize_tag(existing["clan_tag"]) != tag:
        raise FreeAllianceError(
            "免费联盟暂不支持直接更换部落，请停用当前联盟后重新创建",
            status_code=409,
        )
    profile = conn.execute(
        "SELECT clan_name FROM clan_profile_cache WHERE clan_tag=?",
        (tag,),
    ).fetchone()
    display_name = (clan_name or "").strip() or (
        profile["clan_name"] if profile and profile["clan_name"] else tag
    )
    if len(display_name) > 40:
        raise FreeAllianceError("部落名称不能超过 40 个字符", status_code=422)

    with conn:
        if existing is None:
            previous = conn.execute(
                """SELECT clan_tag FROM alliance_clans
                   WHERE alliance_id=? ORDER BY id DESC LIMIT 1""",
                (alliance_id,),
            ).fetchone()
            if previous is not None and normalize_tag(previous["clan_tag"]) != tag:
                raise FreeAllianceError("免费联盟更换部落规则尚未开放", status_code=409)
            conn.execute(
                """INSERT INTO alliance_clans
                   (alliance_id, clan_tag, clan_name, category, sort_order, status,
                    verification_status, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 0, 'active', 'unverified', 'manual', ?, ?)
                   ON CONFLICT(alliance_id, clan_tag) DO UPDATE SET
                       clan_name=excluded.clan_name, category=excluded.category,
                       status='active', verification_status='unverified',
                       verified_by_user_id=NULL, verified_at=NULL,
                       updated_at=excluded.updated_at""",
                (alliance_id, tag, display_name, selected_category, timestamp, timestamp),
            )
            action = "free_clan_subscribed"
        else:
            conn.execute(
                """UPDATE alliance_clans
                   SET clan_name=?, category=?, updated_at=? WHERE id=?""",
                (display_name, selected_category, timestamp, existing["id"]),
            )
            action = "free_clan_updated"
        _audit(
            conn, alliance_id=alliance_id, actor_user_id=int(owner["user_id"]),
            action=action, entity_type="alliance_clan", entity_id=tag,
            details={
                "clan_tag": tag,
                "clan_name": display_name,
                "category": selected_category,
            },
            timestamp=timestamp,
        )
    return {
        "clan_tag": tag,
        "clan_name": display_name,
        "category": selected_category,
        "category_label": FREE_CATEGORY_LABELS[selected_category],
        "verification_status": "unverified",
    }


def archive_free_alliance(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    now: datetime | None = None,
) -> None:
    owner = _owner(conn, openid, alliance_id)
    timestamp = _iso(now)
    with conn:
        _audit(
            conn, alliance_id=alliance_id, actor_user_id=int(owner["user_id"]),
            action="free_alliance_archived", entity_type="alliance",
            entity_id=alliance_id, details={"name": owner["name"]}, timestamp=timestamp,
        )
        conn.execute(
            "UPDATE alliance_clans SET status='inactive', updated_at=? WHERE alliance_id=? AND status='active'",
            (timestamp, alliance_id),
        )
        conn.execute(
            "UPDATE alliance_members SET status='left', updated_at=? WHERE alliance_id=? AND status='active'",
            (timestamp, alliance_id),
        )
        conn.execute(
            "UPDATE alliance_visits SET is_default=0 WHERE alliance_id=?",
            (alliance_id,),
        )
        replacement = conn.execute(
            """SELECT visits.alliance_id
               FROM alliance_visits AS visits
               JOIN alliances ON alliances.id=visits.alliance_id AND alliances.status='active'
               JOIN alliance_members AS members
                 ON members.alliance_id=visits.alliance_id
                AND members.user_id=? AND members.status='active'
               WHERE visits.user_id=? AND visits.alliance_id != ?
               ORDER BY visits.last_visited_at DESC LIMIT 1""",
            (owner["user_id"], owner["user_id"], alliance_id),
        ).fetchone()
        if replacement is not None:
            conn.execute(
                "UPDATE alliance_visits SET is_default=1 WHERE user_id=? AND alliance_id=?",
                (owner["user_id"], replacement["alliance_id"]),
            )
        conn.execute(
            "UPDATE alliances SET status='archived', updated_at=? WHERE id=?",
            (timestamp, alliance_id),
        )


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _now(parsed)


def _cache_time(conn: sqlite3.Connection, resource_type: str, clan_tag: str) -> str | None:
    if resource_type == "clan_profile":
        row = conn.execute(
            "SELECT updated_at FROM clan_profile_cache WHERE clan_tag=? AND data_json IS NOT NULL",
            (clan_tag,),
        ).fetchone()
    elif resource_type == "clan_members":
        row = conn.execute(
            "SELECT MAX(last_synced_at) AS updated_at FROM accounts WHERE clan_tag=?",
            (clan_tag,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT updated_at FROM current_war_cache WHERE clan_tag=? AND data_json IS NOT NULL",
            (clan_tag,),
        ).fetchone()
    return row["updated_at"] if row and row["updated_at"] else None


def _active_live_types(conn: sqlite3.Connection) -> tuple[str, ...]:
    configured = set(active_live_resource_types())
    configured.update(
        row["resource_type"]
        for row in conn.execute(
            "SELECT DISTINCT resource_type FROM sync_targets WHERE planning_mode='live'"
        ).fetchall()
    )
    return tuple(
        item for item in ("clan_profile", "clan_members", "current_war", "cwl_live")
        if item in configured
    )


def reconcile_sync_targets(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    return SyncPlanner(conn).reconcile_targets(
        now=_now(now),
        live_resource_types=_active_live_types(conn),
    )


def _initial_cache_fresh(
    conn: sqlite3.Connection,
    resource_type: str,
    clan_tag: str,
    current: datetime,
) -> bool:
    updated = _parse_time(_cache_time(conn, resource_type, clan_tag))
    if updated is None:
        return False
    max_age = 10 * 60 if resource_type == "current_war" else 6 * 60 * 60
    return updated >= current - timedelta(seconds=max_age)


def _queue_response(value: Mapping[str, object]) -> dict:
    task = value.get("task")
    safe = {key: item for key, item in value.items() if key != "task"}
    if isinstance(task, Mapping):
        safe.update({
            "task_id": int(task["id"]) if task.get("id") is not None else None,
            "task_status": task.get("status"),
            "task_created_at": task.get("created_at"),
        })
    return safe


def enqueue_initialization(
    conn: sqlite3.Connection,
    *,
    alliance_id: int,
    clan_tag: str,
    actor_user_id: int,
    now: datetime | None = None,
) -> list[dict]:
    current = _now(now)
    reconcile_sync_targets(conn, now=current)
    queue = SyncQueueRepository(conn)
    results = []
    for resource_type in INITIAL_RESOURCE_TYPES:
        if _initial_cache_fresh(conn, resource_type, clan_tag, current):
            results.append({"resource_type": resource_type, "accepted": False, "reason": "cache_fresh"})
            continue
        try:
            queued = queue.enqueue_interactive_task(
                resource_type,
                clan_tag,
                cooldown_seconds=60,
                now=current,
                payload={"alliance_id": alliance_id, "actor_user_id": actor_user_id, "trigger": "initialization"},
            )
        except SyncQueueError as exc:
            queued = {"accepted": False, "reason": "planner_pending", "message": str(exc)}
        results.append({"resource_type": resource_type, **_queue_response(queued)})
    return results


def _war_cooldown(conn: sqlite3.Connection, clan_tag: str, current: datetime) -> int:
    row = conn.execute(
        "SELECT status, expected_end_at FROM current_war_cache WHERE clan_tag=?",
        (clan_tag,),
    ).fetchone()
    if row is None:
        return 2 * 60 * 60
    status = row["status"]
    if status == "preparation":
        return 30 * 60
    if status == "in_war":
        end = _parse_time(row["expected_end_at"])
        return 5 * 60 if end and end - current <= timedelta(hours=1) else 10 * 60
    return 2 * 60 * 60


def request_manual_refresh(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tag: str,
    *,
    resource_types: Iterable[str] = ("current_war",),
    now: datetime | None = None,
) -> list[dict]:
    member = _free_member(conn, openid, alliance_id)
    tag = _tag(clan_tag)
    subscribed = conn.execute(
        """SELECT 1 FROM alliance_clans
           WHERE alliance_id=? AND clan_tag=? AND status='active'""",
        (alliance_id, tag),
    ).fetchone()
    if subscribed is None:
        raise FreeAllianceError("部落不在当前联盟订阅范围内", status_code=404)
    selected = tuple(dict.fromkeys(str(item) for item in resource_types))
    if not selected or any(item not in INITIAL_RESOURCE_TYPES for item in selected):
        raise FreeAllianceError("不支持的刷新资源类型", status_code=422)
    current = _now(now)
    reconcile_sync_targets(conn, now=current)
    queue = SyncQueueRepository(conn)
    results = []
    for resource_type in selected:
        cooldown = (
            _war_cooldown(conn, tag, current)
            if resource_type == "current_war" else 2 * 60 * 60
        )
        try:
            queued = queue.enqueue_interactive_task(
                resource_type, tag, cooldown_seconds=cooldown, now=current,
                payload={"alliance_id": alliance_id, "actor_user_id": int(member["user_id"]), "trigger": "manual"},
            )
        except SyncQueueError as exc:
            queued = {"accepted": False, "reason": "planner_pending", "message": str(exc)}
        results.append({
            "resource_type": resource_type,
            "cooldown_seconds": cooldown,
            **_queue_response(queued),
        })
    timestamp = _iso(current)
    with conn:
        _audit(
            conn, alliance_id=alliance_id, actor_user_id=int(member["user_id"]),
            action="free_manual_refresh_requested", entity_type="alliance_clan",
            entity_id=tag,
            details={
                "resource_types": list(selected),
                "results": [
                    {"resource_type": item["resource_type"], "accepted": item["accepted"], "reason": item["reason"]}
                    for item in results
                ],
            },
            timestamp=timestamp,
        )
    return results


def subscription_status(
    conn: sqlite3.Connection,
    alliance_id: int,
    clan_tag: str,
) -> list[dict]:
    tag = _tag(clan_tag)
    result = []
    for resource_type in INITIAL_RESOURCE_TYPES:
        target = conn.execute(
            """SELECT id, planning_mode, priority, next_due_at
               FROM sync_targets WHERE resource_type=? AND resource_key=?""",
            (resource_type, tag),
        ).fetchone()
        task = None
        if target is not None:
            task = conn.execute(
                """SELECT id, status, created_at, updated_at, finished_at, last_error
                   FROM sync_tasks WHERE target_id=? AND mode='live'
                   ORDER BY id DESC LIMIT 1""",
                (target["id"],),
            ).fetchone()
        cache_updated_at = _cache_time(conn, resource_type, tag)
        task_status = task["status"] if task else None
        if task_status in {"pending", "running", "retry_wait"}:
            state = task_status
        elif cache_updated_at:
            state = "partial" if task_status in {"failed", "dead"} else "ready"
        elif task_status in {"failed", "dead"}:
            state = "failed"
        else:
            state = "pending"
        result.append({
            "resource_type": resource_type,
            "state": state,
            "cache_updated_at": cache_updated_at,
            "target_mode": target["planning_mode"] if target else None,
            "target_priority": target["priority"] if target else None,
            "next_due_at": target["next_due_at"] if target else None,
            "task_id": int(task["id"]) if task else None,
            "task_status": task_status,
            "task_updated_at": task["updated_at"] if task else None,
            "error": task["last_error"] if task_status in {"failed", "dead"} else None,
        })
    return result
