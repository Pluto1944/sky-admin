"""M6-M9 alliance membership, sharing, manual verification and plan operations.

The first production version deliberately does not implement self-service clan
verification.  A platform operator verifies a clan manually; the user-facing
button remains an informational entry point.  Public COC facts are never
deleted by lifecycle operations in this module.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
import re
from datetime import datetime, timedelta, timezone
from typing import Mapping

from modules.coc_sync.official.mapper import normalize_tag


_TAG_RE = re.compile(r"^#[0289PYLQGRJCUV]{3,14}$")
_CATEGORIES = {"normal", "combat", "farm", "flat"}


class AllianceOperationError(RuntimeError):
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


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _clan_tag(value: str) -> str:
    tag = normalize_tag(str(value or "").replace("O", "0").replace("o", "0"))
    if not tag or not _TAG_RE.fullmatch(tag):
        raise AllianceOperationError("请输入有效的部落标签", status_code=422)
    return tag


def _user(conn: sqlite3.Connection, openid: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM wechat_users WHERE openid=?", (openid,),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("微信账号不存在，请重新登录", status_code=401)
    return row


def _member(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    roles: set[str] | None = None,
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT users.id AS user_id, members.id AS member_id, members.role,
                  members.status AS member_status, alliances.name,
                  alliances.status AS alliance_status, alliances.plan_code
           FROM wechat_users AS users
           JOIN alliance_members AS members ON members.user_id=users.id
           JOIN alliances ON alliances.id=members.alliance_id
           WHERE users.openid=? AND alliances.id=?""",
        (openid, int(alliance_id)),
    ).fetchone()
    if row is None or row["member_status"] != "active" or row["alliance_status"] != "active":
        raise AllianceOperationError("联盟不存在或当前用户无权访问", status_code=404)
    if roles and row["role"] not in roles:
        raise AllianceOperationError("当前联盟角色没有此操作权限", status_code=403)
    return row


def _alliance_audit(
    conn: sqlite3.Connection,
    *,
    alliance_id: int,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: object = None,
    details: Mapping[str, object] | None = None,
    timestamp: str,
) -> None:
    conn.execute(
        """INSERT INTO alliance_audit_events
           (event_key, alliance_id, actor_user_id, action, entity_type,
            entity_id, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"ops-{action}-{uuid.uuid4().hex}", int(alliance_id), actor_user_id,
            action, entity_type, str(entity_id) if entity_id is not None else None,
            _json(dict(details or {})), timestamp,
        ),
    )


def _platform_audit(
    conn: sqlite3.Connection,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: object = None,
    details: Mapping[str, object] | None = None,
    timestamp: str,
) -> None:
    conn.execute(
        """INSERT INTO platform_audit_events
           (event_key, actor_user_id, action, entity_type, entity_id,
            details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            f"platform-{action}-{uuid.uuid4().hex}", actor_user_id, action,
            entity_type, str(entity_id) if entity_id is not None else None,
            _json(dict(details or {})), timestamp,
        ),
    )


def platform_admin_capability(conn: sqlite3.Connection, openid: str) -> dict:
    row = conn.execute(
        """SELECT users.id,
                  CASE WHEN admins.status='active' THEN 1 ELSE 0 END AS db_admin
           FROM wechat_users AS users
           LEFT JOIN platform_admins AS admins ON admins.user_id=users.id
           WHERE users.openid=?""",
        (openid,),
    ).fetchone()
    allowed = bool(row and row["db_admin"])
    return {"allowed": allowed}


def require_platform_admin(conn: sqlite3.Connection, openid: str) -> sqlite3.Row:
    user = _user(conn, openid)
    if not platform_admin_capability(conn, openid)["allowed"]:
        raise AllianceOperationError("仅平台管理员可以执行此操作", status_code=403)
    return user


def create_platform_alliance(
    conn: sqlite3.Connection,
    openid: str,
    name: str,
    *,
    now: datetime | None = None,
) -> dict:
    """在超级管理入口创建联盟；不受个人普通创建入口的一联盟限制。"""
    actor = require_platform_admin(conn, openid)
    display_name = str(name or "").strip()
    if not display_name:
        raise AllianceOperationError("联盟名称不能为空", status_code=422)
    if len(display_name) > 30:
        raise AllianceOperationError("联盟名称不能超过 30 个字符", status_code=422)
    if conn.execute(
        "SELECT 1 FROM alliance_plans WHERE plan_code='free' AND status='active'",
    ).fetchone() is None:
        raise AllianceOperationError("免费套餐尚未初始化", status_code=503)
    timestamp = _iso(now)
    with conn:
        cursor = conn.execute(
            """INSERT INTO alliances
               (alliance_key, name, status, plan_code, creation_source,
                created_by_user_id, created_at, updated_at)
               VALUES (?, ?, 'active', 'free', 'platform', ?, ?, ?)""",
            (f"platform-{uuid.uuid4().hex}", display_name, int(actor["id"]), timestamp, timestamp),
        )
        alliance_id = int(cursor.lastrowid)
        conn.execute(
            """INSERT INTO alliance_members
               (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
               VALUES (?, ?, 'leader', 'active', ?, ?, ?)""",
            (alliance_id, int(actor["id"]), timestamp, timestamp, timestamp),
        )
        details = {"name": display_name, "plan_code": "free", "source": "platform"}
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["id"]),
            action="alliance_created_by_platform", entity_type="alliance",
            entity_id=alliance_id, details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="alliance_created",
            entity_type="alliance", entity_id=alliance_id,
            details=details, timestamp=timestamp,
        )
    return {"alliance_id": alliance_id, "name": display_name, "plan_code": "free", "status": "active"}


def _setting(conn: sqlite3.Connection, key: str, default: object) -> object:
    row = conn.execute(
        "SELECT value_json FROM platform_settings WHERE setting_key=?", (key,),
    ).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value_json"])
    except (TypeError, json.JSONDecodeError):
        return default


def free_registration_policy(conn: sqlite3.Connection) -> dict:
    enabled = bool(_setting(conn, "free_registration_enabled", False))
    try:
        limit = max(0, min(10000, int(_setting(conn, "free_registration_limit", 20))))
    except (TypeError, ValueError):
        limit = 20
    active = int(conn.execute(
        """SELECT COUNT(*) FROM alliances
           WHERE plan_code='free' AND status='active' AND creation_source='user'"""
    ).fetchone()[0])
    return {
        "public_open": enabled,
        "limit": limit,
        "active": active,
        "remaining": max(0, limit - active),
        "has_capacity": active < limit,
    }


def update_platform_settings(
    conn: sqlite3.Connection,
    openid: str,
    *,
    free_registration_enabled: bool,
    free_registration_limit: int,
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    limit = int(free_registration_limit)
    if limit < 0 or limit > 10000:
        raise AllianceOperationError("免费联盟配额必须在 0 到 10000 之间", status_code=422)
    timestamp = _iso(now)
    values = {
        "free_registration_enabled": bool(free_registration_enabled),
        "free_registration_limit": limit,
    }
    with conn:
        for key, value in values.items():
            conn.execute(
                """INSERT INTO platform_settings
                   (setting_key, value_json, updated_by_user_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(setting_key) DO UPDATE SET
                       value_json=excluded.value_json,
                       updated_by_user_id=excluded.updated_by_user_id,
                       updated_at=excluded.updated_at""",
                (key, _json(value), actor["id"], timestamp),
            )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="platform_settings_updated",
            entity_type="platform_settings", details=values, timestamp=timestamp,
        )
    return free_registration_policy(conn)


def verification_entry(conn: sqlite3.Connection, openid: str, alliance_id: int) -> dict:
    context = _member(conn, openid, alliance_id)
    clans = conn.execute(
        """SELECT clan_tag, clan_name, verification_status, verified_at
           FROM alliance_clans WHERE alliance_id=? AND status='active'
           ORDER BY sort_order, id""",
        (alliance_id,),
    ).fetchall()
    return {
        "mode": "manual",
        "self_service_available": False,
        "can_manage": context["role"] in {"admin", "leader"},
        "message": "认证暂由后台人工处理，请联系作者微信 pluto1944606",
        "clans": [dict(row) for row in clans],
    }


def rename_alliance(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    name: str,
    *,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"leader"})
    display_name = str(name or "").strip()
    if not display_name:
        raise AllianceOperationError("联盟名称不能为空", status_code=422)
    if len(display_name) > 30:
        raise AllianceOperationError("联盟名称不能超过 30 个字符", status_code=422)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliances SET name=?, updated_at=? WHERE id=?",
            (display_name, timestamp, int(alliance_id)),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_renamed", entity_type="alliance", entity_id=int(alliance_id),
            details={"before": actor["name"], "after": display_name}, timestamp=timestamp,
        )
    return {"alliance_id": int(alliance_id), "name": display_name}


