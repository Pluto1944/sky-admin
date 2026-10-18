"""联盟套餐目录与能力判定。

套餐名称、部落配额和同步等级在这里集中定义。数据库中的
``alliance_plans`` 是运行时权威，常量用于幂等迁移、输入校验和兼容旧
``paid`` 套餐；业务页面不应自行复制配额或刷新能力。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Mapping


FREE_PLAN = "free"
STANDARD_PLAN = "standard"
PREMIUM_PLAN = "premium"
INTERNAL_PLAN = "internal"
LEGACY_PAID_PLAN = "paid"

ACTIVE_PLAN_CODES = frozenset({
    FREE_PLAN, STANDARD_PLAN, PREMIUM_PLAN, INTERNAL_PLAN,
})
TIME_LIMITED_PLAN_CODES = frozenset({
    STANDARD_PLAN, PREMIUM_PLAN, LEGACY_PAID_PLAN,
})
TIME_LIMITED_PLAN_SQL = "('standard','premium','paid')"
USER_MANAGED_PLAN_CODES = frozenset({
    FREE_PLAN, STANDARD_PLAN, PREMIUM_PLAN, LEGACY_PAID_PLAN,
})
ON_DEMAND_PLAN_CODES = frozenset({FREE_PLAN, STANDARD_PLAN})
AUTOMATIC_REFRESH_PLAN_CODES = frozenset({
    PREMIUM_PLAN, INTERNAL_PLAN, LEGACY_PAID_PLAN,
})

PLAN_ROWS = (
    {
        "plan_code": FREE_PLAN,
        "display_name": "免费版",
        "max_clans": 3,
        "sync_tier": "low",
        "entitlements": {
            "history_scope": "full",
            "manual_refresh": True,
            "automatic_refresh": False,
            "max_cwl_teams": 3,
            "cwl_data": True,
            "cwl_registration": False,
        },
    },
    {
        "plan_code": STANDARD_PLAN,
        "display_name": "普通会员",
        "max_clans": 10,
        "sync_tier": "low",
        "entitlements": {
            "history_scope": "full",
            "manual_refresh": True,
            "automatic_refresh": False,
            "max_cwl_teams": 10,
            "cwl_data": True,
            "cwl_registration": False,
        },
    },
    {
        "plan_code": PREMIUM_PLAN,
        "display_name": "高级会员",
        "max_clans": 10,
        "sync_tier": "high",
        "entitlements": {
            "history_scope": "full",
            "manual_refresh": False,
            "automatic_refresh": True,
            "max_cwl_teams": 10,
            "cwl_data": True,
            "cwl_registration": False,
        },
    },
    {
        "plan_code": INTERNAL_PLAN,
        "display_name": "内部版",
        "max_clans": 100,
        "sync_tier": "internal",
        "entitlements": {
            "history_scope": "full",
            "manual_refresh": False,
            "automatic_refresh": True,
            "max_cwl_teams": 100,
            "cwl_data": True,
            "cwl_registration": True,
            "registration_source": "tencent_docs",
        },
    },
)

PLAN_BY_CODE: Mapping[str, dict] = {
    str(item["plan_code"]): item for item in PLAN_ROWS
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def plan_requires_expiry(plan_code: str) -> bool:
    return plan_code in TIME_LIMITED_PLAN_CODES


def plan_allows_user_management(plan_code: str) -> bool:
    return plan_code in USER_MANAGED_PLAN_CODES


def plan_uses_on_demand_refresh(plan_code: str) -> bool:
    return plan_code in ON_DEMAND_PLAN_CODES


def plan_uses_automatic_refresh(plan_code: str) -> bool:
    return plan_code in AUTOMATIC_REFRESH_PLAN_CODES


def ensure_plan_catalog(
    conn: sqlite3.Connection,
    *,
    now: str,
) -> dict[str, int]:
    """幂等写入套餐目录，并把旧 ``paid`` 权益迁移为高级会员。

    旧套餐原本提供高频自动刷新，因此迁移到 ``premium`` 才不会降低既有
    权益。旧行保留为 inactive，便于历史审计文本继续解析。
    """
    inserted = 0
    updated = 0
    for plan in PLAN_ROWS:
        code = str(plan["plan_code"])
        entitlement_json = _canonical_json(plan["entitlements"])
        row = conn.execute(
            """SELECT display_name, max_clans, sync_tier, entitlements_json, status
               FROM alliance_plans WHERE plan_code=?""",
            (code,),
        ).fetchone()
        expected = (
            plan["display_name"], int(plan["max_clans"]), plan["sync_tier"],
            entitlement_json, "active",
        )
        if row is None:
            conn.execute(
                """INSERT INTO alliance_plans
                       (plan_code, display_name, max_clans, sync_tier,
                        entitlements_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    code, plan["display_name"], int(plan["max_clans"]),
                    plan["sync_tier"], entitlement_json, now, now,
                ),
            )
            inserted += 1
        elif code == INTERNAL_PLAN:
            # Internal capacity and extra entitlements are operational settings.
            # Keep them across application restarts while enforcing the stable
            # identity, sync tier and active catalog status.
            internal_expected = (
                plan["display_name"], int(row["max_clans"]), "internal",
                row["entitlements_json"], "active",
            )
            if tuple(row) != internal_expected:
                conn.execute(
                    """UPDATE alliance_plans
                       SET display_name=?, sync_tier='internal', status='active',
                           updated_at=?
                       WHERE plan_code=?""",
                    (plan["display_name"], now, code),
                )
                updated += 1
        elif tuple(row) != expected:
            conn.execute(
                """UPDATE alliance_plans
                   SET display_name=?, max_clans=?, sync_tier=?,
                       entitlements_json=?, status='active', updated_at=?
                   WHERE plan_code=?""",
                (*expected[:4], now, code),
            )
            updated += 1

    legacy = conn.execute(
        "SELECT 1 FROM alliance_plans WHERE plan_code=?",
        (LEGACY_PAID_PLAN,),
    ).fetchone()
    migrated_alliances = 0
    migrated_grants = 0
    if legacy is not None:
        migrated_alliances = conn.execute(
            "UPDATE alliances SET plan_code=?, updated_at=? WHERE plan_code=?",
            (PREMIUM_PLAN, now, LEGACY_PAID_PLAN),
        ).rowcount
        migrated_grants = conn.execute(
            "UPDATE alliance_plan_grants SET plan_code=?, updated_at=? WHERE plan_code=?",
            (PREMIUM_PLAN, now, LEGACY_PAID_PLAN),
        ).rowcount
        legacy_row = conn.execute(
            "SELECT display_name, status FROM alliance_plans WHERE plan_code=?",
            (LEGACY_PAID_PLAN,),
        ).fetchone()
        if legacy_row is not None and tuple(legacy_row) != ("历史付费版", "inactive"):
            conn.execute(
                """UPDATE alliance_plans
                   SET display_name='历史付费版', status='inactive', updated_at=?
                   WHERE plan_code=?""",
                (now, LEGACY_PAID_PLAN),
            )
    return {
        "inserted": inserted,
        "updated": updated,
        "migrated_alliances": migrated_alliances,
        "migrated_grants": migrated_grants,
    }
