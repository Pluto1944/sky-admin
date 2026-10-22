"""互刷单部落登记、匹配与原子积分结算。"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from modules.coc_sync.current_war import normalize_current_war
from modules.coc_sync.official.api_client import CocApiError
from shared.db.connection import now_iso

from .rounds import FINAL_REGISTRATION_STATUSES, NON_REGISTERABLE_STATUSES
from .scoring import decide_match
from .tags import coc_tag_key


_SETTLEMENT_LOCK = threading.RLock()


class RegistrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def parse_coc_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _time_tolerance_seconds() -> int:
    try:
        value = int(os.environ.get("FARM_SYSTEM_TIME_TOLERANCE_SECONDS", "2700"))
    except ValueError:
        value = 2700
    return max(60, min(value, 7200))


class FarmRegistrationService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        coc_client,
        *,
        choose_tie_winner: Callable[[tuple[int, int]], int] | None = None,
        before_second_ledger: Callable[[], None] | None = None,
    ):
        self.conn = conn
        self.coc_client = coc_client
        self.choose_tie_winner = choose_tie_winner or random.choice
        self.before_second_ledger = before_second_ledger

    def register(self, actor: dict, round_id: int, clan_tag: str) -> dict:
        round_row = self._round(round_id)
        source = self._round_clan(round_id, clan_tag)
        if int(source["account_id_snapshot"]) != int(actor["id"]):
            raise RegistrationError("clan_not_owned", "该部落不属于当前账号", status_code=404)
        if source["registration_status"] in NON_REGISTERABLE_STATUSES:
            return self._result_payload(round_id, int(source["clan_id"]), reused=True)
        if round_row["status"] not in {"open", "partially_registered"}:
            raise RegistrationError("round_not_open", "当前场次尚未开放登记", status_code=409)
        if round_row["business_time_kind"] != "preparation_start":
            raise RegistrationError(
                "time_kind_invalid", "本轮统一时间配置异常，不能登记", status_code=409
            )

        attempt_started = time.monotonic()
        if not self._set_retry_state(source, "registering", None):
            return self._result_payload(round_id, int(source["clan_id"]), reused=True)
        try:
            raw = self.coc_client.get_current_war(source["clan_tag_snapshot"])
        except CocApiError as exc:
            return self._record_retry(
                actor, source, "fetch_failed", "coc_api_error", str(exc),
                duration_ms=self._duration_ms(attempt_started),
            )
        except Exception as exc:
            return self._record_retry(
                actor, source, "fetch_failed", "unexpected_fetch_error", str(exc),
                duration_ms=self._duration_ms(attempt_started),
            )

        normalized = normalize_current_war(
            raw,
            {"tag": source["clan_tag_snapshot"], "name": source["clan_name_snapshot"],
             "category": "farm"},
        )
        summary = self._official_summary(normalized)
        duration_ms = self._duration_ms(attempt_started)
        if normalized["status"] == "not_in_war":
            return self._record_retry(
                actor, source, "not_in_war", "not_in_war", "当前尚未搜到对手",
                duration_ms=duration_ms, summary=summary,
            )
        if normalized["status"] == "cwl":
            return self._record_retry(
                actor, source, "war_mismatch", "cwl_not_supported", "当前战争为部落战联赛",
                duration_ms=duration_ms, summary=summary,
            )
        if normalized["status"] not in {"preparation", "in_war", "war_ended"}:
            return self._record_retry(
                actor, source, "fetch_failed", "unsupported_war_state", "官方战争状态不可用",
                duration_ms=duration_ms, summary=summary,
            )

        selected_field = "preparation_start_time"
        official_time = parse_coc_time(normalized.get(selected_field))
        scheduled_time = datetime.fromisoformat(round_row["scheduled_at"]).astimezone(timezone.utc)
        if official_time is None:
            return self._record_retry(
                actor, source, "fetch_failed", "official_time_missing", "官方战争时间缺失或无法解析",
                duration_ms=duration_ms, summary=summary,
                official_time_kind=selected_field,
            )
        if abs((official_time - scheduled_time).total_seconds()) > _time_tolerance_seconds():
            return self._record_retry(
                actor, source, "war_mismatch", "war_time_mismatch", "当前战争不属于本轮统一时间",
                duration_ms=duration_ms, summary=summary,
                official_time_kind=selected_field, official_time=official_time.isoformat(),
            )

        opponent = normalized.get("opponent") or {}
        opponent_key = coc_tag_key(opponent.get("tag"))
        if not opponent_key:
            return self._record_retry(
                actor, source, "fetch_failed", "opponent_missing", "官方响应缺少对手部落",
                duration_ms=duration_ms, summary=summary,
                official_time_kind=selected_field, official_time=official_time.isoformat(),
            )
        target = self._round_clan_optional(round_id, opponent_key)
        if target is None:
            return self._settle_external(
                actor, round_row, source, opponent_key, opponent.get("name"),
                duration_ms=duration_ms, summary=summary,
                official_time_kind=selected_field, official_time=official_time.isoformat(),
            )
        return self._settle_internal(
            actor, round_row, source, target,
            duration_ms=duration_ms, summary=summary,
            official_time_kind=selected_field, official_time=official_time.isoformat(),
        )

    def _settle_internal(
        self, actor, round_row, source, target, *, duration_ms, summary,
        official_time_kind, official_time,
    ) -> dict:
        if int(source["clan_id"]) == int(target["clan_id"]):
            return self._record_retry(
                actor, source, "fetch_failed", "self_opponent", "官方对手不能是本方部落",
                duration_ms=duration_ms, summary=summary,
                official_time_kind=official_time_kind, official_time=official_time,
            )
        ordered = sorted((source, target), key=lambda row: coc_tag_key(row["clan_tag_snapshot"]))
        clan_a, clan_b = ordered
        pair_key = f"{coc_tag_key(clan_a['clan_tag_snapshot'])}|{coc_tag_key(clan_b['clan_tag_snapshot'])}"
        with _SETTLEMENT_LOCK:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                fresh_source = self._round_clan_by_id(int(round_row["id"]), int(source["clan_id"]))
                if fresh_source["registration_status"] in NON_REGISTERABLE_STATUSES:
                    self.conn.rollback()
                    return self._result_payload(
                        int(round_row["id"]), int(source["clan_id"]), reused=True
                    )
                fresh_target = self._round_clan_by_id(int(round_row["id"]), int(target["clan_id"]))
                if fresh_target["registration_status"] in NON_REGISTERABLE_STATUSES:
                    raise RegistrationError(
                        "opponent_already_final", "对手已经存在不一致的最终登记结果", status_code=409
                    )
                self._assert_snapshot_balance(clan_a)
                self._assert_snapshot_balance(clan_b)
                decision = decide_match(
                    int(clan_a["clan_id"]), int(clan_a["score_before"]),
                    int(clan_b["clan_id"]), int(clan_b["score_before"]),
                    choose_tie_winner=self.choose_tie_winner,
                )
                now = now_iso()
                cursor = self.conn.execute(
                    """INSERT INTO farm_matches
                       (round_id, match_type, pair_key, clan_a_id, clan_b_id,
                        winner_clan_id, loser_clan_id, score_a_before, score_b_before,
                        tie_break_used, tie_break_value, status, settled_at, settled_by)
                       VALUES (?, 'internal', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'settled', ?, ?)""",
                    (
                        int(round_row["id"]), pair_key, int(clan_a["clan_id"]),
                        int(clan_b["clan_id"]), decision.winner_clan_id,
                        decision.loser_clan_id, int(clan_a["score_before"]),
                        int(clan_b["score_before"]), int(decision.tie_break_used),
                        decision.tie_break_value, now, int(actor["id"]),
                    ),
                )
                match_id = int(cursor.lastrowid)
                for index, clan in enumerate((clan_a, clan_b)):
                    clan_id = int(clan["clan_id"])
                    before = int(clan["score_before"])
                    won = clan_id == decision.winner_clan_id
                    delta = 1 if won else -1
                    entry_type = "win" if won else "loss"
                    if index == 1 and self.before_second_ledger:
                        self.before_second_ledger()
                    self.conn.execute(
                        """INSERT INTO farm_score_ledger
                           (clan_id, round_id, match_id, entry_type, delta,
                            balance_before, balance_after, reason, created_by, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'internal_match', ?, ?)""",
                        (
                            clan_id, int(round_row["id"]), match_id, entry_type, delta,
                            before, before + delta, int(actor["id"]), now,
                        ),
                    )
                    self.conn.execute(
                        "UPDATE farm_clans SET score = ?, updated_at = ? WHERE id = ?",
                        (before + delta, now, clan_id),
                    )
                    opponent = clan_b if clan_id == int(clan_a["clan_id"]) else clan_a
                    self.conn.execute(
                        """UPDATE farm_round_clans
                           SET registration_status = 'internal_matched', match_id = ?,
                               opponent_tag = ?, opponent_name = ?, result = ?, score_after = ?,
                               registered_at = ?, registered_by = ?, last_attempt_at = ?,
                               last_error = NULL, updated_at = ?
                           WHERE round_id = ? AND clan_id = ?""",
                        (
                            match_id, opponent["clan_tag_snapshot"], opponent["clan_name_snapshot"],
                            "win" if won else "loss", before + delta, now, int(actor["id"]),
                            now, now, int(round_row["id"]), clan_id,
                        ),
                    )
                self._record_attempt_sql(
                    actor, source, "internal_matched", duration_ms, summary,
                    official_time_kind=official_time_kind, official_time=official_time,
                )
                self._finalize_round(int(round_row["id"]), now)
                self._audit_match(actor, match_id, pair_key, decision, now)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self._result_payload(int(round_row["id"]), int(source["clan_id"]), reused=False)

    def _settle_external(
        self, actor, round_row, source, opponent_tag, opponent_name, *, duration_ms,
        summary, official_time_kind, official_time,
    ) -> dict:
        pair_key = f"external:{coc_tag_key(source['clan_tag_snapshot'])}"
        with _SETTLEMENT_LOCK:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                fresh = self._round_clan_by_id(int(round_row["id"]), int(source["clan_id"]))
                if fresh["registration_status"] in NON_REGISTERABLE_STATUSES:
                    self.conn.rollback()
                    return self._result_payload(
                        int(round_row["id"]), int(source["clan_id"]), reused=True
                    )
                self._assert_snapshot_balance(fresh)
                now = now_iso()
                cursor = self.conn.execute(
                    """INSERT INTO farm_matches
                       (round_id, match_type, pair_key, clan_a_id, opponent_tag, opponent_name,
                        score_a_before, status, settled_at, settled_by)
                       VALUES (?, 'failed_external', ?, ?, ?, ?, ?, 'settled', ?, ?)""",
                    (
                        int(round_row["id"]), pair_key, int(source["clan_id"]),
                        opponent_tag, opponent_name, int(source["score_before"]), now,
                        int(actor["id"]),
                    ),
                )
                match_id = int(cursor.lastrowid)
                self.conn.execute(
                    """UPDATE farm_round_clans
                       SET registration_status = 'match_failed', match_id = ?, opponent_tag = ?,
                           opponent_name = ?, result = 'match_failed', score_after = score_before,
                           registered_at = ?, registered_by = ?, last_attempt_at = ?,
                           last_error = NULL, updated_at = ?
                       WHERE round_id = ? AND clan_id = ?""",
                    (
                        match_id, opponent_tag, opponent_name, now, int(actor["id"]), now, now,
                        int(round_row["id"]), int(source["clan_id"]),
                    ),
                )
                self._record_attempt_sql(
                    actor, source, "match_failed", duration_ms, summary,
                    official_time_kind=official_time_kind, official_time=official_time,
                )
                self._finalize_round(int(round_row["id"]), now)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self._result_payload(int(round_row["id"]), int(source["clan_id"]), reused=False)

    def _record_retry(
        self, actor, source, status, error_code, message, *, duration_ms,
        summary=None, official_time_kind=None, official_time=None,
    ) -> dict:
        now = now_iso()
        clean_message = str(message or "")[:500]
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE farm_round_clans
                   SET registration_status = ?, last_attempt_at = ?, last_error = ?, updated_at = ?
                   WHERE round_id = ? AND clan_id = ?
                     AND registration_status NOT IN ('internal_matched', 'match_failed', 'revoked')""",
                (
                    status, now, clean_message, now, int(source["round_id"]),
                    int(source["clan_id"]),
                ),
            )
            if cursor.rowcount == 0:
                return self._result_payload(
                    int(source["round_id"]), int(source["clan_id"]), reused=True
                )
            self._record_attempt_sql(
                actor, source, status, duration_ms, summary or {},
                error_code=error_code, error_message=clean_message,
                official_time_kind=official_time_kind, official_time=official_time,
            )
        return self._result_payload(
            int(source["round_id"]), int(source["clan_id"]), reused=False
        )

    def _record_attempt_sql(
        self, actor, source, outcome, duration_ms, summary, *, error_code=None,
        error_message=None, official_time_kind=None, official_time=None,
    ) -> None:
        opponent = summary.get("opponent") or {}
        self.conn.execute(
            """INSERT INTO farm_registration_attempts
               (round_id, clan_id, requested_by, outcome, official_state,
                official_war_type, official_time_kind, official_time,
                opponent_tag, opponent_name, error_code, error_message,
                duration_ms, summary_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(source["round_id"]), int(source["clan_id"]), int(actor["id"]), outcome,
                summary.get("state"), summary.get("war_type"), official_time_kind,
                official_time, opponent.get("tag"), opponent.get("name"), error_code,
                error_message, int(duration_ms),
                json.dumps(summary, ensure_ascii=False, sort_keys=True), now_iso(),
            ),
        )

    def _set_retry_state(self, source, status, error) -> bool:
        now = now_iso()
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE farm_round_clans
                   SET registration_status = ?, last_attempt_at = ?, last_error = ?, updated_at = ?
                   WHERE round_id = ? AND clan_id = ?
                     AND registration_status NOT IN ('internal_matched', 'match_failed', 'revoked')""",
                (status, now, error, now, int(source["round_id"]), int(source["clan_id"])),
            )
        return cursor.rowcount > 0

    def _finalize_round(self, round_id: int, now: str) -> None:
        total, final = self.conn.execute(
            """SELECT COUNT(*), SUM(CASE WHEN registration_status IN
                   ('internal_matched', 'match_failed') THEN 1 ELSE 0 END)
               FROM farm_round_clans WHERE round_id = ?""",
            (int(round_id),),
        ).fetchone()
        status = "completed" if total and int(final or 0) == int(total) else "partially_registered"
        self.conn.execute(
            """UPDATE farm_rounds
               SET status = ?, time_locked_at = COALESCE(time_locked_at, ?), updated_at = ?
               WHERE id = ?""",
            (status, now, now, int(round_id)),
        )

    def _assert_snapshot_balance(self, row) -> None:
        current = self.conn.execute(
            "SELECT score FROM farm_clans WHERE id = ?", (int(row["clan_id"]),)
        ).fetchone()
        if current is None or int(current["score"]) != int(row["score_before"]):
            raise RegistrationError(
                "score_out_of_sync", "部落当前积分与本轮快照不一致，已停止结算", status_code=409
            )

    def _round(self, round_id: int):
        row = self.conn.execute(
            "SELECT * FROM farm_rounds WHERE id = ?", (int(round_id),)
        ).fetchone()
        if row is None:
            raise RegistrationError("round_not_found", "互刷场次不存在", status_code=404)
        return row

    def _round_clan(self, round_id: int, clan_tag: str):
        row = self._round_clan_optional(round_id, clan_tag)
        if row is None:
            raise RegistrationError("clan_not_found", "部落不在当前场次中", status_code=404)
        return row

    def _round_clan_optional(self, round_id: int, clan_tag: str):
        key = coc_tag_key(clan_tag)
        rows = self.conn.execute(
            """SELECT rc.*, c.score AS current_score FROM farm_round_clans rc
               JOIN farm_clans c ON c.id = rc.clan_id WHERE rc.round_id = ?""",
            (int(round_id),),
        ).fetchall()
        return next(
            (row for row in rows if coc_tag_key(row["clan_tag_snapshot"]) == key), None
        )

    def _round_clan_by_id(self, round_id: int, clan_id: int):
        return self.conn.execute(
            """SELECT rc.*, c.score AS current_score FROM farm_round_clans rc
               JOIN farm_clans c ON c.id = rc.clan_id
               WHERE rc.round_id = ? AND rc.clan_id = ?""",
            (int(round_id), int(clan_id)),
        ).fetchone()

    def _result_payload(self, round_id: int, clan_id: int, *, reused: bool) -> dict:
        row = self._round_clan_by_id(round_id, clan_id)
        return {
            "round_id": int(round_id),
            "clan_id": int(clan_id),
            "clan_tag": row["clan_tag_snapshot"],
            "clan_name": row["clan_name_snapshot"],
            "registration_status": row["registration_status"],
            "opponent_tag": row["opponent_tag"],
            "opponent_name": row["opponent_name"],
            "result": row["result"],
            "score_before": int(row["score_before"]),
            "score_after": row["score_after"],
            "last_error": row["last_error"],
            "reused": bool(reused),
        }

    @staticmethod
    def _official_summary(normalized: dict) -> dict:
        opponent = normalized.get("opponent") or {}
        return {
            "state": normalized.get("state"),
            "status": normalized.get("status"),
            "war_type": normalized.get("war_type"),
            "preparation_start_time": normalized.get("preparation_start_time"),
            "start_time": normalized.get("start_time"),
            "end_time": normalized.get("end_time"),
            "opponent": {"tag": opponent.get("tag"), "name": opponent.get("name")},
        }

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    def _audit_match(self, actor, match_id, pair_key, decision, now) -> None:
        self.conn.execute(
            """INSERT INTO farm_audit_logs
               (actor_account_id, action, entity_type, entity_id, after_json, created_at)
               VALUES (?, 'match.settled', 'farm_match', ?, ?, ?)""",
            (
                int(actor["id"]), str(match_id),
                json.dumps(
                    {"pair_key": pair_key, "winner_clan_id": decision.winner_clan_id,
                     "loser_clan_id": decision.loser_clan_id,
                     "tie_break_used": decision.tie_break_used},
                    ensure_ascii=False, sort_keys=True,
                ),
                now,
            ),
        )