def _managed_clan_actor(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    platform: bool = False,
    leader_required: bool = False,
    now: datetime | None = None,
) -> Mapping[str, object]:
    if platform:
        user = require_platform_admin(conn, openid)
        alliance = conn.execute(
            "SELECT name, status, plan_code FROM alliances WHERE id=?",
            (int(alliance_id),),
        ).fetchone()
        if alliance is None or alliance["status"] == "archived":
            raise AllianceOperationError("联盟不存在", status_code=404)
        if alliance["status"] != "active":
            raise AllianceOperationError("请先恢复联盟，再管理部落", status_code=409)
        return {
            "user_id": int(user["id"]), "role": "platform_admin",
            "name": alliance["name"], "alliance_status": alliance["status"],
            "plan_code": alliance["plan_code"], "platform_admin": True,
        }
    actor = _member(
        conn, openid, alliance_id,
        roles={"leader"} if leader_required else {"admin", "leader"},
    )
    if actor["plan_code"] not in {"free", "paid"}:
        raise AllianceOperationError("当前联盟的部落由系统配置，不能在小程序内修改", status_code=409)
    if actor["plan_code"] == "paid":
        latest_grant = conn.execute(
            """SELECT status, expires_at FROM alliance_plan_grants
               WHERE alliance_id=? ORDER BY id DESC LIMIT 1""",
            (int(alliance_id),),
        ).fetchone()
        grant_expiry = _parse_time(latest_grant["expires_at"]) if latest_grant else None
        if latest_grant is not None and (
            latest_grant["status"] != "active"
            or (grant_expiry is not None and grant_expiry <= _now(now))
        ):
            raise AllianceOperationError("付费权益已到期，请先续期", status_code=409)
    return {**dict(actor), "platform_admin": False}


def list_managed_clans(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    platform: bool = False,
) -> dict:
    if platform:
        user = require_platform_admin(conn, openid)
        alliance = conn.execute(
            "SELECT name, status, plan_code FROM alliances WHERE id=?",
            (int(alliance_id),),
        ).fetchone()
        if alliance is None or alliance["status"] == "archived":
            raise AllianceOperationError("联盟不存在", status_code=404)
        actor = {
            "user_id": int(user["id"]), "role": "platform_admin",
            "plan_code": alliance["plan_code"], "platform_admin": True,
            "alliance_status": alliance["status"],
        }
    else:
        actor = {**dict(_member(conn, openid, alliance_id)), "platform_admin": False}
    plan = conn.execute(
        """SELECT alliances.plan_code, plans.max_clans FROM alliances
           JOIN alliance_plans AS plans ON plans.plan_code=alliances.plan_code
           WHERE alliances.id=?""",
        (int(alliance_id),),
    ).fetchone()
    rows = conn.execute(
        """SELECT id, clan_tag, clan_name, category, sort_order, status,
                  verification_status, verified_at
           FROM alliance_clans WHERE alliance_id=?
           ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, sort_order, id""",
        (int(alliance_id),),
    ).fetchall()
    active_count = sum(1 for row in rows if row["status"] == "active")
    plan_allows_management = bool(plan and plan["plan_code"] in {"free", "paid"})
    entitlement_status = "active"
    if plan and plan["plan_code"] == "paid":
        latest_grant = conn.execute(
            """SELECT status, expires_at FROM alliance_plan_grants
               WHERE alliance_id=? ORDER BY id DESC LIMIT 1""",
            (int(alliance_id),),
        ).fetchone()
        grant_expiry = _parse_time(latest_grant["expires_at"]) if latest_grant else None
        if latest_grant is not None and (
            latest_grant["status"] != "active"
            or (grant_expiry is not None and grant_expiry <= _now())
        ):
            plan_allows_management = False
            if latest_grant["status"] == "active" and grant_expiry is not None:
                entitlement_status = (
                    "grace" if grant_expiry > _now() - timedelta(days=7) else "expired"
                )
            else:
                entitlement_status = latest_grant["status"]
        elif latest_grant is None:
            entitlement_status = "legacy"
    is_platform = bool(actor.get("platform_admin"))
    can_manage = (is_platform and actor["alliance_status"] == "active") or (
        actor["role"] in {"admin", "leader"} and plan_allows_management
    )
    can_change_membership = bool(is_platform or (
        actor["role"] == "leader" and plan_allows_management
    ))
    return {
        "alliance_id": int(alliance_id), "actor_role": actor["role"],
        "plan_code": plan["plan_code"] if plan else actor["plan_code"],
        "entitlement_status": entitlement_status,
        "max_clans": int(plan["max_clans"]) if plan else 1,
        "unlimited": is_platform,
        "active_count": active_count,
        "can_manage": bool(can_manage),
        "can_add": bool((is_platform and can_manage) or (
            can_change_membership and active_count < (int(plan["max_clans"]) if plan else 1)
        )),
        "can_remove": can_change_membership,
        "clans": [dict(row) for row in rows],
    }


def add_managed_clan(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    clan_tag: str,
    category: str,
    clan_name: str = "",
    platform: bool = False,
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(
        conn, openid, alliance_id, platform=platform,
        leader_required=True, now=now,
    )
    tag = _clan_tag(clan_tag)
    selected_category = str(category or "").strip()
    if selected_category not in _CATEGORIES:
        raise AllianceOperationError("部落标签仅支持实战、战营、互刷或偷矿", status_code=422)
    profile = conn.execute(
        "SELECT clan_name FROM clan_profile_cache WHERE clan_tag=?", (tag,),
    ).fetchone()
    display_name = str(clan_name or "").strip() or (
        profile["clan_name"] if profile and profile["clan_name"] else tag
    )
    if len(display_name) > 40:
        raise AllianceOperationError("部落名称不能超过 40 个字符", status_code=422)
    timestamp = _iso(now)
    existing = conn.execute(
        "SELECT * FROM alliance_clans WHERE alliance_id=? AND clan_tag=?",
        (int(alliance_id), tag),
    ).fetchone()
    if existing is not None and existing["status"] == "active":
        raise AllianceOperationError("该部落已在当前联盟中", status_code=409)
    active_count = int(conn.execute(
        "SELECT COUNT(*) FROM alliance_clans WHERE alliance_id=? AND status='active'",
        (int(alliance_id),),
    ).fetchone()[0])
    if not actor["platform_admin"]:
        plan_limit = conn.execute(
            """SELECT plans.max_clans FROM alliances
               JOIN alliance_plans AS plans ON plans.plan_code=alliances.plan_code
               WHERE alliances.id=?""",
            (int(alliance_id),),
        ).fetchone()
        if plan_limit is None or active_count >= int(plan_limit["max_clans"]):
            raise AllianceOperationError("已达到当前套餐的部落数量上限", status_code=409)
    try:
        with conn:
            if actor["platform_admin"]:
                conn.execute(
                    """UPDATE alliances
                       SET clan_limit_override=MAX(COALESCE(clan_limit_override, 0), ?),
                           updated_at=?
                       WHERE id=?""",
                    (active_count + 1, timestamp, int(alliance_id)),
                )
            if existing is None:
                order = int(conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM alliance_clans WHERE alliance_id=?",
                    (int(alliance_id),),
                ).fetchone()[0])
                conn.execute(
                    """INSERT INTO alliance_clans
                       (alliance_id, clan_tag, clan_name, category, sort_order, status,
                        verification_status, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'active', 'unverified', 'manual', ?, ?)""",
                    (int(alliance_id), tag, display_name, selected_category, order, timestamp, timestamp),
                )
                action = "managed_clan_added"
            else:
                conn.execute(
                    """UPDATE alliance_clans SET clan_name=?, category=?, status='active',
                              verification_status='unverified', verified_by_user_id=NULL,
                              verified_at=NULL, updated_at=? WHERE id=?""",
                    (display_name, selected_category, timestamp, existing["id"]),
                )
                action = "managed_clan_reactivated"
            _alliance_audit(
                conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
                action=action, entity_type="alliance_clan", entity_id=tag,
                details={"clan_name": display_name, "category": selected_category},
                timestamp=timestamp,
            )
            if actor["platform_admin"]:
                _platform_audit(
                    conn, actor_user_id=int(actor["user_id"]), action=action,
                    entity_type="alliance_clan", entity_id=tag,
                    details={"alliance_id": int(alliance_id), "category": selected_category},
                    timestamp=timestamp,
                )
    except sqlite3.IntegrityError as exc:
        if "active clan limit" in str(exc):
            raise AllianceOperationError("已达到当前套餐的部落数量上限", status_code=409) from exc
        raise
    return {
        "clan_tag": tag, "clan_name": display_name, "category": selected_category,
        "verification_status": "unverified", "status": "active",
    }


