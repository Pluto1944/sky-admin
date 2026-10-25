"""互刷新部落的受控官方资料同步。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from modules.sync_queue.config import active_live_resource_types
from modules.sync_queue.planner import SyncPlanner
from modules.sync_queue.refresh_policy import PROFILE_INTERVAL_SECONDS, as_utc, parse_time
from modules.sync_queue.repository import SyncQueueError, SyncQueueRepository

from .management import _assert_manager
from .repository import FarmAccountRepository, FarmClanRepository
from .tags import coc_tag_key


class FarmClanSyncService:
    SOURCE_TYPE = "farm_clan_request"
    INTEREST_SECONDS = 24 * 60 * 60
    RETRY_COOLDOWN_SECONDS = 60

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.accounts = FarmAccountRepository(conn)
        self.clans = FarmClanRepository(conn)
        self.queue = SyncQueueRepository(conn)

    def request(self, actor: dict, clan_tag: str, account_id: int) -> dict:
        _assert_manager(actor)
        tag = self._tag(clan_tag)
        account = self._active_account(account_id)
        existing = self.clans.get_by_tag(tag)
        if existing is not None:
            raise ValueError(f"部落已绑定到账号 {existing['account_id']}")
        ready = self._profile(tag)
        if ready is not None:
            return self._payload(tag, account, status="ready", profile=ready)

        current = datetime.now(timezone.utc)
        source_key = f"account:{int(account['id'])}:tag:{tag}"
        self.queue.upsert_interest(
            source_type=self.SOURCE_TYPE,
            source_key=source_key,
            resource_type="clan_profile",
            resource_key=tag,
            priority="interactive",
            desired_interval_seconds=6 * 60 * 60,
            expires_at=(current + timedelta(seconds=self.INTEREST_SECONDS)).isoformat(timespec="seconds"),
            metadata={
                "farm_account_id": int(account["id"]),
                "requested_by": int(actor["id"]),
                "category": "farm",
            },
            now=current,
        )
        SyncPlanner(self.conn).reconcile_targets(
            now=current,
            live_resource_types=active_live_resource_types(),
        )
        try:
            queued = self.queue.enqueue_interactive_task(
                "clan_profile",
                tag,
                cooldown_seconds=self.RETRY_COOLDOWN_SECONDS,
                now=current,
                payload={
                    "farm_account_id": int(account["id"]),
                    "requested_by": int(actor["id"]),
                    "trigger": "farm_clan_validation",
                },
            )
        except SyncQueueError as exc:
            return self._payload(
                tag, account, status="failed", error=str(exc), task_status="unavailable",
            )
        task = queued.get("task") or {}
        self._audit(actor, tag, account, queued)
        return self._payload(
            tag,
            account,
            status="syncing",
            task_id=task.get("id"),
            task_status=task.get("status"),
        )

    def status(self, actor: dict, clan_tag: str, account_id: int) -> dict:
        _assert_manager(actor)
        tag = self._tag(clan_tag)
        account = self._active_account(account_id)
        profile = self._profile(tag)
        if profile is not None:
            return self._payload(tag, account, status="ready", profile=profile)
        target = self.conn.execute(
            """SELECT * FROM sync_targets
               WHERE resource_type='clan_profile' AND resource_key=?""",
            (tag,),
        ).fetchone()
        if target is None:
            return self._payload(tag, account, status="not_requested")
        task = self.conn.execute(
            """SELECT * FROM sync_tasks WHERE target_id=?
               ORDER BY id DESC LIMIT 1""",
            (int(target["id"]),),
        ).fetchone()
        if task is None:
            return self._payload(tag, account, status="syncing", task_status="pending")
        task_status = task["status"]
        if task_status in {"failed", "dead", "cancelled"}:
            state = "failed"
            error = task["last_error"] or "官方部落资料同步失败"
        elif task_status == "succeeded":
            state = "failed"
            error = "同步任务已完成，但未取得可用的官方部落资料"
        else:
            state = "syncing"
            error = None
        return self._payload(
            tag,
            account,
            status=state,
            error=error,
            task_id=int(task["id"]),
            task_status=task_status,
        )

    def request_detail_profiles(
        self,
        actor: dict,
        clan_tag: str,
        *,
        now: datetime | None = None,
    ) -> dict:
        """Queue stale profile facts used by one authorized farm detail page.

        The read path remains cache-only.  Opening the page submits this
        separate mutation, and only the source clan plus its current farm
        opponent are eligible.  Current-war and farm-result facts are never
        queued here.
        """
        from .management import FarmManagementService

        current = as_utc(now)
        detail = FarmManagementService(self.conn).get_clan_detail(actor, clan_tag)
        source = detail["clan"]
        requested = [
            {
                "clan_tag": coc_tag_key(source["clan_tag"]),
                "clan_name": source["clan_name"],
                "kind": "source",
            }
        ]
        opponent = detail.get("opponent")
        if opponent and opponent.get("source") == "farm_registration":
            requested.append(
                {
                    "clan_tag": coc_tag_key(opponent.get("clan_tag")),
                    "clan_name": opponent.get("clan_name"),
                    "kind": "opponent",
                }
            )

        profiles = []
        seen = set()
        for item in requested:
            tag = item["clan_tag"]
            if not tag or tag in seen:
                continue
            seen.add(tag)
            profiles.append(
                self._request_detail_profile(
                    actor,
                    source,
                    tag=tag,
                    clan_name=item["clan_name"],
                    kind=item["kind"],
                    now=current,
                )
            )
        return {
            "clan_tag": coc_tag_key(source["clan_tag"]),
            "refresh_interval_seconds": PROFILE_INTERVAL_SECONDS,
            "profiles": profiles,
        }

    def _request_detail_profile(
        self,
        actor: dict,
        source,
        *,
        tag: str,
        clan_name: str | None,
        kind: str,
        now: datetime,
    ) -> dict:
        cache = self._profile_cache_row(tag)
        updated_at = cache["updated_at"] if cache is not None else None
        updated = parse_time(updated_at)
        has_profile = bool(cache is not None and cache["data_json"])
        if has_profile and updated is not None and now - updated < timedelta(
            seconds=PROFILE_INTERVAL_SECONDS
        ):
            return {
                "clan_tag": tag,
                "kind": kind,
                "accepted": False,
                "reason": "fresh",
                "task_status": None,
                "profile_updated_at": updated_at,
            }

        source_key = f"detail:{int(source['id'])}:{tag}"
        self.queue.upsert_interest(
            source_type=self.SOURCE_TYPE,
            source_key=source_key,
            resource_type="clan_profile",
            resource_key=tag,
            priority="interactive",
            desired_interval_seconds=PROFILE_INTERVAL_SECONDS,
            expires_at=(now + timedelta(seconds=self.INTEREST_SECONDS)).isoformat(
                timespec="seconds"
            ),
            metadata={
                "farm_account_id": int(source["account_id"]),
                "requested_by": int(actor["id"]),
                "category": "farm",
                "clan_name": clan_name or tag,
                "trigger": "farm_detail_page_open",
                "kind": kind,
            },
            now=now,
        )
        SyncPlanner(self.conn).reconcile_targets(
            now=now,
            live_resource_types=active_live_resource_types(),
        )
        try:
            queued = self.queue.enqueue_interactive_task(
                "clan_profile",
                tag,
                cooldown_seconds=PROFILE_INTERVAL_SECONDS,
                now=now,
                payload={
                    "farm_account_id": int(source["account_id"]),
                    "requested_by": int(actor["id"]),
                    "trigger": "farm_detail_page_open",
                    "kind": kind,
                },
            )
        except SyncQueueError as exc:
            return {
                "clan_tag": tag,
                "kind": kind,
                "accepted": False,
                "reason": "planner_pending",
                "task_status": None,
                "profile_updated_at": updated_at,
                "message": str(exc),
            }
        task = queued.get("task") or {}
        return {
            "clan_tag": tag,
            "kind": kind,
            "accepted": bool(queued.get("accepted")),
            "reason": queued.get("reason"),
            "task_status": task.get("status"),
            "profile_updated_at": updated_at,
        }

    def _profile_cache_row(self, tag: str):
        rows = self.conn.execute(
            """SELECT clan_tag, status, data_json, error, updated_at, attempted_at
               FROM clan_profile_cache"""
        ).fetchall()
        return next(
            (row for row in rows if coc_tag_key(row["clan_tag"]) == tag),
            None,
        )

    def _tag(self, value: str) -> str:
        tag = coc_tag_key(value)
        if not tag or len(tag) < 4 or len(tag) > 16:
            raise ValueError("请输入有效的 COC 部落标签")
        return tag

    def _active_account(self, account_id: int):
        try:
            account = self.accounts.get_by_id(int(account_id))
        except (TypeError, ValueError):
            account = None
        if account is None:
            raise LookupError("目标互刷账号不存在")
        if account["status"] != "active":
            raise ValueError("不能把部落绑定到已停用账号")
        return account

    def _profile(self, tag: str):
        rows = self.conn.execute(
            """SELECT clan_tag, clan_name, status, data_json, error, updated_at
               FROM clan_profile_cache WHERE data_json IS NOT NULL"""
        ).fetchall()
        for row in rows:
            if coc_tag_key(row["clan_tag"]) != tag or row["status"] not in {"success", "stale"}:
                continue
            try:
                data = json.loads(row["data_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            official_tag = coc_tag_key(
                data.get("tag") or data.get("clan_tag") or row["clan_tag"]
            )
            official_name = str(data.get("name") or row["clan_name"] or "").strip()
            if official_tag == tag and official_name:
                result = dict(row)
                result.update({"clan_tag": official_tag, "clan_name": official_name})
                return result
        return None

    @staticmethod
    def _payload(
        tag, account, *, status, profile=None, error=None, task_id=None, task_status=None,
    ) -> dict:
        return {
            "clan_tag": profile["clan_tag"] if profile is not None else tag,
            "clan_name": profile["clan_name"] if profile is not None else None,
            "account_id": int(account["id"]),
            "account_name": account["display_name"],
            "status": status,
            "profile_status": profile["status"] if profile is not None else None,
            "profile_updated_at": profile["updated_at"] if profile is not None else None,
            "task_id": int(task_id) if task_id is not None else None,
            "task_status": task_status,
            "error": error,
        }

    def _audit(self, actor, tag, account, queued) -> None:
        from shared.db.connection import now_iso

        task = queued.get("task") or {}
        with self.conn:
            self.conn.execute(
                """INSERT INTO farm_audit_logs
                   (actor_account_id, action, entity_type, entity_id,
                    after_json, created_at)
                   VALUES (?, 'clan.sync_requested', 'farm_clan', ?, ?, ?)""",
                (
                    int(actor["id"]), tag,
                    json.dumps({
                        "account_id": int(account["id"]),
                        "accepted": bool(queued.get("accepted")),
                        "reason": queued.get("reason"),
                        "task_id": task.get("id"),
                    }, ensure_ascii=False, sort_keys=True),
                    now_iso(),
                ),
            )
