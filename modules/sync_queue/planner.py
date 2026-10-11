"""Shadow planner that derives globally deduplicated sync targets.

It reads only local configuration and caches.  It never calls an external API
and never writes business facts, so M4.0 can compare its plan with the legacy
scheduler before any task type is cut over.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
from modules.coc_sync.official.mapper import normalize_tag

from .config import RESOURCE_TYPES, parse_resource_types
from .repository import SyncQueueRepository


BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
MANAGED_SOURCE_TYPES = ("alliance_clan", "alliance_cwl_team")


def _as_utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


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
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_war_policy(
    sync_tier: str,
    cache: dict | None,
    current: datetime,
) -> tuple[str, int]:
    """Mirror today's broad refresh classes without executing a request."""
    if sync_tier == "low":
        return "scheduled", 6 * 60 * 60
    status = (cache or {}).get("status")
    failures = int((cache or {}).get("failure_count") or 0)
    if status == "error" or failures > 0:
        backoff = (5, 10, 20, 30)
        return "scheduled", backoff[min(max(1, failures) - 1, len(backoff) - 1)] * 60
    if status == "in_war":
        return "realtime", 2 * 60
    if status == "preparation":
        try:
            payload = json.loads((cache or {}).get("data_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        start_time = _parse_time(payload.get("start_time"))
        if start_time is not None and (start_time - current).total_seconds() <= 30 * 60:
            return "realtime", 2 * 60
        return "realtime", 30 * 60
    if status == "cwl":
        return "scheduled", 30 * 60
    return "scheduled", 5 * 60


class SyncPlanner:
    """Reconcile subscriptions and plan shadow/live work by resource type."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.queue = SyncQueueRepository(conn)

    def _clan_interests(self, current: datetime) -> list[dict]:
        cache_by_tag = {
            normalize_tag(row["clan_tag"]): dict(row)
            for row in self.conn.execute("SELECT * FROM current_war_cache").fetchall()
            if normalize_tag(row["clan_tag"])
        }
        rows = self.conn.execute(
            """SELECT clans.id, clans.alliance_id, clans.clan_tag, clans.category,
                      alliances.plan_code, plans.sync_tier
               FROM alliance_clans AS clans
               JOIN alliances ON alliances.id = clans.alliance_id
               JOIN alliance_plans AS plans ON plans.plan_code = alliances.plan_code
               WHERE clans.status = 'active' AND alliances.status = 'active'
                 AND plans.status = 'active'
               ORDER BY clans.id"""
        ).fetchall()
        interests: list[dict] = []
        for row in rows:
            tag = normalize_tag(row["clan_tag"])
            if not tag:
                continue
            tier = row["sync_tier"]
            base_interval = 24 * 60 * 60 if tier == "low" else 6 * 60 * 60
            common = {
                "source_type": "alliance_clan",
                "source_key": str(row["id"]),
                "alliance_id": int(row["alliance_id"]),
                "resource_key": tag,
                "metadata": {
                    "category": row["category"],
                    "plan_code": row["plan_code"],
                    "sync_tier": tier,
                },
            }
            for resource_type in ("clan_profile", "clan_members"):
                interests.append({
                    **common,
                    "resource_type": resource_type,
                    "priority": "scheduled",
                    "desired_interval_seconds": base_interval,
                })
            priority, interval = _current_war_policy(tier, cache_by_tag.get(tag), current)
            interests.append({
                **common,
                "resource_type": "current_war",
                "priority": priority,
                "desired_interval_seconds": interval,
                "metadata": {
                    **common["metadata"],
                    "cached_status": (cache_by_tag.get(tag) or {}).get("status"),
                },
            })
        return interests

    def _cwl_interests(self, current: datetime) -> list[dict]:
        local_now = current.astimezone(BUSINESS_TZ)
        # The legacy live collector only runs through day 12.  Shadow targets
        # deliberately mirror that boundary until a later M4 cut-over reviews it.
        if local_now.day > 12:
            return []
        period = local_now.strftime("%Y-%m")
        rows = self.conn.execute(
            """SELECT teams.id, seasons.alliance_id, seasons.period,
                      teams.clan_tag, teams.category, alliances.plan_code,
                      plans.sync_tier
               FROM alliance_cwl_teams AS teams
               JOIN alliance_cwl_seasons AS seasons ON seasons.id = teams.season_id
               JOIN alliances ON alliances.id = seasons.alliance_id
               JOIN alliance_plans AS plans ON plans.plan_code = alliances.plan_code
               WHERE seasons.period = ?
                 AND seasons.status IN ('active', 'frozen', 'complete')
                 AND alliances.status = 'active' AND plans.status = 'active'
               ORDER BY teams.id""",
            (period,),
        ).fetchall()
        interests: list[dict] = []
        for row in rows:
            tag = normalize_tag(row["clan_tag"])
            if not tag:
                continue
            high_quality = row["sync_tier"] in {"high", "internal"}
            interests.append({
                "source_type": "alliance_cwl_team",
                "source_key": str(row["id"]),
                "alliance_id": int(row["alliance_id"]),
                "resource_type": "cwl_live",
                "resource_key": f"{period}:{tag}",
                "priority": "realtime" if high_quality else "scheduled",
                "desired_interval_seconds": 2 * 60 if high_quality else 30 * 60,
                "metadata": {
                    "period": period,
                    "clan_tag": tag,
                    "category": row["category"],
                    "plan_code": row["plan_code"],
                    "sync_tier": row["sync_tier"],
                },
            })
        return interests

    def _legacy_comparison(self, current: datetime) -> dict[str, dict[str, int]]:
        """Count target differences against the still-supported legacy sources.

        Only counts are returned so observability never exposes clan tags.  An
        extra queue target is valid for a non-legacy alliance; a missing legacy
        target is the cut-over blocker.
        """
        configured = {
            tag for item in config.CLANS if item.get("enabled", True)
            if (tag := normalize_tag(item.get("tag")))
        }
        expected: dict[str, set[str]] = {
            "clan_profile": set(configured),
            "clan_members": set(configured),
            "current_war": set(configured),
            "cwl_live": set(),
        }
        local_now = current.astimezone(BUSINESS_TZ)
        if local_now.day <= 12:
            period = local_now.strftime("%Y-%m")
            rows = self.conn.execute(
                """SELECT clan_tag FROM league_teams
                   WHERE period = ? AND category IN ('combat', 'shell')
                   UNION
                   SELECT teams.clan_tag
                   FROM alliance_cwl_teams AS teams
                   JOIN alliance_cwl_seasons AS seasons ON seasons.id = teams.season_id
                   WHERE seasons.period = ?
                     AND seasons.status IN ('active', 'frozen', 'complete')""",
                (period, period),
            ).fetchall()
            expected["cwl_live"] = {
                f"{period}:{tag}" for row in rows
                if (tag := normalize_tag(row["clan_tag"]))
            }
        planned: dict[str, set[str]] = {name: set() for name in expected}
        for row in self.conn.execute(
            """SELECT resource_type, resource_key FROM sync_targets
               WHERE status = 'active'"""
        ).fetchall():
            if row["resource_type"] in planned:
                planned[row["resource_type"]].add(row["resource_key"])
        return {
            name: {
                "legacy": len(expected[name]),
                "planned": len(planned[name]),
                "missing": len(expected[name] - planned[name]),
                "extra": len(planned[name] - expected[name]),
            }
            for name in expected
        }

    def run(
        self,
        *,
        now: datetime | None = None,
        task_limit: int = 1000,
        shadow_retention_days: int = 7,
        live_resource_types: tuple[str, ...] | list[str] = (),
    ) -> dict:
        current = _as_utc(now)
        live_types = parse_resource_types(live_resource_types)
        shadow_types = tuple(item for item in RESOURCE_TYPES if item not in live_types)
        interests = self._clan_interests(current) + self._cwl_interests(current)
        interest_result = self.queue.reconcile_interests(
            interests,
            managed_source_types=MANAGED_SOURCE_TYPES,
            now=current,
        )
        target_result = self.queue.rebuild_targets(now=current)
        comparison = self._legacy_comparison(current)
        mode_changes = self.queue.set_target_modes(live_types, now=current)
        live_tasks = self.queue.plan_due_tasks(
            mode="live", now=current, limit=task_limit, resource_types=live_types,
        ) if live_types else []
        remaining = max(0, task_limit - len(live_tasks))
        shadow_tasks = self.queue.plan_due_tasks(
            mode="shadow", now=current, limit=remaining,
            resource_types=shadow_types,
        ) if shadow_types and remaining else []
        tasks = live_tasks + shadow_tasks
        pruned = self.queue.prune_shadow_tasks(
            retention_days=shadow_retention_days,
            now=current,
        )
        return {
            "mode": "mixed" if live_types and shadow_types else ("live" if live_types else "shadow"),
            "live_resource_types": list(live_types),
            "shadow_resource_types": list(shadow_types),
            "mode_changes": mode_changes,
            "interests": interest_result,
            "targets": target_result,
            "legacy_comparison": comparison,
            "tasks_planned": len(tasks),
            "live_tasks_planned": len(live_tasks),
            "shadow_tasks_planned": len(shadow_tasks),
            "tasks_by_type": {
                resource_type: sum(1 for task in tasks if task["resource_type"] == resource_type)
                for resource_type in sorted({task["resource_type"] for task in tasks})
            },
            "shadow_tasks_pruned": pruned,
            "queue": self.queue.summary(),
        }


class ShadowSyncPlanner(SyncPlanner):
    """Backward-compatible M4.0 planner that never creates live work."""

    def run(self, **kwargs) -> dict:
        kwargs["live_resource_types"] = ()
        return super().run(**kwargs)


def format_planner_reason(result: dict) -> str:
    """Compact scheduler reason without exposing payloads or private data."""
    counts = json.dumps(result.get("tasks_by_type", {}), ensure_ascii=False, sort_keys=True)
    return (
        f"计划 {result.get('tasks_planned', 0)} 个任务"
        f"（live {result.get('live_tasks_planned', 0)} / "
        f"影子 {result.get('shadow_tasks_planned', 0)}），"
        f"有效目标 {result.get('targets', {}).get('active', 0)}，类型 {counts}"
    )