def update_managed_clan(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tag: str,
    *,
    category: str,
    clan_name: str | None = None,
    platform: bool = False,
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(conn, openid, alliance_id, platform=platform, now=now)
    tag = _clan_tag(clan_tag)
    selected_category = str(category or "").strip()
    if selected_category not in _CATEGORIES:
        raise AllianceOperationError("部落标签仅支持实战、战营、互刷或偷矿", status_code=422)
    row = conn.execute(
        """SELECT id, clan_name, category, verification_status FROM alliance_clans
           WHERE alliance_id=? AND clan_tag=? AND status='active'""",
        (int(alliance_id), tag),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("部落不在当前有效订阅中", status_code=404)
    display_name = row["clan_name"]
    if clan_name is not None:
        display_name = str(clan_name).strip() or tag
        if len(display_name) > 40:
            raise AllianceOperationError("部落名称不能超过 40 个字符", status_code=422)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliance_clans SET clan_name=?, category=?, updated_at=? WHERE id=?",
            (display_name, selected_category, timestamp, row["id"]),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="managed_clan_category_updated", entity_type="alliance_clan", entity_id=tag,
            details={
                "before": {"clan_name": row["clan_name"], "category": row["category"]},
                "after": {"clan_name": display_name, "category": selected_category},
            }, timestamp=timestamp,
        )
        if actor["platform_admin"]:
            _platform_audit(
                conn, actor_user_id=int(actor["user_id"]),
                action="managed_clan_category_updated", entity_type="alliance_clan",
                entity_id=tag,
                details={
                    "alliance_id": int(alliance_id),
                    "before": {"clan_name": row["clan_name"], "category": row["category"]},
                    "after": {"clan_name": display_name, "category": selected_category},
                },
                timestamp=timestamp,
            )
    return {
        "clan_tag": tag, "clan_name": display_name, "category": selected_category,
        "verification_status": row["verification_status"], "status": "active",
    }


def reorder_managed_clans(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tags: list[str],
    *,
    platform: bool = False,
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(conn, openid, alliance_id, platform=platform, now=now)
    tags = [_clan_tag(tag) for tag in clan_tags]
    if len(tags) != len(set(tags)):
        raise AllianceOperationError("部落顺序中存在重复标签", status_code=422)
    rows = conn.execute(
        """SELECT clan_tag FROM alliance_clans
           WHERE alliance_id=? AND status='active' ORDER BY sort_order, id""",
        (int(alliance_id),),
    ).fetchall()
    current_tags = [row["clan_tag"] for row in rows]
    if len(tags) != len(current_tags) or set(tags) != set(current_tags):
        raise AllianceOperationError("部落顺序必须包含当前全部有效部落", status_code=422)
    timestamp = _iso(now)
    with conn:
        for order, tag in enumerate(tags):
            conn.execute(
                """UPDATE alliance_clans SET sort_order=?, updated_at=?
                   WHERE alliance_id=? AND clan_tag=? AND status='active'""",
                (order, timestamp, int(alliance_id), tag),
            )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="managed_clans_reordered", entity_type="alliance_clan_order",
            details={"before": current_tags, "after": tags}, timestamp=timestamp,
        )
        if actor["platform_admin"]:
            _platform_audit(
                conn, actor_user_id=int(actor["user_id"]), action="managed_clans_reordered",
                entity_type="alliance_clan_order", entity_id=int(alliance_id),
                details={"before": current_tags, "after": tags}, timestamp=timestamp,
            )
    return {"clan_tags": tags}


def remove_managed_clan(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tag: str,
    *,
    platform: bool = False,
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(
        conn, openid, alliance_id, platform=platform,
        leader_required=True, now=now,
    )
    tag = _clan_tag(clan_tag)
    row = conn.execute(
        """SELECT id, status, verification_status FROM alliance_clans
           WHERE alliance_id=? AND clan_tag=?""",
        (int(alliance_id), tag),
    ).fetchone()
    if row is None or row["status"] != "active":
        raise AllianceOperationError("部落不在当前有效订阅中", status_code=404)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            """UPDATE alliance_clans SET status='removed', verification_status='revoked',
                      verified_by_user_id=NULL, verified_at=NULL, updated_at=? WHERE id=?""",
            (timestamp, row["id"]),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="managed_clan_removed", entity_type="alliance_clan", entity_id=tag,
            details={"verification_before": row["verification_status"]}, timestamp=timestamp,
        )
        if actor["platform_admin"]:
            _platform_audit(
                conn, actor_user_id=int(actor["user_id"]), action="managed_clan_removed",
                entity_type="alliance_clan", entity_id=tag,
                details={"alliance_id": int(alliance_id), "verification_before": row["verification_status"]},
                timestamp=timestamp,
            )
    return {"clan_tag": tag, "status": "removed"}


def manual_set_clan_verification(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tag: str,
    status: str,
    *,
    note: str = "",
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    selected = str(status or "").strip()
    if selected not in {"verified", "unverified", "disputed", "revoked"}:
        raise AllianceOperationError("不支持的认证状态", status_code=422)
    tag = normalize_tag(clan_tag)
    row = conn.execute(
        """SELECT id, verification_status FROM alliance_clans
           WHERE alliance_id=? AND clan_tag=? AND status='active'""",
        (int(alliance_id), tag),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("部落不在目标联盟订阅范围内", status_code=404)
    also_verified: list[sqlite3.Row] = []
    if selected == "verified":
        also_verified = conn.execute(
            """SELECT alliances.id AS alliance_id, alliances.name
               FROM alliance_clans AS clans
               JOIN alliances ON alliances.id=clans.alliance_id
               WHERE clans.clan_tag=? AND clans.verification_status='verified'
                 AND clans.status='active' AND alliances.status='active'
                 AND alliances.id != ?
               ORDER BY alliances.id""",
            (tag, int(alliance_id)),
        ).fetchall()
    timestamp = _iso(now)
    with conn:
        conn.execute(
            """UPDATE alliance_clans
               SET verification_status=?, verified_by_user_id=?, verified_at=?, updated_at=?
               WHERE id=?""",
            (
                selected,
                actor["id"] if selected == "verified" else None,
                timestamp if selected == "verified" else None,
                timestamp, row["id"],
            ),
        )
        details = {
            "before": row["verification_status"], "after": selected,
            "also_verified_alliances": [
                {"alliance_id": int(item["alliance_id"]), "alliance_name": item["name"]}
                for item in also_verified
            ],
            "note": note[:500],
        }
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["id"]),
            action="manual_clan_verification_updated", entity_type="alliance_clan",
            entity_id=tag, details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="manual_clan_verification_updated",
            entity_type="alliance_clan", entity_id=f"{alliance_id}:{tag}",
            details=details, timestamp=timestamp,
        )
    return {
        "alliance_id": int(alliance_id), "clan_tag": tag,
        "verification_status": selected, "verified_at": timestamp if selected == "verified" else None,
        "also_verified_alliances": [
            {"alliance_id": int(item["alliance_id"]), "alliance_name": item["name"]}
            for item in also_verified
        ],
    }


def create_share_link(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    share_type: str = "invite",
    expires_days: int = 30,
    now: datetime | None = None,
) -> dict:
    selected_type = str(share_type or "invite").strip()
    if selected_type not in {"browse", "invite"}:
        raise AllianceOperationError("不支持的分享类型", status_code=422)
    actor = _member(
        conn, openid, alliance_id,
        roles={"admin", "leader"} if selected_type == "invite" else None,
    )
    days = int(expires_days)
    if days < 1 or days > 30:
        raise AllianceOperationError("分享有效期必须在 1 到 30 天之间", status_code=422)
    current = _now(now)
    timestamp = _iso(current)
    expires_at = _iso(current + timedelta(days=days))
    active_links = int(conn.execute(
        """SELECT COUNT(*) FROM alliance_share_links
           WHERE alliance_id=? AND share_type=? AND status='active' AND expires_at>?""",
        (int(alliance_id), selected_type, timestamp),
    ).fetchone()[0])
    if selected_type == "invite" and active_links >= 5:
        raise AllianceOperationError("当前联盟最多保留 5 个有效邀请，请先撤销旧邀请", status_code=409)
    if selected_type == "browse":
        with conn:
            conn.execute(
                """UPDATE alliance_share_links SET status='revoked', updated_at=?
                   WHERE alliance_id=? AND created_by_user_id=?
                     AND share_type='browse' AND status='active'""",
                (timestamp, int(alliance_id), int(actor["user_id"])),
            )
    raw_token = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with conn:
        cursor = conn.execute(
            """INSERT INTO alliance_share_links
               (token_hash, alliance_id, created_by_user_id, visibility, share_type, status,
                expires_at, created_at, updated_at)
               VALUES (?, ?, ?, 'member', ?, 'active', ?, ?, ?)""",
            (digest, int(alliance_id), actor["user_id"], selected_type, expires_at, timestamp, timestamp),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_share_created", entity_type="alliance_share_link",
            entity_id=int(cursor.lastrowid), details={"expires_at": expires_at, "share_type": selected_type},
            timestamp=timestamp,
        )
    return {
        "token": raw_token, "expires_at": expires_at,
        "alliance_id": int(alliance_id), "share_type": selected_type,
    }


def _share_row(conn: sqlite3.Connection, token: str, current: datetime) -> sqlite3.Row:
    digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    row = conn.execute(
        """SELECT links.*, alliances.name AS alliance_name, alliances.status AS alliance_status,
                  alliances.plan_code, plans.display_name AS plan_name
           FROM alliance_share_links AS links
           JOIN alliances ON alliances.id=links.alliance_id
           JOIN alliance_plans AS plans ON plans.plan_code=alliances.plan_code
           WHERE links.token_hash=?""",
        (digest,),
    ).fetchone()
    if row is None or row["status"] != "active" or row["alliance_status"] != "active":
        raise AllianceOperationError("分享链接无效或已撤销", status_code=404)
    expiry = _parse_time(row["expires_at"])
    if expiry is None or expiry <= current:
        with conn:
            conn.execute(
                "UPDATE alliance_share_links SET status='expired', updated_at=? WHERE id=?",
                (_iso(current), row["id"]),
            )
        raise AllianceOperationError("分享链接已过期", status_code=410)
    return row


def share_preview(conn: sqlite3.Connection, token: str, *, now: datetime | None = None) -> dict:
    row = _share_row(conn, token, _now(now))
    clan_count = int(conn.execute(
        "SELECT COUNT(*) FROM alliance_clans WHERE alliance_id=? AND status='active'",
        (row["alliance_id"],),
    ).fetchone()[0])
    return {
        "alliance_id": int(row["alliance_id"]), "name": row["alliance_name"],
        "plan_name": row["plan_name"], "clan_count": clan_count,
        "expires_at": row["expires_at"], "share_type": row["share_type"],
        "can_join": row["share_type"] == "invite",
    }


def share_alliance_id(
    conn: sqlite3.Connection,
    token: str,
    *,
    now: datetime | None = None,
) -> int:
    return int(_share_row(conn, token, _now(now))["alliance_id"])


def record_share_visit(
    conn: sqlite3.Connection,
    openid: str,
    token: str,
    *,
    make_default: bool = True,
    now: datetime | None = None,
) -> dict:
    current = _now(now)
    timestamp = _iso(current)
    link = _share_row(conn, token, current)
    user = _user(conn, openid)
    alliance_id = int(link["alliance_id"])
    with conn:
        if make_default:
            conn.execute("UPDATE alliance_visits SET is_default=0 WHERE user_id=?", (user["id"],))
        conn.execute(
            """INSERT INTO alliance_visits
               (alliance_id, user_id, is_default, is_hidden, hidden_at,
                first_visited_at, last_visited_at)
               VALUES (?, ?, ?, 0, NULL, ?, ?)
               ON CONFLICT(alliance_id, user_id) DO UPDATE SET
                   is_default=excluded.is_default, is_hidden=0, hidden_at=NULL,
                   last_visited_at=excluded.last_visited_at""",
            (alliance_id, user["id"], 1 if make_default else 0, timestamp, timestamp),
        )
        stale = conn.execute(
            """SELECT visits.alliance_id
               FROM alliance_visits AS visits
               LEFT JOIN alliance_members AS members
                 ON members.alliance_id=visits.alliance_id
                AND members.user_id=visits.user_id AND members.status='active'
               WHERE visits.user_id=? AND members.id IS NULL
               ORDER BY visits.last_visited_at DESC, visits.alliance_id DESC
               LIMIT -1 OFFSET 50""",
            (user["id"],),
        ).fetchall()
        if stale:
            conn.executemany(
                "DELETE FROM alliance_visits WHERE user_id=? AND alliance_id=?",
                [(user["id"], row["alliance_id"]) for row in stale],
            )
    return {
        "alliance_id": alliance_id,
        "share_type": link["share_type"],
        "last_visited_at": timestamp,
    }


def join_from_share(
    conn: sqlite3.Connection,
    openid: str,
    token: str,
    *,
    now: datetime | None = None,
) -> dict:
    current = _now(now)
    timestamp = _iso(current)
    link = _share_row(conn, token, current)
    if link["share_type"] != "invite":
        raise AllianceOperationError("普通分享不能直接加入，请先申请", status_code=409)
    user = _user(conn, openid)
    alliance_id = int(link["alliance_id"])
    membership = conn.execute(
        "SELECT id, role, status FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (alliance_id, user["id"]),
    ).fetchone()
    if membership is not None and membership["status"] in {"removed", "blocked"}:
        raise AllianceOperationError("你已被该联盟移除，无法通过分享重新加入", status_code=403)
    joined = membership is None or membership["status"] != "active"
    if joined:
        recent_joins = int(conn.execute(
            """SELECT COUNT(*) FROM alliance_audit_events
               WHERE actor_user_id=? AND action='alliance_share_joined' AND created_at>=?""",
            (user["id"], _iso(current - timedelta(days=1))),
        ).fetchone()[0])
        if recent_joins >= 20:
            raise AllianceOperationError("加入联盟过于频繁，请稍后再试", status_code=429)
    with conn:
        if joined:
            claimed = conn.execute(
                """UPDATE alliance_share_links
                   SET use_count=use_count+1, last_used_at=?, updated_at=?
                   WHERE id=? AND status='active' AND use_count < 1000""",
                (timestamp, timestamp, link["id"]),
            )
            if claimed.rowcount != 1:
                raise AllianceOperationError(
                    "该分享已达到使用上限，请联系联盟重新生成", status_code=429,
                )
        if membership is None:
            conn.execute(
                """INSERT INTO alliance_members
                   (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
                   VALUES (?, ?, 'member', 'active', ?, ?, ?)""",
                (alliance_id, user["id"], timestamp, timestamp, timestamp),
            )
        elif membership["status"] != "active":
            conn.execute(
                """UPDATE alliance_members SET role='member', status='active',
                          joined_at=?, updated_at=? WHERE id=?""",
                (timestamp, timestamp, membership["id"]),
            )
        conn.execute("UPDATE alliance_visits SET is_default=0 WHERE user_id=?", (user["id"],))
        conn.execute(
            """INSERT INTO alliance_visits
               (alliance_id, user_id, is_default, is_hidden, hidden_at,
                first_visited_at, last_visited_at)
               VALUES (?, ?, 1, 0, NULL, ?, ?)
               ON CONFLICT(alliance_id, user_id) DO UPDATE SET
                   is_default=1, is_hidden=0, hidden_at=NULL,
                   last_visited_at=excluded.last_visited_at""",
            (alliance_id, user["id"], timestamp, timestamp),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(user["id"]),
            action="alliance_share_joined" if joined else "alliance_share_reopened",
            entity_type="alliance_member", entity_id=int(user["id"]),
            details={"share_link_id": int(link["id"]), "role": "member"},
            timestamp=timestamp,
        )
    return {"alliance_id": alliance_id, "joined": joined, "role": "member"}


def request_alliance_join(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    now: datetime | None = None,
) -> dict:
    user = _user(conn, openid)
    alliance = conn.execute(
        "SELECT id FROM alliances WHERE id=? AND status='active'",
        (int(alliance_id),),
    ).fetchone()
    if alliance is None:
        raise AllianceOperationError("联盟不存在", status_code=404)
    membership = conn.execute(
        "SELECT role, status FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (int(alliance_id), int(user["id"])),
    ).fetchone()
    if membership is not None and membership["status"] == "active":
        raise AllianceOperationError("你已经是该联盟成员", status_code=409)
    if membership is not None and membership["status"] == "blocked":
        raise AllianceOperationError("你已被该联盟封禁，无法申请", status_code=403)
    visit = conn.execute(
        "SELECT 1 FROM alliance_visits WHERE alliance_id=? AND user_id=?",
        (int(alliance_id), int(user["id"])),
    ).fetchone()
    if visit is None:
        raise AllianceOperationError("请先通过有效分享打开该联盟", status_code=403)
    current = _now(now)
    timestamp = _iso(current)
    existing = conn.execute(
        """SELECT id, status, updated_at FROM alliance_join_requests
           WHERE alliance_id=? AND user_id=? ORDER BY id DESC LIMIT 1""",
        (int(alliance_id), int(user["id"])),
    ).fetchone()
    if existing is not None and existing["status"] == "pending":
        return {"id": int(existing["id"]), "alliance_id": int(alliance_id), "status": "pending"}
    if existing is not None and existing["status"] == "rejected":
        rejected_at = _parse_time(existing["updated_at"])
        if rejected_at and rejected_at > current - timedelta(hours=24):
            raise AllianceOperationError("申请被拒绝后 24 小时内不能重复提交", status_code=429)
    with conn:
        cursor = conn.execute(
            """INSERT INTO alliance_join_requests
               (alliance_id, user_id, status, created_at, updated_at)
               VALUES (?, ?, 'pending', ?, ?)""",
            (int(alliance_id), int(user["id"]), timestamp, timestamp),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(user["id"]),
            action="alliance_join_requested", entity_type="alliance_join_request",
            entity_id=int(cursor.lastrowid), timestamp=timestamp,
        )
    return {"id": int(cursor.lastrowid), "alliance_id": int(alliance_id), "status": "pending"}


def list_join_requests(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"admin", "leader"})
    rows = conn.execute(
        """SELECT requests.id, requests.status, requests.created_at, requests.updated_at,
                  users.nickname, users.account_name, users.player_tag
           FROM alliance_join_requests AS requests
           JOIN wechat_users AS users ON users.id=requests.user_id
           WHERE requests.alliance_id=?
           ORDER BY CASE requests.status WHEN 'pending' THEN 0 ELSE 1 END,
                    requests.created_at DESC LIMIT 100""",
        (int(alliance_id),),
    ).fetchall()
    return {
        "alliance_id": int(alliance_id), "actor_role": actor["role"],
        "requests": [
            {
                "id": int(row["id"]), "status": row["status"],
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "display_name": row["nickname"] or row["account_name"] or f"微信用户{row['id']}",
                "player_tag": row["player_tag"],
            }
            for row in rows
        ],
    }


