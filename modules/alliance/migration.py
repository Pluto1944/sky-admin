"""M1 苍穹联盟租户化的纯清单与幂等写入逻辑。

迁移期仍以 ``config/settings.yaml`` 为现有业务的权威来源。本模块只建立
联盟侧映射，不参与 API 授权，也不改变旧调度器的部落范围。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

from modules.coc_sync.official.mapper import normalize_tag


SKY_ALLIANCE_KEY = "sky-internal"
SKY_ALLIANCE_NAME = "苍穹联盟"
_VALID_ROLES = {"member", "admin", "leader"}

_PLAN_ROWS = (
    {
        "plan_code": "free",
        "display_name": "免费联盟",
        "max_clans": 1,
        "sync_tier": "low",
        "entitlements": {
            "history_scope": "full",
            "manual_refresh": True,
            "max_cwl_teams": 1,
            "cwl_data": True,
            "cwl_registration": False,
        },
    },
    {
        "plan_code": "paid",
        "display_name": "付费联盟",
        "max_clans": 10,
        "sync_tier": "high",
        "entitlements": {
            "history_scope": "full",
            "automatic_refresh": True,
            "max_cwl_teams": 20,
            "cwl_data": True,
            "cwl_registration": False,
        },
    },
    {
        "plan_code": "internal",
        "display_name": "内部联盟",
        "max_clans": 100,
        "sync_tier": "internal",
        "entitlements": {
            "history_scope": "full",
            "automatic_refresh": True,
            "max_cwl_teams": 100,
            "cwl_data": True,
            "cwl_registration": True,
            "registration_source": "tencent_docs",
        },
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_sky_manifest(clans: Iterable[Mapping[str, object]]) -> dict:
    """从现有配置生成稳定、可比较的苍穹联盟映射清单。"""
    enabled = []
    seen: set[str] = set()
    for configured in clans:
        if not configured.get("enabled", True):
            continue
        tag = normalize_tag(str(configured.get("tag") or ""))
        if not tag:
            raise ValueError("enabled clan is missing a valid tag")
        if tag in seen:
            raise ValueError(f"duplicate enabled clan tag: {tag}")
        seen.add(tag)
        category = str(configured.get("category") or "normal")
        if category not in {"combat", "normal", "farm", "flat", "other"}:
            raise ValueError(f"unsupported clan category for {tag}: {category}")
        enabled.append(
            {
                "clan_tag": tag,
                "clan_name": str(configured.get("name") or tag),
                "category": category,
                "sort_order": len(enabled),
                "verification_status": "verified",
            }
        )
    manifest = {
        "alliance_key": SKY_ALLIANCE_KEY,
        "alliance_name": SKY_ALLIANCE_NAME,
        "plan_code": "internal",
        "clans": enabled,
    }
    manifest["config_hash"] = _digest(manifest)
    return manifest


def validate_member_assignments(
    conn: sqlite3.Connection,
    assignments: Sequence[Mapping[str, object]],
) -> list[dict]:
    """校验人工确认的用户角色，不从遗留全局角色自动推断。"""
    normalized: list[dict] = []
    seen: set[int] = set()
    leaders = 0
    for item in assignments:
        try:
            user_id = int(item["user_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("each member assignment requires an integer user_id") from exc
        role = str(item.get("role") or "member")
        if role not in _VALID_ROLES:
            raise ValueError(f"unsupported alliance role for user {user_id}: {role}")
        if user_id in seen:
            raise ValueError(f"duplicate member assignment for user {user_id}")
        if conn.execute("SELECT 1 FROM wechat_users WHERE id = ?", (user_id,)).fetchone() is None:
            raise ValueError(f"wechat user does not exist: {user_id}")
        seen.add(user_id)
        leaders += role == "leader"
        normalized.append({"user_id": user_id, "role": role})
    if leaders > 1:
        raise ValueError("an alliance can have at most one active leader")
    return sorted(normalized, key=lambda item: item["user_id"])


def build_existing_user_assignments(
    conn: sqlite3.Connection,
    overrides: Sequence[Mapping[str, object]] = (),
) -> list[dict]:
    """将 M1 上线前已有微信用户默认映射为苍穹管理员。

    这是一次性的兼容迁移规则，用于保持现有苍穹用户的可见范围。角色文件可将
    指定用户改为 member/admin/leader；M1 之后新加入联盟的用户不走此规则。
    """
    merged = {
        int(row[0]): {"user_id": int(row[0]), "role": "admin"}
        for row in conn.execute("SELECT id FROM wechat_users ORDER BY id")
    }
    for override in overrides:
        try:
            merged[int(override["user_id"])] = dict(override)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("each member override requires an integer user_id") from exc
    return validate_member_assignments(conn, list(merged.values()))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def preview_sky_migration(
    conn: sqlite3.Connection,
    clans: Iterable[Mapping[str, object]],
    member_assignments: Sequence[Mapping[str, object]] = (),
) -> dict:
    """只读比较配置和联盟映射，返回不含 openid/昵称的迁移摘要。"""
    manifest = build_sky_manifest(clans)
    assignments = validate_member_assignments(conn, member_assignments)
    legacy_roles = {
        str(row[0] or "<null>"): int(row[1])
        for row in conn.execute(
            "SELECT role, COUNT(*) FROM wechat_users GROUP BY role ORDER BY role"
        )
    }
    current_clans: list[dict] = []
    current_members: list[dict] = []
    alliance_id = None
    if _table_exists(conn, "alliances"):
        alliance = conn.execute(
            "SELECT id FROM alliances WHERE alliance_key = ?", (SKY_ALLIANCE_KEY,)
        ).fetchone()
        if alliance:
            alliance_id = int(alliance[0])
            current_clans = [
                dict(row)
                for row in conn.execute(
                    """SELECT clan_tag, clan_name, category, sort_order, status,
                              verification_status
                       FROM alliance_clans WHERE alliance_id = ? ORDER BY sort_order, clan_tag""",
                    (alliance_id,),
                )
            ]
            current_members = [
                dict(row)
                for row in conn.execute(
                    """SELECT user_id, role, status FROM alliance_members
                       WHERE alliance_id = ? ORDER BY user_id""",
                    (alliance_id,),
                )
            ]
    target_by_tag = {item["clan_tag"]: item for item in manifest["clans"]}
    current_active_by_tag = {
        item["clan_tag"]: item for item in current_clans if item["status"] == "active"
    }
    current_member_by_user = {item["user_id"]: item for item in current_members}
    changed = [
        tag
        for tag, target in target_by_tag.items()
        if tag not in current_active_by_tag
        or any(
            current_active_by_tag[tag].get(key) != target[key]
            for key in ("clan_name", "category", "sort_order", "verification_status")
        )
    ]
    removed = sorted(set(current_active_by_tag) - set(target_by_tag))
    member_changes = [
        item
        for item in assignments
        if item["user_id"] not in current_member_by_user
        or current_member_by_user[item["user_id"]]["role"] != item["role"]
        or current_member_by_user[item["user_id"]]["status"] != "active"
    ]
    return {
        "mode": "preview",
        "alliance": {
            "alliance_key": SKY_ALLIANCE_KEY,
            "exists": alliance_id is not None,
            "plan_code": "internal",
        },
        "config": {
            "hash": manifest["config_hash"],
            "enabled_clan_count": len(manifest["clans"]),
            "clan_tags": [item["clan_tag"] for item in manifest["clans"]],
        },
        "changes": {
            "clans_to_insert_or_update": changed,
            "config_clans_to_deactivate": removed,
            "member_assignments_to_apply": len(member_changes),
        },
        "current": {
            "active_clan_count": len(current_active_by_tag),
            "membership_count": len(current_members),
        },
        "legacy_wechat_users": {
            "total": sum(legacy_roles.values()),
            "roles": legacy_roles,
            "legacy_role_inference_used": False,
            "target_roles": dict(Counter(item["role"] for item in assignments)),
        },
        "warnings": [
            "wechat_users.role is legacy global state and is not used to grant alliance roles",
            (
                "membership roles come from the migration assignments, not legacy global roles"
                if assignments
                else "no user membership is written unless assignments are explicitly supplied"
            ),
            "existing API, frontend and scheduler continue to use the legacy configuration",
        ],
    }


def apply_sky_migration(
    conn: sqlite3.Connection,
    clans: Iterable[Mapping[str, object]],
    member_assignments: Sequence[Mapping[str, object]] = (),
    *,
    now: str | None = None,
) -> dict:
    """在一个事务中幂等写入套餐、苍穹联盟、部落与显式成员关系。"""
    timestamp = now or _utc_now()
    manifest = build_sky_manifest(clans)
    assignments = validate_member_assignments(conn, member_assignments)
    with conn:
        for plan in _PLAN_ROWS:
            conn.execute(
                """INSERT INTO alliance_plans
                       (plan_code, display_name, max_clans, sync_tier,
                        entitlements_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                   ON CONFLICT(plan_code) DO UPDATE SET
                       display_name = excluded.display_name,
                       max_clans = excluded.max_clans,
                       sync_tier = excluded.sync_tier,
                       entitlements_json = excluded.entitlements_json,
                       status = 'active',
                       updated_at = excluded.updated_at""",
                (
                    plan["plan_code"], plan["display_name"], plan["max_clans"],
                    plan["sync_tier"], _canonical_json(plan["entitlements"]),
                    timestamp, timestamp,
                ),
            )
        conn.execute(
            """INSERT INTO alliances
                   (alliance_key, name, status, plan_code, creation_source,
                    created_at, updated_at)
               VALUES (?, ?, 'active', 'internal', 'migration', ?, ?)
               ON CONFLICT(alliance_key) DO UPDATE SET
                   name = excluded.name,
                   status = 'active',
                   plan_code = 'internal',
                   creation_source = 'migration',
                   updated_at = excluded.updated_at""",
            (SKY_ALLIANCE_KEY, SKY_ALLIANCE_NAME, timestamp, timestamp),
        )
        alliance_id = int(
            conn.execute(
                "SELECT id FROM alliances WHERE alliance_key = ?", (SKY_ALLIANCE_KEY,)
            ).fetchone()[0]
        )
        configured_tags = []
        for clan in manifest["clans"]:
            configured_tags.append(clan["clan_tag"])
            conn.execute(
                """INSERT INTO alliance_clans
                       (alliance_id, clan_tag, clan_name, category, sort_order, status,
                        verification_status, verified_at, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', 'verified', ?,
                           'config_migration', ?, ?)
                   ON CONFLICT(alliance_id, clan_tag) DO UPDATE SET
                       clan_name = excluded.clan_name,
                       category = excluded.category,
                       sort_order = excluded.sort_order,
                       status = 'active',
                       verification_status = 'verified',
                       verified_at = COALESCE(alliance_clans.verified_at, excluded.verified_at),
                       source = 'config_migration',
                       updated_at = excluded.updated_at""",
                (
                    alliance_id, clan["clan_tag"], clan["clan_name"],
                    clan["category"], clan["sort_order"], timestamp, timestamp, timestamp,
                ),
            )
        if configured_tags:
            placeholders = ",".join("?" for _ in configured_tags)
            conn.execute(
                f"""UPDATE alliance_clans SET status = 'inactive', updated_at = ?
                    WHERE alliance_id = ? AND source = 'config_migration'
                      AND status = 'active' AND clan_tag NOT IN ({placeholders})""",
                (timestamp, alliance_id, *configured_tags),
            )
        else:
            conn.execute(
                """UPDATE alliance_clans SET status = 'inactive', updated_at = ?
                   WHERE alliance_id = ? AND source = 'config_migration' AND status = 'active'""",
                (timestamp, alliance_id),
            )
        for member in assignments:
            conn.execute(
                """INSERT INTO alliance_members
                       (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
                   VALUES (?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(alliance_id, user_id) DO UPDATE SET
                       role = excluded.role,
                       status = 'active',
                       joined_at = COALESCE(alliance_members.joined_at, excluded.joined_at),
                       updated_at = excluded.updated_at""",
                (
                    alliance_id, member["user_id"], member["role"],
                    timestamp, timestamp, timestamp,
                ),
            )
        audit_payload = {
            "config_hash": manifest["config_hash"],
            "clan_count": len(manifest["clans"]),
            "member_assignments": assignments,
        }
        conn.execute(
            """INSERT OR IGNORE INTO alliance_audit_events
                   (event_key, alliance_id, action, entity_type, entity_id,
                    details_json, created_at)
               VALUES (?, ?, 'm1_sky_migration', 'alliance', ?, ?, ?)""",
            (
                "m1-sky-" + _digest(audit_payload), alliance_id,
                SKY_ALLIANCE_KEY, _canonical_json(audit_payload), timestamp,
            ),
        )
    result = preview_sky_migration(conn, clans, assignments)
    result["mode"] = "applied"
    result["alliance"]["id"] = alliance_id
    result["applied_members_by_role"] = dict(Counter(item["role"] for item in assignments))
    return result
