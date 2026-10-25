"""互刷场次部落监控：缓存战争状态、聚合进度并分批刷新。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from modules.coc_sync.current_war import normalize_current_war
from shared.db.connection import now_iso

from .management import FarmPermissionError, _assert_manager
from .rounds import FINAL_REGISTRATION_STATUSES, public_round


DETECTED_WAR_STATUSES = {"preparation", "in_war", "war_ended"}
REFRESHABLE_WAR_STATUSES = {"unchecked", "not_in_war", "error"}
ACTIVE_ROUND_STATUSES = ("scheduled", "open", "partially_registered")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _next_check_at(round_scheduled_at: str, status: str, checked_at: datetime) -> str | None:
    if status not in {"not_in_war", "error"}:
        return None
    scheduled = _parse_iso(round_scheduled_at)
    if scheduled is None or checked_at >= scheduled + timedelta(minutes=60):
        return None
    delay = 10 if status == "not_in_war" else 15
    return (checked_at + timedelta(minutes=delay)).isoformat(timespec="seconds")


def save_monitor_snapshot(
    conn: sqlite3.Connection,
    *,
    round_id: int,
    clan_id: int,
    normalized: dict,
    source: str,
    checked_at: str | None = None,
) -> None:
    checked_text = checked_at or now_iso()
    checked = _parse_iso(checked_text) or datetime.now(timezone.utc)
    round_row = conn.execute(
        "SELECT scheduled_at FROM farm_rounds WHERE id = ?", (int(round_id),)
    ).fetchone()
    if round_row is None:
        return
    status = normalized.get("status") or "not_in_war"
    if status not in DETECTED_WAR_STATUSES | {"not_in_war", "cwl", "error"}:
        status = "error"
    opponent = normalized.get("opponent") or {}
    official_time = normalized.get("preparation_start_time")
    next_check = _next_check_at(round_row["scheduled_at"], status, checked)
    with conn:
        conn.execute(
            """INSERT INTO farm_round_monitors
               (round_id, clan_id, war_status, opponent_tag, opponent_name,
                official_time, source, checked_at, next_check_at, error,
                check_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(round_id, clan_id) DO UPDATE SET
                   war_status=excluded.war_status,
                   opponent_tag=excluded.opponent_tag,
                   opponent_name=excluded.opponent_name,
                   official_time=excluded.official_time,
                   source=excluded.source,
                   checked_at=excluded.checked_at,
                   next_check_at=excluded.next_check_at,
                   error=excluded.error,
                   check_count=farm_round_monitors.check_count + 1,
                   updated_at=excluded.updated_at""",
            (
                int(round_id), int(clan_id), status, opponent.get("tag"),
                opponent.get("name"), official_time, source, checked_text, next_check,
                normalized.get("error"), checked_text, checked_text,
            ),
        )


def save_monitor_error(
    conn: sqlite3.Connection,
    *,
    round_id: int,
    clan_id: int,
    error: str,
    source: str,
    checked_at: str | None = None,
) -> None:
    save_monitor_snapshot(
        conn,
        round_id=round_id,
        clan_id=clan_id,
        normalized={"status": "error", "error": str(error or "")[:500]},
        source=source,
        checked_at=checked_at,
    )


class FarmMonitoringService:
    def __init__(self, conn: sqlite3.Connection, coc_client=None):
        self.conn = conn
        self.coc_client = coc_client

    def _current_active_round(self):
        placeholders = ",".join("?" for _ in ACTIVE_ROUND_STATUSES)
        return self.conn.execute(
            f"""SELECT * FROM farm_rounds
                WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT 1""",
            ACTIVE_ROUND_STATUSES,
        ).fetchone()

    def _current_round(self):
        active = self._current_active_round()
        if active is not None:
            return active
        return self.conn.execute(
            "SELECT * FROM farm_rounds WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def _round(self, round_id: int | None = None):
        row = (
            self.conn.execute(
                "SELECT * FROM farm_rounds WHERE id = ?", (int(round_id),)
            ).fetchone()
            if round_id is not None
            else self._current_round()
        )
        if row is None:
            raise LookupError("当前没有可监控的互刷场次")
        return row

    def ensure_round_rows(self, round_row) -> None:
        scheduled = _parse_iso(round_row["scheduled_at"]) or datetime.now(timezone.utc)
        first_check = (scheduled + timedelta(minutes=5)).isoformat(timespec="seconds")
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO farm_round_monitors
                   (round_id, clan_id, war_status, next_check_at, created_at, updated_at)
                   SELECT round_id, clan_id, 'unchecked', ?, ?, ?
                   FROM farm_round_clans WHERE round_id = ?""",
                (first_check, now, now, int(round_row["id"])),
            )
            attempts = self.conn.execute(
                """SELECT a.clan_id, a.summary_json, a.error_message, a.created_at
                   FROM farm_registration_attempts a
                   JOIN (
                       SELECT clan_id, MAX(id) AS latest_id
                       FROM farm_registration_attempts WHERE round_id = ? GROUP BY clan_id
                   ) latest ON latest.latest_id = a.id
                   JOIN farm_round_monitors m
                     ON m.round_id = a.round_id AND m.clan_id = a.clan_id
                   WHERE a.round_id = ? AND m.checked_at IS NULL""",
                (int(round_row["id"]), int(round_row["id"])),
            ).fetchall()
            for attempt in attempts:
                try:
                    summary = json.loads(attempt["summary_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    summary = {}
                status = summary.get("status") or ("error" if attempt["error_message"] else None)
                if not status:
                    continue
                opponent = summary.get("opponent") or {}
                checked = _parse_iso(attempt["created_at"]) or datetime.now(timezone.utc)
                self.conn.execute(
                    """UPDATE farm_round_monitors
                       SET war_status=?, opponent_tag=?, opponent_name=?, official_time=?,
                           source='registration_backfill', checked_at=?, next_check_at=?,
                           error=?, check_count=1, updated_at=?
                       WHERE round_id=? AND clan_id=?""",
                    (
                        status if status in DETECTED_WAR_STATUSES | {"not_in_war", "cwl", "error"}
                        else "error",
                        opponent.get("tag"), opponent.get("name"),
                        summary.get("preparation_start_time"), attempt["created_at"],
                        _next_check_at(round_row["scheduled_at"], status, checked),
                        attempt["error_message"], attempt["created_at"],
                        int(round_row["id"]), int(attempt["clan_id"]),
                    ),
                )

    def _items(self, round_row) -> list[dict]:
        self.ensure_round_rows(round_row)
        rows = self.conn.execute(
            """SELECT rc.*, c.score AS current_score,
                      a.display_name AS account_name, a.username AS account_username,
                      m.war_status, m.opponent_tag AS monitor_opponent_tag,
                      m.opponent_name AS monitor_opponent_name, m.official_time,
                      m.source AS monitor_source, m.checked_at, m.next_check_at,
                      m.error AS monitor_error, m.check_count
               FROM farm_round_clans rc
               JOIN farm_clans c ON c.id = rc.clan_id
               JOIN farm_auth_accounts a ON a.id = rc.account_id_snapshot
               LEFT JOIN farm_round_monitors m
                 ON m.round_id = rc.round_id AND m.clan_id = rc.clan_id
               WHERE rc.round_id = ?""",
            (int(round_row["id"]),),
        ).fetchall()
        return [self._public_item(row) for row in rows]

    @staticmethod
    def _public_item(row) -> dict:
        registration_status = row["registration_status"]
        final = registration_status in FINAL_REGISTRATION_STATUSES
        war_status = row["war_status"] or "unchecked"
        attention = (
            war_status in {"unchecked", "not_in_war", "error", "cwl"}
            or not final
            or registration_status in {"match_failed", "war_mismatch", "fetch_failed", "revoked"}
        )
        return {
            "round_id": int(row["round_id"]),
            "clan_id": int(row["clan_id"]),
            "clan_tag": row["clan_tag_snapshot"],
            "clan_name": row["clan_name_snapshot"],
            "account_id": int(row["account_id_snapshot"]),
            "account_name": row["account_name"],
            "account_username": row["account_username"],
            "current_score": int(row["current_score"]),
            "war_status": war_status,
            "war_checked_at": row["checked_at"],
            "war_error": row["monitor_error"],
            "war_check_count": int(row["check_count"] or 0),
            "registration_status": registration_status,
            "registered": final,
            "opponent_tag": row["opponent_tag"] or row["monitor_opponent_tag"],
            "opponent_name": row["opponent_name"] or row["monitor_opponent_name"],
            "result": row["result"],
            "score_before": int(row["score_before"]),
            "score_after": row["score_after"],
            "last_attempt_at": row["last_attempt_at"],
            "last_error": row["last_error"],
            "attention": attention,
        }

    def overview(self, actor: dict, round_id: int | None = None) -> dict:
        _assert_manager(actor)
        round_row = self._round(round_id)
        items = self._items(round_row)
        total = len(items)
        detected = sum(item["war_status"] in DETECTED_WAR_STATUSES for item in items)
        not_detected = sum(item["war_status"] == "not_in_war" for item in items)
        unchecked = sum(item["war_status"] == "unchecked" for item in items)
        war_errors = sum(item["war_status"] in {"error", "cwl"} for item in items)
        registered = sum(item["registered"] for item in items)
        matched = sum(item["registration_status"] == "internal_matched" for item in items)
        failed = sum(item["registration_status"] == "match_failed" for item in items)
        denominator = matched + failed
        wins = sum(item["result"] == "win" for item in items)
        losses = sum(item["result"] == "loss" for item in items)
        revoked = sum(item["registration_status"] == "revoked" for item in items)
        account_map: dict[int, dict] = {}
        for item in items:
            progress = account_map.setdefault(
                item["account_id"],
                {
                    "account_id": item["account_id"],
                    "account_name": item["account_name"],
                    "account_username": item["account_username"],
                    "total": 0,
                    "registered": 0,
                },
            )
            progress["total"] += 1
            progress["registered"] += int(item["registered"])
        accounts = sorted(
            account_map.values(),
            key=lambda item: (item["registered"] == item["total"], item["account_name"].lower()),
        )
        checked_values = [item["war_checked_at"] for item in items if item["war_checked_at"]]
        return {
            "round": public_round(round_row),
            "updated_at": max(checked_values, default=round_row["updated_at"]),
            "war": {
                "total": total,
                "detected": detected,
                "not_detected": not_detected,
                "unchecked": unchecked,
                "error": war_errors,
            },
            "registration": {
                "total": total,
                "registered": registered,
                "pending": total - registered,
                "rate": round(registered * 100 / total, 1) if total else 0,
            },
            "matching": {
                "success": matched,
                "failed": failed,
                "pending": total - denominator,
                "success_pairs": matched // 2,
                "rate": round(matched * 100 / denominator, 1) if denominator else 0,
            },
            "results": {
                "win": wins,
                "loss": losses,
                "match_failed": failed,
                "revoked": revoked,
                "pending": total - wins - losses - failed,
            },
            "attention": {
                "unregistered": total - registered,
                "war_not_detected": not_detected,
                "war_unchecked": unchecked,
                "war_error": war_errors,
                "match_failed": failed,
                "war_mismatch": sum(
                    item["registration_status"] == "war_mismatch" for item in items
                ),
                "fetch_failed": sum(
                    item["registration_status"] == "fetch_failed" for item in items
                ),
            },
            "accounts": accounts,
            "can_refresh": (
                actor.get("role") == "creator"
                and round_row["status"] in ACTIVE_ROUND_STATUSES
            ),
        }

    @staticmethod
    def _matches_filter(item: dict, value: str) -> bool:
        filters = {
            "all": lambda row: True,
            "attention": lambda row: row["attention"],
            "war_detected": lambda row: row["war_status"] in DETECTED_WAR_STATUSES,
            "war_not_detected": lambda row: row["war_status"] == "not_in_war",
            "war_unchecked": lambda row: row["war_status"] == "unchecked",
            "war_error": lambda row: row["war_status"] in {"error", "cwl"},
            "registered": lambda row: row["registered"],
            "unregistered": lambda row: not row["registered"],
            "war_mismatch": lambda row: row["registration_status"] == "war_mismatch",
            "fetch_failed": lambda row: row["registration_status"] == "fetch_failed",
            "match_success": lambda row: row["registration_status"] == "internal_matched",
            "match_failed": lambda row: row["registration_status"] == "match_failed",
            "win": lambda row: row["result"] == "win",
            "loss": lambda row: row["result"] == "loss",
            "revoked": lambda row: row["registration_status"] == "revoked",
        }
        return filters.get(value, filters["all"])(item)

    def list_clans(
        self,
        actor: dict,
        *,
        round_id: int | None = None,
        status_filter: str = "attention",
        account_id: int | None = None,
        search: str = "",
        sort: str = "attention",
        page: int = 1,
        page_size: int = 30,
    ) -> dict:
        _assert_manager(actor)
        round_row = self._round(round_id)
        items = self._items(round_row)
        query = search.strip().lower()
        items = [
            item for item in items
            if self._matches_filter(item, status_filter)
            and (account_id is None or item["account_id"] == int(account_id))
            and (
                not query
                or query in item["clan_name"].lower()
                or query in item["clan_tag"].lower()
                or query in item["account_name"].lower()
                or query in item["account_username"].lower()
            )
        ]
        if sort == "account":
            items.sort(key=lambda item: (item["account_name"].lower(), item["clan_name"].lower()))
        elif sort == "updated":
            items.sort(key=lambda item: item["war_checked_at"] or "", reverse=True)
        else:
            items.sort(
                key=lambda item: (
                    not item["attention"],
                    item["registered"],
                    item["account_name"].lower(),
                    item["clan_name"].lower(),
                )
            )
        size = max(1, min(int(page_size), 50))
        current_page = max(1, int(page))
        start = (current_page - 1) * size
        return {
            "round": public_round(round_row),
            "total": len(items),
            "page": current_page,
            "page_size": size,
            "has_more": start + size < len(items),
            "clans": items[start:start + size],
        }

    def request_refresh(self, actor: dict, round_id: int | None = None) -> dict:
        if actor.get("role") != "creator":
            raise FarmPermissionError("只有超级管理员可以刷新部落监控")
        round_row = self._round(round_id)
        if round_row["status"] not in ACTIVE_ROUND_STATUSES:
            raise ValueError("已完成场次不能刷新部落监控")
        self.ensure_round_rows(round_row)
        now = now_iso()
        placeholders = ",".join("?" for _ in REFRESHABLE_WAR_STATUSES)
        with self.conn:
            cursor = self.conn.execute(
                f"""UPDATE farm_round_monitors
                    SET next_check_at = ?, updated_at = ?
                    WHERE round_id = ? AND war_status IN ({placeholders})""",
                (now, now, int(round_row["id"]), *sorted(REFRESHABLE_WAR_STATUSES)),
            )
            self.conn.execute(
                """INSERT INTO farm_audit_logs
                   (actor_account_id, action, entity_type, entity_id, after_json, created_at)
                   VALUES (?, 'monitor.refresh_requested', 'farm_round', ?, ?, ?)""",
                (
                    int(actor["id"]), str(round_row["id"]),
                    json.dumps({"queued": cursor.rowcount}, ensure_ascii=False), now,
                ),
            )
        return {"round_id": int(round_row["id"]), "queued": cursor.rowcount}

    def run_due(self, *, now: datetime | None = None, limit: int | None = None) -> dict:
        if self.coc_client is None:
            raise RuntimeError("部落监控任务缺少 COC 客户端")
        round_row = self._current_active_round()
        if round_row is None:
            return {"status": "skipped", "reason": "当前没有可监控的互刷场次"}
        self.ensure_round_rows(round_row)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        current_text = current.isoformat(timespec="seconds")
        batch_size = limit if limit is not None else int(os.getenv("FARM_MONITOR_BATCH_SIZE", "20"))
        batch_size = max(1, min(int(batch_size), 50))
        rows = self.conn.execute(
            """SELECT rc.clan_id, rc.clan_tag_snapshot, rc.clan_name_snapshot
               FROM farm_round_monitors m
               JOIN farm_round_clans rc
                 ON rc.round_id = m.round_id AND rc.clan_id = m.clan_id
               WHERE m.round_id = ? AND m.next_check_at IS NOT NULL
                 AND m.next_check_at <= ?
               ORDER BY m.next_check_at, rc.clan_id LIMIT ?""",
            (int(round_row["id"]), current_text, batch_size),
        ).fetchall()
        if not rows:
            return {"status": "skipped", "reason": "没有到期的部落监控检查"}
        success = 0
        failed = 0
        for row in rows:
            try:
                raw = self.coc_client.get_current_war(row["clan_tag_snapshot"])
                normalized = normalize_current_war(
                    raw,
                    {"tag": row["clan_tag_snapshot"], "name": row["clan_name_snapshot"], "category": "farm"},
                    current_text,
                )
                save_monitor_snapshot(
                    self.conn,
                    round_id=int(round_row["id"]),
                    clan_id=int(row["clan_id"]),
                    normalized=normalized,
                    source="monitor_job",
                    checked_at=current_text,
                )
                success += 1
            except Exception as exc:  # 单个部落失败不能中断整批
                save_monitor_error(
                    self.conn,
                    round_id=int(round_row["id"]),
                    clan_id=int(row["clan_id"]),
                    error=str(exc),
                    source="monitor_job",
                    checked_at=current_text,
                )
                failed += 1
        return {
            "status": "success",
            "reason": f"检查 {len(rows)} 个部落，成功 {success}，失败 {failed}",
            "checked": len(rows),
            "success_count": success,
            "failed_count": failed,
        }