def review_join_request(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    request_id: int,
    action: str,
    *,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"admin", "leader"})
    selected = str(action or "").strip()
    if selected not in {"approve", "reject"}:
        raise AllianceOperationError("只能批准或拒绝申请", status_code=422)
    row = conn.execute(
        """SELECT * FROM alliance_join_requests
           WHERE id=? AND alliance_id=? AND status='pending'""",
        (int(request_id), int(alliance_id)),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("待处理申请不存在", status_code=404)
    membership = conn.execute(
        "SELECT id, status FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (int(alliance_id), int(row["user_id"])),
    ).fetchone()
    if membership is not None and membership["status"] == "blocked":
        raise AllianceOperationError("已封禁用户不能通过申请恢复", status_code=409)
    timestamp = _iso(now)
    status = "approved" if selected == "approve" else "rejected"
    with conn:
        conn.execute(
            """UPDATE alliance_join_requests
               SET status=?, reviewed_by_user_id=?, reviewed_at=?, updated_at=?
               WHERE id=?""",
            (status, int(actor["user_id"]), timestamp, timestamp, int(request_id)),
        )
        if selected == "approve":
            if membership is None:
                conn.execute(
                    """INSERT INTO alliance_members
                       (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
                       VALUES (?, ?, 'member', 'active', ?, ?, ?)""",
                    (int(alliance_id), int(row["user_id"]), timestamp, timestamp, timestamp),
                )
            else:
                conn.execute(
                    """UPDATE alliance_members SET role='member', status='active',
                              joined_at=?, updated_at=? WHERE id=?""",
                    (timestamp, timestamp, int(membership["id"])),
                )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action=f"alliance_join_request_{status}", entity_type="alliance_join_request",
            entity_id=int(request_id), details={"user_id": int(row["user_id"])},
            timestamp=timestamp,
        )
    return {"id": int(request_id), "status": status}


