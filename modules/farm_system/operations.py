"""互刷创建者纠错操作：反向流水撤销与整场取消。"""
from __future__ import annotations

import json
import sqlite3

from shared.db.connection import now_iso

from .registration import _SETTLEMENT_LOCK


class CreatorPermissionError(PermissionError):
    pass


def _assert_creator(actor: dict) -> None:
    if actor.get("role") != "creator":
        raise CreatorPermissionError("仅互刷系统创建者可以执行该操作")


def _reason(value: str) -> str:
    reason = str(value or "").strip()
    if len(reason) < 3 or len(reason) > 500:
        raise ValueError("撤销原因必须为 3-500 个字符")
    return reason


class FarmCreatorOperations:
    def __init__(self, conn: sqlite3.Connection, *, before_match_revoke=None):
        self.conn = conn
        self.before_match_revoke = before_match_revoke

    def revoke_match(self, actor: dict, match_id: int, reason: str) -> dict:
        _assert_creator(actor)
        clean_reason = _reason(reason)
        with _SETTLEMENT_LOCK:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                match = self._match(match_id)
                if match["status"] == "revoked":
                    self.conn.rollback()
                    return self._public_match(match, reused=True)
                now = now_iso()
                self._revoke_match_sql(match, actor, clean_reason, now)
                self._audit(
                    actor, "match.revoked", "farm_match", str(match_id),
                    {"status": "settled"},
                    {"status": "revoked", "reason": clean_reason}, now,
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self._public_match(self._match(match_id), reused=False)

    def cancel_round(self, actor: dict, round_id: int, reason: str) -> dict:
        _assert_creator(actor)
        clean_reason = _reason(reason)
        with _SETTLEMENT_LOCK:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                round_row = self.conn.execute(
                    "SELECT * FROM farm_rounds WHERE id = ?", (int(round_id),)
                ).fetchone()
                if round_row is None:
                    raise LookupError("互刷场次不存在")
                if round_row["status"] == "cancelled":
                    self.conn.rollback()
                    return {"round_id": int(round_id), "status": "cancelled", "reused": True}
                now = now_iso()
                matches = self.conn.execute(
                    """SELECT * FROM farm_matches
                       WHERE round_id = ? AND status = 'settled' ORDER BY id""",
                    (int(round_id),),
                ).fetchall()
                for index, match in enumerate(matches):
                    if self.before_match_revoke:
                        self.before_match_revoke(index, match)
                    self._revoke_match_sql(match, actor, clean_reason, now)
                self.conn.execute(
                    """UPDATE farm_rounds
                       SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?,
                           cancel_reason = ?, updated_at = ? WHERE id = ?""",
                    (now, int(actor["id"]), clean_reason, now, int(round_id)),
                )
                self._audit(
                    actor, "round.cancelled", "farm_round", str(round_id),
                    {"status": round_row["status"]},
                    {"status": "cancelled", "reason": clean_reason,
                     "revoked_match_count": len(matches)}, now,
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return {"round_id": int(round_id), "status": "cancelled", "reused": False}

    def reopen_match(self, actor: dict, match_id: int) -> dict:
        """Explicitly make both sides of a revoked match registerable again."""
        _assert_creator(actor)
        with _SETTLEMENT_LOCK:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                match = self._match(match_id)
                if match["status"] != "revoked":
                    raise ValueError("只有已撤销的匹配可以重新开放")
                round_row = self.conn.execute(
                    "SELECT * FROM farm_rounds WHERE id = ?", (int(match["round_id"]),)
                ).fetchone()
                if round_row is None:
                    raise LookupError("互刷场次不存在")
                if round_row["status"] == "cancelled":
                    raise ValueError("已撤销整场不能重新开放单个匹配")
                affected = self.conn.execute(
                    """SELECT clan_id FROM farm_round_clans
                       WHERE round_id = ? AND match_id = ?
                         AND registration_status = 'revoked'
                       ORDER BY clan_id""",
                    (int(match["round_id"]), int(match_id)),
                ).fetchall()
                if not affected:
                    reopened = self.conn.execute(
                        """SELECT 1 FROM farm_audit_logs
                           WHERE action='match.reopened' AND entity_type='farm_match'
                             AND entity_id=? LIMIT 1""",
                        (str(match_id),),
                    ).fetchone()
                    if reopened:
                        self.conn.rollback()
                        return {
                            "match_id": int(match_id),
                            "round_id": int(match["round_id"]),
                            "status": "reopened",
                            "round_status": round_row["status"],
                            "clan_ids": [],
                            "reused": True,
                        }
                    raise ValueError("已撤销匹配没有可重新开放的部落")
                now = now_iso()
                clan_ids = [int(row["clan_id"]) for row in affected]
                self.conn.execute(
                    """UPDATE farm_round_clans
                       SET registration_status='not_registered', match_id=NULL,
                           opponent_tag=NULL, opponent_name=NULL, result=NULL,
                           score_after=NULL, registered_at=NULL, registered_by=NULL,
                           last_error='已由创建者重新开放', updated_at=?
                       WHERE round_id=? AND match_id=?
                         AND registration_status='revoked'""",
                    (now, int(match["round_id"]), int(match_id)),
                )
                total, settled = self.conn.execute(
                    """SELECT COUNT(*), SUM(CASE WHEN registration_status IN
                           ('internal_matched', 'match_failed') THEN 1 ELSE 0 END)
                       FROM farm_round_clans WHERE round_id=?""",
                    (int(match["round_id"]),),
                ).fetchone()
                next_status = (
                    "completed" if total and int(settled or 0) == int(total)
                    else "partially_registered" if int(settled or 0) > 0
                    else "open"
                )
                self.conn.execute(
                    "UPDATE farm_rounds SET status=?, updated_at=? WHERE id=?",
                    (next_status, now, int(match["round_id"])),
                )
                self._audit(
                    actor, "match.reopened", "farm_match", str(match_id),
                    {"status": "revoked"},
                    {"status": "reopened", "clan_ids": clan_ids,
                     "round_status": next_status}, now,
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return {
            "match_id": int(match_id),
            "round_id": int(match["round_id"]),
            "status": "reopened",
            "round_status": next_status,
            "clan_ids": clan_ids,
            "reused": False,
        }

    def _revoke_match_sql(self, match, actor, reason: str, now: str) -> None:
        base_entries = self.conn.execute(
            """SELECT * FROM farm_score_ledger
               WHERE match_id = ? AND entry_type IN ('win', 'loss') ORDER BY id""",
            (int(match["id"]),),
        ).fetchall()
        for entry in base_entries:
            existing = self.conn.execute(
                """SELECT id FROM farm_score_ledger
                   WHERE entry_type = 'reversal' AND reverses_entry_id = ?""",
                (int(entry["id"]),),
            ).fetchone()
            if existing is not None:
                continue
            clan = self.conn.execute(
                "SELECT score FROM farm_clans WHERE id = ?", (int(entry["clan_id"]),)
            ).fetchone()
            if clan is None:
                raise LookupError("积分部落不存在")
            before = int(clan["score"])
            delta = -int(entry["delta"])
            after = before + delta
            self.conn.execute(
                """INSERT INTO farm_score_ledger
                   (clan_id, round_id, match_id, entry_type, delta,
                    balance_before, balance_after, reason, created_by, created_at,
                    reverses_entry_id)
                   VALUES (?, ?, ?, 'reversal', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(entry["clan_id"]), int(entry["round_id"]), int(entry["match_id"]),
                    delta, before, after, reason, int(actor["id"]), now, int(entry["id"]),
                ),
            )
            self.conn.execute(
                "UPDATE farm_clans SET score = ?, updated_at = ? WHERE id = ?",
                (after, now, int(entry["clan_id"])),
            )
        self.conn.execute(
            """UPDATE farm_round_clans
               SET registration_status = 'revoked', score_after = score_before,
                   last_error = ?, updated_at = ?
               WHERE round_id = ? AND match_id = ?""",
            (f"已撤销：{reason}", now, int(match["round_id"]), int(match["id"])),
        )
        self.conn.execute(
            """UPDATE farm_matches
               SET status = 'revoked', revoked_at = ?, revoked_by = ?, revoke_reason = ?
               WHERE id = ?""",
            (now, int(actor["id"]), reason, int(match["id"])),
        )

    def _match(self, match_id: int):
        row = self.conn.execute(
            "SELECT * FROM farm_matches WHERE id = ?", (int(match_id),)
        ).fetchone()
        if row is None:
            raise LookupError("互刷匹配不存在")
        return row

    @staticmethod
    def _public_match(row, *, reused: bool) -> dict:
        return {
            "match_id": int(row["id"]),
            "round_id": int(row["round_id"]),
            "match_type": row["match_type"],
            "status": row["status"],
            "revoke_reason": row["revoke_reason"],
            "reused": reused,
        }

    def _audit(self, actor, action, entity_type, entity_id, before, after, now) -> None:
        self.conn.execute(
            """INSERT INTO farm_audit_logs
               (actor_account_id, action, entity_type, entity_id,
                before_json, after_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                int(actor["id"]), action, entity_type, entity_id,
                json.dumps(before, ensure_ascii=False, sort_keys=True),
                json.dumps(after, ensure_ascii=False, sort_keys=True), now,
            ),
        )
