"""互刷统一场次与参与部落快照。F3 不执行 COC 登记。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from shared.db.connection import now_iso

from .management import FarmPermissionError, _assert_manager


BEIJING = ZoneInfo("Asia/Shanghai")
BUSINESS_TIME_KIND = "preparation_start"
ACTIVE_ROUND_STATUSES = ("scheduled", "open", "partially_registered")
FINAL_REGISTRATION_STATUSES = ("internal_matched", "match_failed")
NON_REGISTERABLE_STATUSES = FINAL_REGISTRATION_STATUSES + ("revoked",)


def normalize_scheduled_at(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("统一时间不能为空")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("统一时间必须是带时区的 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError("统一时间必须包含时区")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def public_round(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    scheduled = datetime.fromisoformat(row["scheduled_at"])
    return {
        "id": int(row["id"]),
        "scheduled_at": scheduled.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "scheduled_at_beijing": scheduled.astimezone(BEIJING).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "business_time_kind": row["business_time_kind"],
        "status": row["status"],
        "time_locked_at": row["time_locked_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_round_clan(row: sqlite3.Row) -> dict:
    return {
        "clan_id": int(row["clan_id"]),
        "account_id": int(row["account_id_snapshot"]),
        "clan_tag": row["clan_tag_snapshot"],
        "clan_name": row["clan_name_snapshot"],
        "score_before": int(row["score_before"]),
        "current_score": int(row["current_score"]),
        "registration_status": row["registration_status"],
        "match_id": int(row["match_id"]) if row["match_id"] is not None else None,
        "opponent_tag": row["opponent_tag"],
        "opponent_name": row["opponent_name"],
        "result": row["result"],
        "score_after": row["score_after"],
        "registered_at": row["registered_at"],
        "last_attempt_at": row["last_attempt_at"],
        "last_error": row["last_error"],
    }


def public_bound_clan(row: sqlite3.Row) -> dict:
    """无当前场次时仍展示账号已绑定的启用部落。"""
    score = int(row["score"])
    return {
        "clan_id": int(row["id"]),
        "account_id": int(row["account_id"]),
        "clan_tag": row["clan_tag"],
        "clan_name": row["clan_name"],
        "score_before": score,
        "current_score": score,
        "registration_status": "not_registered",
        "match_id": None,
        "opponent_tag": None,
        "opponent_name": None,
        "result": None,
        "score_after": None,
        "registered_at": None,
        "last_attempt_at": None,
        "last_error": None,
    }


class FarmRoundService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def current_round(self) -> sqlite3.Row | None:
        placeholders = ",".join("?" for _ in ACTIVE_ROUND_STATUSES)
        active = self.conn.execute(
            f"SELECT * FROM farm_rounds WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            ACTIVE_ROUND_STATUSES,
        ).fetchone()
        if active is not None:
            return active
        return self.conn.execute(
            "SELECT * FROM farm_rounds WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def get_round(self, round_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM farm_rounds WHERE id = ?", (int(round_id),)
        ).fetchone()

    def create_round(self, actor: dict, payload: dict) -> sqlite3.Row:
        _assert_manager(actor)
        scheduled_at = normalize_scheduled_at(payload.get("scheduled_at"))
        kind = payload.get("business_time_kind") or BUSINESS_TIME_KIND
        if kind != BUSINESS_TIME_KIND:
            raise ValueError("统一时间固定为开始搜战时间")
        candidates = self.conn.execute(
            """SELECT c.* FROM farm_clans c
               JOIN farm_auth_accounts a ON a.id = c.account_id
               WHERE c.status = 'active' AND a.status = 'active'
               ORDER BY c.id"""
        ).fetchall()
        if not candidates:
            raise ValueError("没有可加入场次的启用互刷部落")
        now = now_iso()
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO farm_rounds
                   (scheduled_at, business_time_kind, status, created_by, created_at, updated_at)
                   VALUES (?, ?, 'scheduled', ?, ?, ?)""",
                (scheduled_at, kind, int(actor["id"]), now, now),
            )
            round_id = int(cursor.lastrowid)
            self.conn.executemany(
                """INSERT INTO farm_round_clans
                   (round_id, clan_id, account_id_snapshot, clan_tag_snapshot,
                    clan_name_snapshot, score_before, registration_status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'not_registered', ?, ?)""",
                [
                    (
                        round_id, int(clan["id"]), int(clan["account_id"]),
                        clan["clan_tag"], clan["clan_name"], int(clan["score"]), now, now,
                    )
                    for clan in candidates
                ],
            )
            first_check_at = (
                datetime.fromisoformat(scheduled_at) + timedelta(minutes=5)
            ).isoformat(timespec="seconds")
            self.conn.executemany(
                """INSERT INTO farm_round_monitors
                   (round_id, clan_id, war_status, next_check_at, created_at, updated_at)
                   VALUES (?, ?, 'unchecked', ?, ?, ?)""",
                [
                    (round_id, int(clan["id"]), first_check_at, now, now)
                    for clan in candidates
                ],
            )
            self._audit(
                actor_id=int(actor["id"]), action="round.created", round_id=round_id,
                before=None,
                after={"scheduled_at": scheduled_at, "business_time_kind": kind,
                       "status": "scheduled", "clan_count": len(candidates)},
                created_at=now,
            )
        return self.get_round(round_id)

    def update_round(self, actor: dict, round_id: int, payload: dict) -> sqlite3.Row:
        _assert_manager(actor)
        row = self.get_round(round_id)
        if row is None:
            raise LookupError("互刷场次不存在")
        if row["status"] not in {"scheduled", "open"}:
            raise ValueError("当前场次状态不允许修改")
        scheduled_at = row["scheduled_at"]
        if "scheduled_at" in payload:
            if row["time_locked_at"]:
                raise ValueError("首次最终登记后不能修改统一时间")
            scheduled_at = normalize_scheduled_at(payload["scheduled_at"])
        kind = payload.get("business_time_kind", row["business_time_kind"])
        if kind != BUSINESS_TIME_KIND:
            raise ValueError("统一时间固定为开始搜战时间")
        next_status = payload.get("status", row["status"])
        if next_status not in {"scheduled", "open"}:
            raise ValueError("F3 只允许把场次设为 scheduled 或 open")
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """UPDATE farm_rounds
                   SET scheduled_at = ?, business_time_kind = ?, status = ?, updated_at = ?
                   WHERE id = ?""",
                (scheduled_at, kind, next_status, now, int(round_id)),
            )
            if scheduled_at != row["scheduled_at"]:
                first_check_at = (
                    datetime.fromisoformat(scheduled_at) + timedelta(minutes=5)
                ).isoformat(timespec="seconds")
                self.conn.execute(
                    """UPDATE farm_round_monitors
                       SET next_check_at = ?, updated_at = ?
                       WHERE round_id = ? AND war_status = 'unchecked'""",
                    (first_check_at, now, int(round_id)),
                )
            self._audit(
                actor_id=int(actor["id"]), action="round.updated", round_id=int(round_id),
                before={"scheduled_at": row["scheduled_at"],
                        "business_time_kind": row["business_time_kind"], "status": row["status"]},
                after={"scheduled_at": scheduled_at, "business_time_kind": kind,
                       "status": next_status}, created_at=now,
            )
        return self.get_round(round_id)

    def dashboard(self, actor: dict) -> dict:
        round_row = self.current_round()
        if round_row is None:
            clans = self.conn.execute(
                """SELECT * FROM farm_clans
                   WHERE account_id = ? AND status = 'active'
                   ORDER BY id""",
                (int(actor["id"]),),
            ).fetchall()
            return {
                "round": None,
                "registered_count": 0,
                "total_count": len(clans),
                "clans": [public_bound_clan(row) for row in clans],
            }
        clans = self._round_clans(int(round_row["id"]), account_id=int(actor["id"]))
        registered = sum(
            row["registration_status"] in FINAL_REGISTRATION_STATUSES for row in clans
        )
        return {
            "round": public_round(round_row),
            "registered_count": registered,
            "total_count": len(clans),
            "clans": [public_round_clan(row) for row in clans],
        }

    def results(self, actor: dict, round_id: int) -> dict:
        _assert_manager(actor)
        round_row = self.get_round(round_id)
        if round_row is None:
            raise LookupError("互刷场次不存在")
        clans = self._round_clans(int(round_id))
        registered = sum(
            row["registration_status"] in FINAL_REGISTRATION_STATUSES for row in clans
        )
        return {
            "round": public_round(round_row),
            "registered_count": registered,
            "total_count": len(clans),
            "clans": [public_round_clan(row) for row in clans],
        }

    def _round_clans(self, round_id: int, account_id: int | None = None) -> list[sqlite3.Row]:
        sql = """SELECT rc.*, c.score AS current_score
                 FROM farm_round_clans rc
                 JOIN farm_clans c ON c.id = rc.clan_id
                 WHERE rc.round_id = ?"""
        params: list[int] = [int(round_id)]
        if account_id is not None:
            sql += " AND rc.account_id_snapshot = ?"
            params.append(int(account_id))
        sql += " ORDER BY rc.clan_id"
        return self.conn.execute(sql, params).fetchall()

    def _audit(
        self,
        *,
        actor_id: int,
        action: str,
        round_id: int,
        before: dict | None,
        after: dict | None,
        created_at: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO farm_audit_logs
               (actor_account_id, action, entity_type, entity_id, before_json, after_json, created_at)
               VALUES (?, ?, 'farm_round', ?, ?, ?, ?)""",
            (
                actor_id, action, str(round_id),
                json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
                created_at,
            ),
        )