def delete_browsing_history(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
) -> dict:
    user = _user(conn, openid)
    active = conn.execute(
        """SELECT 1 FROM alliance_members
           WHERE alliance_id=? AND user_id=? AND status='active'""",
        (int(alliance_id), int(user["id"])),
    ).fetchone()
    if active is not None:
        raise AllianceOperationError("已加入联盟请使用退出功能", status_code=409)
    with conn:
        cursor = conn.execute(
            "DELETE FROM alliance_visits WHERE alliance_id=? AND user_id=?",
            (int(alliance_id), int(user["id"])),
        )
    if not cursor.rowcount:
        raise AllianceOperationError("浏览记录不存在", status_code=404)
    return {"alliance_id": int(alliance_id), "removed": True}


def revoke_share_link(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    link_id: int,
    *,
    now: datetime | None = None,
) -> None:
    actor = _member(conn, openid, alliance_id)
    row = conn.execute(
        "SELECT * FROM alliance_share_links WHERE id=? AND alliance_id=?",
        (int(link_id), int(alliance_id)),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("分享链接不存在", status_code=404)
    if actor["role"] == "member" and int(row["created_by_user_id"]) != int(actor["user_id"]):
        raise AllianceOperationError("只能撤销自己创建的分享", status_code=403)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliance_share_links SET status='revoked', updated_at=? WHERE id=?",
            (timestamp, int(link_id)),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_share_revoked", entity_type="alliance_share_link",
            entity_id=int(link_id), timestamp=timestamp,
        )


def list_share_links(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
) -> list[dict]:
    actor = _member(conn, openid, alliance_id)
    current = _now()
    rows = conn.execute(
        """SELECT id, created_by_user_id, share_type, status, expires_at, use_count,
                  last_used_at, created_at
           FROM alliance_share_links WHERE alliance_id=?
           ORDER BY id DESC LIMIT 50""",
        (int(alliance_id),),
    ).fetchall()
    result = []
    for row in rows:
        expiry = _parse_time(row["expires_at"])
        effective_status = row["status"]
        if effective_status == "active" and expiry is not None and expiry <= current:
            effective_status = "expired"
        result.append({
            "id": int(row["id"]), "status": effective_status,
            "share_type": row["share_type"],
            "expires_at": row["expires_at"], "use_count": int(row["use_count"]),
            "last_used_at": row["last_used_at"], "created_at": row["created_at"],
            "can_revoke": effective_status == "active" and (
                actor["role"] in {"admin", "leader"}
                or int(row["created_by_user_id"]) == int(actor["user_id"])
            ),
        })
    return result


def list_alliance_members(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"admin", "leader"})
    rows = conn.execute(
        """SELECT members.id, members.role, members.status, members.joined_at,
                  users.nickname, users.account_name, users.player_tag
           FROM alliance_members AS members
           JOIN wechat_users AS users ON users.id=members.user_id
           WHERE members.alliance_id=?
           ORDER BY CASE members.status WHEN 'active' THEN 0 ELSE 1 END,
                    CASE members.role WHEN 'leader' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                    members.id""",
        (int(alliance_id),),
    ).fetchall()
    return {
        "alliance_id": int(alliance_id), "actor_role": actor["role"],
        "members": [
            {
                "id": int(row["id"]), "role": row["role"], "status": row["status"],
                "joined_at": row["joined_at"],
                "display_name": row["nickname"] or row["account_name"] or f"微信用户{row['id']}",
                "player_tag": row["player_tag"],
            }
            for row in rows
        ],
    }


