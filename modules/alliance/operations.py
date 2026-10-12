"""M6-M9 alliance membership, sharing, manual verification and plan operations.

The first production version deliberately does not implement self-service clan
verification.  A platform operator verifies a clan manually; the user-facing
button remains an informational entry point.  Public COC facts are never
deleted by lifecycle operations in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
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


def _env_values(name: str) -> set[str]:
    return {item.strip() for item in os.getenv(name, "").split(",") if item.strip()}


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
    allowlist = _env_values("ALLIANCE_PLATFORM_ADMIN_OPENIDS")
    # M5's internal tester remains the bootstrap operator until the dedicated
    # allowlist/table is configured.  Neither allowlist is exposed by an API.
    bootstrap = _env_values("M5_FREE_ALLIANCE_OPENIDS")
    allowed = bool(row and (row["db_admin"] or openid in allowlist or openid in bootstrap))
    return {"allowed": allowed}


def require_platform_admin(conn: sqlite3.Connection, openid: str) -> sqlite3.Row:
    user = _user(conn, openid)
    if not platform_admin_capability(conn, openid)["allowed"]:
        raise AllianceOperationError("仅平台管理员可以执行此操作", status_code=403)
    return user


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
        "SELECT COUNT(*) FROM alliances WHERE plan_code='free' AND status='active'"
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
    now: datetime | None = None,
) -> sqlite3.Row:
    actor = _member(conn, openid, alliance_id, roles={"admin", "leader"})
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
    return actor


def list_managed_clans(conn: sqlite3.Connection, openid: str, alliance_id: int) -> dict:
    member = _member(conn, openid, alliance_id)
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
    can_manage = member["role"] in {"admin", "leader"} and plan_allows_management
    return {
        "alliance_id": int(alliance_id), "actor_role": member["role"],
        "plan_code": plan["plan_code"] if plan else member["plan_code"],
        "max_clans": int(plan["max_clans"]) if plan else 1,
        "active_count": active_count,
        "can_manage": bool(can_manage),
        "can_add": bool(can_manage and active_count < (int(plan["max_clans"]) if plan else 1)),
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
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(conn, openid, alliance_id, now=now)
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
    try:
        with conn:
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
                if existing["status"] == "active":
                    raise AllianceOperationError("该部落已在当前联盟中", status_code=409)
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
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(conn, openid, alliance_id, now=now)
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
    timestamp = _iso(now)
    with conn:
        conn.execute(
            "UPDATE alliance_clans SET category=?, updated_at=? WHERE id=?",
            (selected_category, timestamp, row["id"]),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="managed_clan_category_updated", entity_type="alliance_clan", entity_id=tag,
            details={"before": row["category"], "after": selected_category}, timestamp=timestamp,
        )
    return {
        "clan_tag": tag, "clan_name": row["clan_name"], "category": selected_category,
        "verification_status": row["verification_status"], "status": "active",
    }


def reorder_managed_clans(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tags: list[str],
    *,
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(conn, openid, alliance_id, now=now)
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
    return {"clan_tags": tags}


def remove_managed_clan(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    clan_tag: str,
    *,
    now: datetime | None = None,
) -> dict:
    actor = _managed_clan_actor(conn, openid, alliance_id, now=now)
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
    if selected == "verified":
        conflict = conn.execute(
            """SELECT alliances.id, alliances.name
               FROM alliance_clans AS clans
               JOIN alliances ON alliances.id=clans.alliance_id
               WHERE clans.clan_tag=? AND clans.verification_status='verified'
                 AND clans.status='active' AND alliances.status='active'
                 AND alliances.id != ?
               ORDER BY alliances.id LIMIT 1""",
            (tag, int(alliance_id)),
        ).fetchone()
        if conflict is not None:
            raise AllianceOperationError(
                f"该部落已由联盟“{conflict['name']}”认证，请先人工处理冲突",
                status_code=409,
            )
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
        details = {"before": row["verification_status"], "after": selected, "note": note[:500]}
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
    }


def create_share_link(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
    *,
    expires_days: int = 30,
    now: datetime | None = None,
) -> dict:
    actor = _member(conn, openid, alliance_id)
    days = int(expires_days)
    if days < 1 or days > 30:
        raise AllianceOperationError("分享有效期必须在 1 到 30 天之间", status_code=422)
    current = _now(now)
    timestamp = _iso(current)
    expires_at = _iso(current + timedelta(days=days))
    active_links = int(conn.execute(
        """SELECT COUNT(*) FROM alliance_share_links
           WHERE alliance_id=? AND status='active' AND expires_at>?""",
        (int(alliance_id), timestamp),
    ).fetchone()[0])
    if active_links >= 5:
        raise AllianceOperationError("当前联盟最多保留 5 个有效邀请，请先撤销旧邀请", status_code=409)
    raw_token = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with conn:
        cursor = conn.execute(
            """INSERT INTO alliance_share_links
               (token_hash, alliance_id, created_by_user_id, visibility, status,
                expires_at, created_at, updated_at)
               VALUES (?, ?, ?, 'member', 'active', ?, ?, ?)""",
            (digest, int(alliance_id), actor["user_id"], expires_at, timestamp, timestamp),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_share_created", entity_type="alliance_share_link",
            entity_id=int(cursor.lastrowid), details={"expires_at": expires_at},
            timestamp=timestamp,
        )
    return {"token": raw_token, "expires_at": expires_at, "alliance_id": int(alliance_id)}


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
        "expires_at": row["expires_at"], "can_join": True,
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
        active_memberships = int(conn.execute(
            "SELECT COUNT(*) FROM alliance_members WHERE user_id=? AND status='active'",
            (user["id"],),
        ).fetchone()[0])
        if active_memberships >= 50:
            raise AllianceOperationError("当前账号加入的联盟数量已达上限", status_code=409)
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
        """SELECT id, created_by_user_id, status, expires_at, use_count,
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
            "UPDATE alliance_visits SET is_default=0 WHERE alliance_id=? AND user_id=?",
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
            "UPDATE alliance_visits SET is_default=0 WHERE alliance_id=? AND user_id=?",
            (int(alliance_id), int(actor["user_id"])),
        )
        _alliance_audit(
            conn, alliance_id=alliance_id, actor_user_id=int(actor["user_id"]),
            action="alliance_member_left", entity_type="alliance_member",
            entity_id=int(actor["member_id"]),
            details={"previous_role": actor["role"]}, timestamp=timestamp,
        )
    return {"alliance_id": int(alliance_id), "status": "left"}


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
    rows = conn.execute(
        """SELECT grants.id, grants.alliance_id, grants.plan_code, grants.expires_at
           FROM alliance_plan_grants AS grants
           WHERE grants.status='active' AND grants.plan_code='paid'
             AND grants.expires_at IS NOT NULL
             AND grants.expires_at <= ?
           ORDER BY grants.id""",
        (timestamp,),
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
            _alliance_audit(
                conn, alliance_id=int(row["alliance_id"]), actor_user_id=None,
                action="alliance_plan_expired", entity_type="alliance_plan",
                entity_id=row["plan_code"],
                details={"expires_at": row["expires_at"], "deactivated_clans": len(extras)},
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
    if selected not in {"active", "suspended", "archived"}:
        raise AllianceOperationError("不支持的联盟状态", status_code=422)
    row = conn.execute("SELECT status FROM alliances WHERE id=?", (int(alliance_id),)).fetchone()
    if row is None:
        raise AllianceOperationError("联盟不存在", status_code=404)
    if selected == "active":
        conflict = conn.execute(
            """SELECT mine.clan_tag, other_alliances.name
               FROM alliance_clans AS mine
               JOIN alliance_clans AS other
                 ON other.clan_tag=mine.clan_tag
                AND other.alliance_id != mine.alliance_id
                AND other.status='active'
                AND other.verification_status='verified'
               JOIN alliances AS other_alliances
                 ON other_alliances.id=other.alliance_id
                AND other_alliances.status='active'
               WHERE mine.alliance_id=? AND mine.status='active'
                 AND mine.verification_status='verified'
               ORDER BY mine.id LIMIT 1""",
            (int(alliance_id),),
        ).fetchone()
        if conflict is not None:
            raise AllianceOperationError(
                f"部落 {conflict['clan_tag']} 已由联盟“{conflict['name']}”认证，请先处理认证冲突",
                status_code=409,
            )
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
                  CASE WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                              AND datetime(grants.expires_at) <= datetime('now')
                       THEN 'expired' ELSE grants.status END AS grant_status,
                  grants.expires_at
           FROM alliances
           LEFT JOIN alliance_members AS members ON members.alliance_id=alliances.id
           LEFT JOIN alliance_clans AS clans ON clans.alliance_id=alliances.id
           LEFT JOIN alliance_plan_grants AS grants
             ON grants.id=(SELECT MAX(g.id) FROM alliance_plan_grants AS g WHERE g.alliance_id=alliances.id)
           WHERE (?='' OR alliances.name LIKE ? OR alliances.alliance_key LIKE ?)
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
    conflicts = [dict(row) for row in conn.execute(
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
        "verification_conflicts": conflicts,
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
                  CASE WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                              AND datetime(grants.expires_at) <= datetime('now')
                       THEN 'expired' ELSE grants.status END AS grant_status,
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
                  users.nickname, users.account_name, users.player_tag
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
