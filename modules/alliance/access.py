"""联盟上下文与权限判定。

JWT 只提供 ``openid`` 身份；本模块每次从数据库读取联盟、成员关系、套餐和
逐部落认证状态。访问记录不授予成员资格，未认证部落中的管理员权限封顶为
普通成员。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from modules.coc_sync.official.mapper import normalize_tag

from .migration import SKY_ALLIANCE_KEY


ROLE_LABELS = {
    "visitor": "浏览",
    "member": "成员",
    "admin": "管理",
    "leader": "首领",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@dataclass(frozen=True)
class AllianceClanAccess:
    id: int
    clan_tag: str
    clan_name: str
    category: str
    sort_order: int
    verification_status: str
    effective_access: str

    @property
    def management_allowed(self) -> bool:
        return self.effective_access == "management"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "clan_tag": self.clan_tag,
            "clan_name": self.clan_name,
            "category": self.category,
            "sort_order": self.sort_order,
            "verification_status": self.verification_status,
            "effective_access": self.effective_access,
        }


@dataclass(frozen=True)
class AllianceContext:
    user_id: int
    openid: str
    alliance_id: int
    alliance_key: str
    alliance_name: str
    role: str
    plan_code: str
    plan_name: str
    sync_tier: str
    max_clans: int
    entitlements: dict
    entitlement_status: str
    entitlement_expires_at: str | None
    clans: tuple[AllianceClanAccess, ...]

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def clan_tags(self) -> frozenset[str]:
        return frozenset(clan.clan_tag for clan in self.clans)

    def clan(self, clan_tag: str) -> AllianceClanAccess | None:
        normalized = normalize_tag(clan_tag)
        return next((item for item in self.clans if item.clan_tag == normalized), None)

    def as_dict(self, *, include_clans: bool = True) -> dict:
        verified_count = sum(
            1 for clan in self.clans if clan.verification_status == "verified"
        )
        if self.clans and verified_count == len(self.clans):
            verification_status = "verified"
        elif verified_count:
            verification_status = "partial"
        else:
            verification_status = "unverified"
        result = {
            "id": self.alliance_id,
            "key": self.alliance_key,
            "name": self.alliance_name,
            "role": self.role,
            "role_label": self.role_label,
            "plan": {
                "code": self.plan_code,
                "name": self.plan_name,
                "sync_tier": self.sync_tier,
                "max_clans": self.max_clans,
                "entitlements": self.entitlements,
                "status": self.entitlement_status,
                "expires_at": self.entitlement_expires_at,
            },
            "clan_count": len(self.clans),
            "verified_clan_count": verified_count,
            "verification_status": verification_status,
            "has_management_access": any(clan.management_allowed for clan in self.clans),
        }
        if include_clans:
            result["clans"] = [clan.as_dict() for clan in self.clans]
        return result


def ensure_sky_admin_membership(
    conn: sqlite3.Connection,
    openid: str,
    *,
    now: str | None = None,
) -> bool:
    """为新出现的苍穹用户补一条管理员关系，存在记录时绝不覆盖。

    该兼容规则只作用于固定 ``sky-internal``。若用户曾被降级、移除或封禁，
    ``UNIQUE(alliance_id, user_id)`` 会令插入无效，因此不会被自动提权或恢复。
    数据库尚未执行 M1 映射时安全跳过，不影响遗留登录。
    """
    timestamp = now or _utc_now()
    row = conn.execute(
        """SELECT users.id AS user_id, alliances.id AS alliance_id
           FROM wechat_users AS users
           JOIN alliances ON alliances.alliance_key = ? AND alliances.status = 'active'
           WHERE users.openid = ?""",
        (SKY_ALLIANCE_KEY, openid),
    ).fetchone()
    if row is None:
        return False

    cursor = conn.execute(
        """INSERT OR IGNORE INTO alliance_members
           (alliance_id, user_id, role, status, joined_at, created_at, updated_at)
           VALUES (?, ?, 'admin', 'active', ?, ?, ?)""",
        (row["alliance_id"], row["user_id"], timestamp, timestamp, timestamp),
    )
    membership = conn.execute(
        """SELECT status FROM alliance_members
           WHERE alliance_id = ? AND user_id = ?""",
        (row["alliance_id"], row["user_id"]),
    ).fetchone()
    if membership is not None and membership["status"] == "active":
        has_default = conn.execute(
            "SELECT 1 FROM alliance_visits WHERE user_id = ? AND is_default = 1",
            (row["user_id"],),
        ).fetchone()
        conn.execute(
            """INSERT INTO alliance_visits
               (alliance_id, user_id, is_default, first_visited_at, last_visited_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(alliance_id, user_id) DO UPDATE SET
                   last_visited_at = excluded.last_visited_at""",
            (
                row["alliance_id"], row["user_id"],
                0 if has_default else 1, timestamp, timestamp,
            ),
        )
    if cursor.rowcount:
        conn.execute(
            """INSERT OR IGNORE INTO alliance_audit_events
               (event_key, alliance_id, actor_user_id, action, entity_type,
                entity_id, details_json, created_at)
               VALUES (?, ?, ?, 'sky_auto_admin_join', 'alliance_member', ?, ?, ?)""",
            (
                f"sky-auto-admin-user-{row['user_id']}",
                row["alliance_id"], row["user_id"], str(row["user_id"]),
                json.dumps({"source": "wechat_login"}, ensure_ascii=False), timestamp,
            ),
        )
    conn.commit()
    return bool(cursor.rowcount)


def _context_rows(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int | None = None,
) -> list[sqlite3.Row]:
    params: list[object] = [openid]
    selected = ""
    if alliance_id is not None:
        selected = " AND alliances.id = ?"
        params.append(alliance_id)
    return conn.execute(
        f"""SELECT users.id AS user_id, users.openid,
                   alliances.id AS alliance_id, alliances.alliance_key,
                   alliances.name AS alliance_name, members.role,
                   plans.plan_code, plans.display_name AS plan_name,
                   CASE
                     WHEN alliances.plan_code='paid' AND grants.id IS NOT NULL
                      AND (grants.status!='active' OR
                           (grants.expires_at IS NOT NULL AND
                            datetime(grants.expires_at) <= datetime('now', '-7 days')))
                     THEN 'low' ELSE plans.sync_tier
                   END AS sync_tier,
                   plans.max_clans, plans.entitlements_json,
                   CASE
                     WHEN grants.id IS NULL THEN
                       CASE WHEN alliances.plan_code='paid' THEN 'legacy' ELSE 'active' END
                     WHEN grants.status='active' AND
                          (grants.expires_at IS NULL OR datetime(grants.expires_at) > datetime('now'))
                     THEN 'active'
                     WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                          AND datetime(grants.expires_at) > datetime('now', '-7 days')
                     THEN 'grace'
                     WHEN grants.status='revoked' THEN 'revoked'
                     ELSE 'expired'
                   END AS entitlement_status,
                   grants.expires_at AS entitlement_expires_at
            FROM wechat_users AS users
            JOIN alliance_members AS members
              ON members.user_id = users.id AND members.status = 'active'
            JOIN alliances
              ON alliances.id = members.alliance_id AND alliances.status = 'active'
            JOIN alliance_plans AS plans
              ON plans.plan_code = alliances.plan_code AND plans.status = 'active'
            LEFT JOIN alliance_plan_grants AS grants
              ON grants.id=(SELECT MAX(g.id) FROM alliance_plan_grants AS g
                            WHERE g.alliance_id=alliances.id)
            WHERE users.openid = ?{selected}
            ORDER BY CASE members.role
                         WHEN 'leader' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                     alliances.name, alliances.id""",
        params,
    ).fetchall()


def _clans_for_context(
    conn: sqlite3.Connection,
    alliance_id: int,
    role: str,
) -> tuple[AllianceClanAccess, ...]:
    rows = conn.execute(
        """SELECT id, clan_tag, clan_name, category, sort_order,
                  verification_status
           FROM alliance_clans
           WHERE alliance_id = ? AND status = 'active'
           ORDER BY sort_order, id""",
        (alliance_id,),
    ).fetchall()
    result = []
    for row in rows:
        verification = row["verification_status"]
        effective = (
            "management"
            if role in {"admin", "leader"} and verification == "verified"
            else "member"
        )
        result.append(
            AllianceClanAccess(
                id=int(row["id"]),
                clan_tag=normalize_tag(row["clan_tag"]),
                clan_name=row["clan_name"] or normalize_tag(row["clan_tag"]),
                category=row["category"],
                sort_order=int(row["sort_order"]),
                verification_status=verification,
                effective_access=effective,
            )
        )
    return tuple(result)


def _build_context(conn: sqlite3.Connection, row: sqlite3.Row) -> AllianceContext:
    role = row["role"]
    alliance_id = int(row["alliance_id"])
    return AllianceContext(
        user_id=int(row["user_id"]),
        openid=row["openid"],
        alliance_id=alliance_id,
        alliance_key=row["alliance_key"],
        alliance_name=row["alliance_name"],
        role=role,
        plan_code=row["plan_code"],
        plan_name=row["plan_name"],
        sync_tier=row["sync_tier"],
        max_clans=int(row["max_clans"]),
        entitlements=_load_json(row["entitlements_json"]),
        entitlement_status=row["entitlement_status"],
        entitlement_expires_at=row["entitlement_expires_at"],
        clans=_clans_for_context(conn, alliance_id, role),
    )


def resolve_alliance_public_context(
    conn: sqlite3.Connection,
    alliance_id: int,
    *,
    management: bool = False,
    openid: str = "",
) -> AllianceContext | None:
    """构建只读访客上下文。

    普通分享和无成员关系的历史访问按 member 数据边界组装；
    超级管理员读取时可显式跳过逐部落认证限制。
    """
    row = conn.execute(
        """SELECT alliances.id AS alliance_id, alliances.alliance_key,
                  alliances.name AS alliance_name, plans.plan_code,
                  plans.display_name AS plan_name,
                  CASE
                    WHEN alliances.plan_code='paid' AND grants.id IS NOT NULL
                     AND (grants.status!='active' OR
                          (grants.expires_at IS NOT NULL AND
                           datetime(grants.expires_at) <= datetime('now', '-7 days')))
                    THEN 'low' ELSE plans.sync_tier
                  END AS sync_tier,
                  plans.max_clans, plans.entitlements_json,
                  CASE
                    WHEN grants.id IS NULL THEN
                      CASE WHEN alliances.plan_code='paid' THEN 'legacy' ELSE 'active' END
                    WHEN grants.status='active' AND
                         (grants.expires_at IS NULL OR datetime(grants.expires_at) > datetime('now'))
                    THEN 'active'
                    WHEN grants.status='active' AND grants.expires_at IS NOT NULL
                         AND datetime(grants.expires_at) > datetime('now', '-7 days')
                    THEN 'grace'
                    WHEN grants.status='revoked' THEN 'revoked'
                    ELSE 'expired'
                  END AS entitlement_status,
                  grants.expires_at AS entitlement_expires_at
           FROM alliances
           JOIN alliance_plans AS plans
             ON plans.plan_code=alliances.plan_code AND plans.status='active'
           LEFT JOIN alliance_plan_grants AS grants
             ON grants.id=(SELECT MAX(g.id) FROM alliance_plan_grants AS g
                           WHERE g.alliance_id=alliances.id)
           WHERE alliances.id=? AND alliances.status='active'""",
        (int(alliance_id),),
    ).fetchone()
    if row is None:
        return None
    role = "leader" if management else "visitor"
    clans = _clans_for_context(conn, int(alliance_id), "leader" if management else "member")
    if management:
        clans = tuple(
            AllianceClanAccess(
                id=item.id, clan_tag=item.clan_tag, clan_name=item.clan_name,
                category=item.category, sort_order=item.sort_order,
                verification_status=item.verification_status,
                effective_access="management",
            )
            for item in clans
        )
    return AllianceContext(
        user_id=0,
        openid=openid,
        alliance_id=int(row["alliance_id"]),
        alliance_key=row["alliance_key"],
        alliance_name=row["alliance_name"],
        role=role,
        plan_code=row["plan_code"],
        plan_name=row["plan_name"],
        sync_tier=row["sync_tier"],
        max_clans=int(row["max_clans"]),
        entitlements=_load_json(row["entitlements_json"]),
        entitlement_status=row["entitlement_status"],
        entitlement_expires_at=row["entitlement_expires_at"],
        clans=clans,
    )


def list_alliance_contexts(conn: sqlite3.Connection, openid: str) -> list[AllianceContext]:
    return [_build_context(conn, row) for row in _context_rows(conn, openid)]


def resolve_alliance_context(
    conn: sqlite3.Connection,
    openid: str,
    alliance_id: int,
) -> AllianceContext | None:
    rows = _context_rows(conn, openid, alliance_id)
    return _build_context(conn, rows[0]) if rows else None