def _platform_member_target(
    conn: sqlite3.Connection,
    alliance_id: int,
    member_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT members.*, users.openid
           FROM alliance_members AS members
           JOIN wechat_users AS users ON users.id=members.user_id
           WHERE members.id=? AND members.alliance_id=?""",
        (int(member_id), int(alliance_id)),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("联盟成员不存在", status_code=404)
    return row


def platform_add_alliance_member(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    target_openid: str,
    role: str = "member",
    *,
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    selected = str(role or "member").strip()
    if selected not in {"member", "admin", "leader"}:
        raise AllianceOperationError("不支持的联盟角色", status_code=422)
    normalized_openid = str(target_openid or "").strip()
    target_user = conn.execute(
        "SELECT id FROM wechat_users WHERE openid=?", (normalized_openid,),
    ).fetchone()
    if target_user is None:
        raise AllianceOperationError("未找到该用户，请让对方先登录小程序", status_code=404)
    alliance = conn.execute(
        "SELECT id, status FROM alliances WHERE id=?", (int(alliance_id),),
    ).fetchone()
    if alliance is None or alliance["status"] == "archived":
        raise AllianceOperationError("联盟不存在", status_code=404)
    existing = conn.execute(
        "SELECT id, role, status FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (int(alliance_id), int(target_user["id"])),
    ).fetchone()
    if (
        existing is not None and existing["status"] == "active"
        and existing["role"] == "leader" and selected != "leader"
    ):
        raise AllianceOperationError("请先把首领移交给其他成员", status_code=409)
    timestamp = _iso(now)
    with conn:
        if selected == "leader":
            conn.execute(
                """UPDATE alliance_members SET role='admin', updated_at=?
                   WHERE alliance_id=? AND role='leader' AND status='active'""",
                (timestamp, int(alliance_id)),
            )
        if existing is None:
            cursor = conn.execute(
                """INSERT INTO alliance_members
                   (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
                   VALUES (?, ?, ?, 'active', ?, ?, ?)""",
                (int(alliance_id), int(target_user["id"]), selected,
                 timestamp, timestamp, timestamp),
            )
            member_id = int(cursor.lastrowid)
            before = None
        else:
            member_id = int(existing["id"])
            before = {"role": existing["role"], "status": existing["status"]}
            conn.execute(
                """UPDATE alliance_members
                   SET role=?, status='active', joined_at=COALESCE(joined_at, ?), updated_at=?
                   WHERE id=?""",
                (selected, timestamp, timestamp, member_id),
            )
        details = {"member_id": member_id, "before": before, "role": selected}
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["id"]),
            action="platform_member_added", entity_type="alliance_member",
            entity_id=member_id, details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="alliance_member_added",
            entity_type="alliance_member", entity_id=member_id,
            details={"alliance_id": int(alliance_id), **details}, timestamp=timestamp,
        )
    return {"member_id": member_id, "role": selected, "status": "active"}


def platform_set_alliance_member_role(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    member_id: int,
    role: str,
    *,
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    selected = str(role or "").strip()
    if selected not in {"member", "admin", "leader"}:
        raise AllianceOperationError("不支持的联盟角色", status_code=422)
    target = _platform_member_target(conn, alliance_id, member_id)
    if target["status"] != "active":
        raise AllianceOperationError("只能调整有效成员的角色", status_code=409)
    if target["role"] == "leader" and selected != "leader":
        raise AllianceOperationError("请先把首领移交给其他成员", status_code=409)
    timestamp = _iso(now)
    with conn:
        if selected == "leader":
            conn.execute(
                """UPDATE alliance_members SET role='admin', updated_at=?
                   WHERE alliance_id=? AND role='leader' AND status='active' AND id!=?""",
                (timestamp, int(alliance_id), int(member_id)),
            )
        conn.execute(
            "UPDATE alliance_members SET role=?, updated_at=? WHERE id=?",
            (selected, timestamp, int(member_id)),
        )
        action = "platform_leader_assigned" if selected == "leader" else "platform_member_role_updated"
        details = {"before": target["role"], "after": selected}
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["id"]),
            action=action, entity_type="alliance_member", entity_id=int(member_id),
            details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action=action,
            entity_type="alliance_member", entity_id=int(member_id),
            details={"alliance_id": int(alliance_id), **details}, timestamp=timestamp,
        )
    return {"member_id": int(member_id), "role": selected, "status": "active"}


def platform_remove_alliance_member(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    member_id: int,
    *,
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    target = _platform_member_target(conn, alliance_id, member_id)
    if target["status"] != "active":
        raise AllianceOperationError("该成员已经不是有效成员", status_code=409)
    if target["role"] == "leader":
        raise AllianceOperationError("请先把首领移交给其他成员", status_code=409)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliance_members SET status='removed', updated_at=? WHERE id=?",
            (timestamp, int(member_id)),
        )
        details = {"before_role": target["role"], "status": "removed"}
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["id"]),
            action="platform_member_removed", entity_type="alliance_member",
            entity_id=int(member_id), details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="alliance_member_removed",
            entity_type="alliance_member", entity_id=int(member_id),
            details={"alliance_id": int(alliance_id), **details}, timestamp=timestamp,
        )
    return {"member_id": int(member_id), "status": "removed"}


def add_alliance_member_by_openid(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    target_openid: str,
    role: str = "member",
    *,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"admin", "leader"})
    selected_role = str(role or "member").strip()
    if selected_role not in {"member", "admin"}:
        raise AllianceOperationError("只能添加普通成员或管理员", status_code=422)
    if actor["role"] == "admin" and selected_role != "member":
        raise AllianceOperationError("管理员只能添加普通成员", status_code=403)
    normalized_openid = str(target_openid or "").strip()
    if not normalized_openid:
        raise AllianceOperationError("请输入 OpenID", status_code=422)
    target = conn.execute(
        "SELECT id FROM wechat_users WHERE openid=?", (normalized_openid,),
    ).fetchone()
    if target is None:
        raise AllianceOperationError("未找到该用户，请让对方先登录小程序", status_code=404)
    existing = conn.execute(
        "SELECT id, role, status FROM alliance_members WHERE alliance_id=? AND user_id=?",
        (int(alliance_id), int(target["id"])),
    ).fetchone()
    if existing is not None and existing["status"] == "blocked":
        raise AllianceOperationError("该用户已被联盟封禁，请先由后台处理", status_code=409)
    timestamp = _iso(now)
    with conn:
        if existing is None:
            cursor = conn.execute(
                """INSERT INTO alliance_members
                   (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
                   VALUES (?, ?, ?, 'active', ?, ?, ?)""",
                (
                    int(alliance_id), int(target["id"]), selected_role,
                    timestamp, timestamp, timestamp,
                ),
            )
            member_id = int(cursor.lastrowid)
        else:
            member_id = int(existing["id"])
            conn.execute(
                """UPDATE alliance_members
                   SET role=?, status='active', joined_at=COALESCE(joined_at, ?), updated_at=?
                   WHERE id=?""",
                (selected_role, timestamp, timestamp, member_id),
            )
        conn.execute(
            "DELETE FROM alliance_join_requests WHERE alliance_id=? AND user_id=? AND status='pending'",
            (int(alliance_id), int(target["id"])),
        )
        conn.execute(
            """INSERT INTO alliance_visits
               (user_id, alliance_id, is_default, first_visited_at, last_visited_at)
               VALUES (?, ?, 0, ?, ?)
               ON CONFLICT(user_id, alliance_id) DO UPDATE SET last_visited_at=excluded.last_visited_at""",
            (int(target["id"]), int(alliance_id), timestamp, timestamp),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_member_added_by_openid", entity_type="alliance_member",
            entity_id=member_id, details={"role": selected_role}, timestamp=timestamp,
        )
    return {"member_id": member_id, "role": selected_role, "status": "active"}


def set_alliance_member_role(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    member_id: int,
    role: str,
    *,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"leader"})
    selected = str(role or "").strip()
    if selected not in {"member", "admin", "leader"}:
        raise AllianceOperationError("不支持的联盟角色", status_code=422)
    target = conn.execute(
        """SELECT members.*, users.id AS target_user_id
           FROM alliance_members AS members
           JOIN wechat_users AS users ON users.id=members.user_id
           WHERE members.id=? AND members.alliance_id=? AND members.status='active'""",
        (int(member_id), int(alliance_id)),
    ).fetchone()
    if target is None:
        raise AllianceOperationError("联盟成员不存在", status_code=404)
    timestamp = _iso(now)
    with conn:
        if selected == "leader":
            if int(target["user_id"]) == int(actor["user_id"]):
                return {"member_id": int(member_id), "role": "leader"}
            conn.execute(
                """UPDATE alliance_members SET role='admin', updated_at=?
                   WHERE alliance_id=? AND user_id=? AND role='leader' AND status='active'""",
                (timestamp, int(alliance_id), int(actor["user_id"])),
            )
        elif int(target["user_id"]) == int(actor["user_id"]):
            raise AllianceOperationError("首领不能直接降低自己的权限，请先移交首领", status_code=409)
        conn.execute(
            "UPDATE alliance_members SET role=?, updated_at=? WHERE id=?",
            (selected, timestamp, int(member_id)),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_leader_transferred" if selected == "leader" else "alliance_member_role_updated",
            entity_type="alliance_member", entity_id=int(member_id),
            details={"before": target["role"], "after": selected}, timestamp=timestamp,
        )
    return {"member_id": int(member_id), "role": selected}


def remove_alliance_member(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    member_id: int,
    *,
    block: bool = False,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"admin", "leader"})
    target = conn.execute(
        "SELECT * FROM alliance_members WHERE id=? AND alliance_id=? AND status='active'",
        (int(member_id), int(alliance_id)),
    ).fetchone()
    if target is None:
        raise AllianceOperationError("联盟成员不存在", status_code=404)
    if target["role"] == "leader" or int(target["user_id"]) == int(actor["user_id"]):
        raise AllianceOperationError("不能移除联盟首领或自己", status_code=409)
    if actor["role"] == "admin" and target["role"] != "member":
        raise AllianceOperationError("管理员只能移除普通成员", status_code=403)
    timestamp = _iso(now)
    selected = "blocked" if block else "removed"
    with conn:
        conn.execute(
            "UPDATE alliance_members SET status=?, updated_at=? WHERE id=?",
            (selected, timestamp, int(member_id)),
        )
        conn.execute(
            "DELETE FROM alliance_visits WHERE alliance_id=? AND user_id=?",
            (int(alliance_id), int(target["user_id"])),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_member_blocked" if block else "alliance_member_removed",
            entity_type="alliance_member", entity_id=int(member_id),
            details={"previous_role": target["role"]}, timestamp=timestamp,
        )
    return {"member_id": int(member_id), "status": selected}


def leave_alliance(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id)
    if actor["role"] == "leader":
        raise AllianceOperationError("联盟首领请先移交首领后再退出", status_code=409)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliance_members SET status='left', updated_at=? WHERE id=?",
            (timestamp, int(actor["member_id"])),
        )
        conn.execute(
            "DELETE FROM alliance_visits WHERE alliance_id=? AND user_id=?",
            (int(alliance_id), int(actor["user_id"])),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_member_left", entity_type="alliance_member",
            entity_id=int(actor["member_id"]),
            details={"previous_role": actor["role"]}, timestamp=timestamp,
        )
    return {"alliance_id": int(alliance_id), "status": "left"}


def archive_alliance(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    confirmation_name: str,
    *,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id, roles={"leader"})
    if actor["plan_code"] == "internal":
        raise AllianceOperationError("内置联盟不能在小程序中删除", status_code=403)
    if str(confirmation_name or "").strip() != actor["name"]:
        raise AllianceOperationError("请输入完整联盟名称确认删除", status_code=422)
    timestamp = _iso(now)
    with conn:
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_archived", entity_type="alliance",
            entity_id=int(alliance_id), details={"name": actor["name"]}, timestamp=timestamp,
        )
        conn.execute(
            "UPDATE alliance_clans SET status='inactive', updated_at=? WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            "UPDATE alliance_members SET status='left', updated_at=? WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute("DELETE FROM alliance_visits WHERE alliance_id=?", (int(alliance_id),))
        conn.execute(
            "UPDATE alliances SET status='archived', updated_at=? WHERE id=?",
            (timestamp, int(alliance_id)),
        )
    return {"alliance_id": int(alliance_id), "status": "archived"}


def grant_alliance_plan(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    plan_code: str,
    expires_at: str | None,
    note: str = "",
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    if plan_code not in {"free", "paid", "internal"}:
        raise AllianceOperationError("不支持的套餐", status_code=422)
    plan = conn.execute(
        "SELECT max_clans FROM alliance_plans WHERE plan_code=? AND status='active'",
        (plan_code,),
    ).fetchone()
    if plan is None:
        raise AllianceOperationError("套餐不存在或已停用", status_code=404)
    active_clans = int(conn.execute(
        "SELECT COUNT(*) FROM alliance_clans WHERE alliance_id=? AND status='active'",
        (int(alliance_id),),
    ).fetchone()[0])
    if active_clans > int(plan["max_clans"]):
        raise AllianceOperationError("目标套餐容量小于当前有效部落数量", status_code=409)
    current = _now(now)
    timestamp = _iso(current)
    expiry = _parse_time(expires_at)
    if plan_code == "paid" and expiry is None:
        raise AllianceOperationError("付费权益必须设置有效期", status_code=422)
    if plan_code != "paid" and expiry is not None:
        raise AllianceOperationError("仅付费权益支持设置到期时间", status_code=422)
    if expiry is not None and expiry <= current:
        raise AllianceOperationError("套餐到期时间必须晚于当前时间", status_code=422)
    with conn:
        alliance = conn.execute(
            "SELECT plan_code FROM alliances WHERE id=?", (int(alliance_id),),
        ).fetchone()
        if alliance is None:
            raise AllianceOperationError("联盟不存在", status_code=404)
        conn.execute(
            """UPDATE alliance_plan_grants SET status='revoked', updated_at=?
               WHERE alliance_id=? AND status='active'""",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            """INSERT INTO alliance_plan_grants
               (alliance_id, plan_code, status, starts_at, expires_at,
                granted_by_user_id, note, created_at, updated_at)
               VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
            (
                int(alliance_id), plan_code, timestamp, _iso(expiry) if expiry else None,
                actor["id"], note[:500], timestamp, timestamp,
            ),
        )
        conn.execute(
            "UPDATE alliances SET plan_code=?, updated_at=? WHERE id=?",
            (plan_code, timestamp, int(alliance_id)),
        )
        details = {
            "before": alliance["plan_code"], "after": plan_code,
            "expires_at": _iso(expiry) if expiry else None, "note": note[:500],
        }
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["id"]),
            action="alliance_plan_granted", entity_type="alliance_plan",
            entity_id=plan_code, details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="alliance_plan_granted",
            entity_type="alliance", entity_id=int(alliance_id),
            details=details, timestamp=timestamp,
        )
    return {"alliance_id": int(alliance_id), "plan_code": plan_code, "expires_at": _iso(expiry) if expiry else None}


def reconcile_expired_plan_grants(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> dict:
    current = _now(now)
    timestamp = _iso(current)
    downgrade_before = _iso(current - timedelta(days=7))
    rows = conn.execute(
        """SELECT grants.id, grants.alliance_id, grants.plan_code, grants.expires_at
           FROM alliance_plan_grants AS grants
           WHERE grants.status='active' AND grants.plan_code='paid'
             AND grants.expires_at IS NOT NULL
             AND grants.expires_at <= ?
           ORDER BY grants.id""",
        (downgrade_before,),
    ).fetchall()
    expired = 0
    deactivated = 0
    with conn:
        for row in rows:
            conn.execute(
                "UPDATE alliance_plan_grants SET status='expired', updated_at=? WHERE id=?",
                (timestamp, row["id"]),
            )
            # Keep the oldest subscribed clan as the low-frequency free fallback;
            # private subscription rows are retained and public facts are untouched.
            extras = conn.execute(
                """SELECT id FROM alliance_clans
                   WHERE alliance_id=? AND status='active'
                   ORDER BY sort_order, id LIMIT -1 OFFSET 1""",
                (row["alliance_id"],),
            ).fetchall()
            for extra in extras:
                conn.execute(
                    "UPDATE alliance_clans SET status='inactive', updated_at=? WHERE id=?",
                    (timestamp, extra["id"]),
                )
            deactivated += len(extras)
            conn.execute(
                """UPDATE alliances
                   SET plan_code='free', clan_limit_override=NULL, updated_at=?
                   WHERE id=?""",
                (timestamp, row["alliance_id"]),
            )
            conn.execute(
                """INSERT INTO alliance_plan_grants
                   (alliance_id, plan_code, status, starts_at, expires_at,
                    granted_by_user_id, note, created_at, updated_at)
                   VALUES (?, 'free', 'active', ?, NULL, NULL,
                           '付费权益宽限期结束后自动降级', ?, ?)""",
                (row["alliance_id"], timestamp, timestamp, timestamp),
            )
            _alliance_audit(
                conn, alliance_id=int(row["alliance_id"]), actor_user_id=None,
                action="alliance_plan_expired", entity_type="alliance_plan",
                entity_id=row["plan_code"],
                details={
                    "expires_at": row["expires_at"], "grace_days": 7,
                    "downgraded_to": "free", "deactivated_clans": len(extras),
                },
                timestamp=timestamp,
            )
            expired += 1
    return {"expired_grants": expired, "deactivated_clans": deactivated}


def set_alliance_status(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    status: str,
    *,
    note: str = "",
    now: datetime | None = None,
) -> dict:
    actor = require_platform_admin(conn, openid)
    selected = str(status or "").strip()
    if selected not in {"active", "suspended"}:
        raise AllianceOperationError("不支持的联盟状态", status_code=422)
    row = conn.execute(
        "SELECT status FROM alliances WHERE id=?", (int(alliance_id),),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("联盟不存在", status_code=404)
    if row["status"] == "archived":
        raise AllianceOperationError("已删除联盟不能恢复", status_code=409)
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliances SET status=?, updated_at=? WHERE id=?",
            (selected, timestamp, int(alliance_id)),
        )
        details = {"before": row["status"], "after": selected, "note": note[:500]}
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="alliance_status_updated",
            entity_type="alliance", entity_id=int(alliance_id), details=details,
            timestamp=timestamp,
        )
    return {"alliance_id": int(alliance_id), "status": selected}


def archive_suspended_alliance(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    confirmation_name: str,
    *,
    now: datetime | None = None,
) -> dict:
    """由超级管理员软删除已停用联盟，保留历史事实和审计。"""
    actor = require_platform_admin(conn, openid)
    row = conn.execute(
        "SELECT name, status FROM alliances WHERE id=?", (int(alliance_id),),
    ).fetchone()
    if row is None:
        raise AllianceOperationError("联盟不存在", status_code=404)
    if row["status"] != "suspended":
        raise AllianceOperationError("请先停用联盟，再执行删除", status_code=409)
    if str(confirmation_name or "").strip() != row["name"]:
        raise AllianceOperationError("请输入完整联盟名称确认删除", status_code=422)

    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliance_clans SET status='inactive', updated_at=? "
            "WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            "UPDATE alliance_members SET status='left', updated_at=? "
            "WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            "UPDATE alliance_share_links SET status='revoked', updated_at=? "
            "WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            "UPDATE alliance_join_requests SET status='cancelled', updated_at=? "
            "WHERE alliance_id=? AND status='pending'",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            "UPDATE alliance_plan_grants SET status='revoked', updated_at=? "
            "WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute(
            "UPDATE sync_interests SET status='inactive', updated_at=? "
            "WHERE alliance_id=? AND status='active'",
            (timestamp, int(alliance_id)),
        )
        conn.execute("DELETE FROM alliance_visits WHERE alliance_id=?", (int(alliance_id),))
        conn.execute(
            "UPDATE alliances SET status='archived', updated_at=? WHERE id=?",
            (timestamp, int(alliance_id)),
        )
        details = {"before": "suspended", "after": "archived", "name": row["name"]}
        _alliance_audit(
            conn, alliance_id=int(alliance_id), actor_user_id=int(actor["id"]),
            action="alliance_archived_by_platform", entity_type="alliance",
            entity_id=int(alliance_id), details=details, timestamp=timestamp,
        )
        _platform_audit(
            conn, actor_user_id=int(actor["id"]), action="alliance_archived",
            entity_type="alliance", entity_id=int(alliance_id), details=details,
            timestamp=timestamp,
        )
    return {"alliance_id": int(alliance_id), "status": "archived"}


def platform_dashboard(conn: sqlite3.Connection, openid: str, *, search: str = "") -> dict:
    require_platform_admin(conn, openid)
    keyword = f"%{search.strip()}%"
    rows = conn.execute(
        """SELECT alliances.id, alliances.alliance_key, alliances.name, alliances.status,
                  alliances.plan_code, alliances.created_at,
                  COUNT(DISTINCT CASE WHEN members.status='active' THEN members.id END) AS member_count,
                  COUNT(DISTINCT CASE WHEN clans.status='active' THEN clans.id END) AS clan_count,
                  COUNT(DISTINCT CASE
                      WHEN clans.status='active' AND clans.verification_status='verified'
                      THEN clans.id END) AS verified_count,
                  CASE
                    WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                         AND datetime(grants.expires_at) <= datetime('now')
                         AND datetime(grants.expires_at) > datetime('now', '-7 days')
                    THEN 'grace'
                    WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                         AND datetime(grants.expires_at) <= datetime('now', '-7 days')
                    THEN 'expired'
                    ELSE grants.status
                  END AS grant_status,
                  grants.expires_at
           FROM alliances
           LEFT JOIN alliance_members AS members ON members.alliance_id=alliances.id
           LEFT JOIN alliance_clans AS clans ON clans.alliance_id=alliances.id
           LEFT JOIN alliance_plan_grants AS grants
             ON grants.id=(SELECT MAX(g.id) FROM alliance_plan_grants AS g WHERE g.alliance_id=alliances.id)
           WHERE alliances.status != 'archived'
             AND (?='' OR alliances.name LIKE ? OR alliances.alliance_key LIKE ?)
           GROUP BY alliances.id
           ORDER BY CASE alliances.status WHEN 'active' THEN 0 ELSE 1 END, alliances.id DESC
           LIMIT 200""",
        (search.strip(), keyword, keyword),
    ).fetchall()
    queue = {
        f"{row['mode']}:{row['status']}": int(row["count"])
        for row in conn.execute(
            "SELECT mode, status, COUNT(*) AS count FROM sync_tasks GROUP BY mode, status"
        ).fetchall()
    }
    multi_alliance_verifications = [dict(row) for row in conn.execute(
        """SELECT clans.clan_tag, COUNT(DISTINCT clans.alliance_id) AS alliance_count,
                  GROUP_CONCAT(DISTINCT alliances.name) AS alliance_names
           FROM alliance_clans AS clans
           JOIN alliances ON alliances.id=clans.alliance_id AND alliances.status='active'
           WHERE clans.status='active' AND clans.verification_status='verified'
           GROUP BY clans.clan_tag HAVING COUNT(DISTINCT clans.alliance_id) > 1
           ORDER BY clans.clan_tag"""
    ).fetchall()]
    return {
        "settings": free_registration_policy(conn),
        "alliances": [dict(row) for row in rows],
        "queue": queue,
        # 旧字段保留给已发布的小程序；新版使用符合当前业务语义的新字段。
        "verification_conflicts": multi_alliance_verifications,
        "multi_alliance_verifications": multi_alliance_verifications,
        "audit": [dict(row) for row in conn.execute(
            """SELECT action, entity_type, entity_id, created_at
               FROM platform_audit_events ORDER BY id DESC LIMIT 50"""
        ).fetchall()],
    }


def platform_alliance_detail(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
) -> dict:
    require_platform_admin(conn, openid)
    alliance = conn.execute(
        """SELECT alliances.id, alliances.alliance_key, alliances.name,
                  alliances.status, alliances.plan_code, alliances.created_at,
                  CASE
                    WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                         AND datetime(grants.expires_at) <= datetime('now')
                         AND datetime(grants.expires_at) > datetime('now', '-7 days')
                    THEN 'grace'
                    WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                         AND datetime(grants.expires_at) <= datetime('now', '-7 days')
                    THEN 'expired'
                    ELSE grants.status
                  END AS grant_status,
                  grants.starts_at,
                  grants.expires_at, grants.note AS grant_note
           FROM alliances
           LEFT JOIN alliance_plan_grants AS grants
             ON grants.id=(SELECT MAX(g.id) FROM alliance_plan_grants AS g
                           WHERE g.alliance_id=alliances.id)
           WHERE alliances.id=?""",
        (int(alliance_id),),
    ).fetchone()
    if alliance is None:
        raise AllianceOperationError("联盟不存在", status_code=404)
    clans = [dict(row) for row in conn.execute(
        """SELECT id, clan_tag, clan_name, category, status,
                  verification_status, verified_at
           FROM alliance_clans WHERE alliance_id=? ORDER BY sort_order, id""",
        (int(alliance_id),),
    ).fetchall()]
    members = [dict(row) for row in conn.execute(
        """SELECT members.id, members.role, members.status, members.joined_at,
                  users.openid, users.nickname, users.account_name, users.player_tag
           FROM alliance_members AS members
           JOIN wechat_users AS users ON users.id=members.user_id
           WHERE members.alliance_id=?
           ORDER BY members.id""",
        (int(alliance_id),),
    ).fetchall()]
    audits = [dict(row) for row in conn.execute(
        """SELECT action, entity_type, entity_id, details_json, created_at
           FROM alliance_audit_events WHERE alliance_id=? ORDER BY id DESC LIMIT 100""",
        (int(alliance_id),),
    ).fetchall()]
    return {"alliance": dict(alliance), "clans": clans, "members": members, "audit": audits}
