#!/usr/bin/env python3
"""只读检查互刷匹配、积分流水和场次一致性。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH  # noqa: E402


def audit_farm_system(conn: sqlite3.Connection) -> list[dict]:
    issues: list[dict] = []
    clans = conn.execute("SELECT id, clan_tag, score FROM farm_clans ORDER BY id").fetchall()
    for clan in clans:
        entries = conn.execute(
            "SELECT * FROM farm_score_ledger WHERE clan_id = ? ORDER BY id",
            (int(clan["id"]),),
        ).fetchall()
        previous_after = None
        for entry in entries:
            before = int(entry["balance_before"])
            after = int(entry["balance_after"])
            delta = int(entry["delta"])
            if after != before + delta:
                issues.append({"code": "ledger_arithmetic", "ledger_id": int(entry["id"])})
            if previous_after is not None and before != previous_after:
                issues.append({
                    "code": "ledger_chain", "clan_id": int(clan["id"]),
                    "ledger_id": int(entry["id"]),
                })
            previous_after = after
        expected = previous_after if previous_after is not None else 0
        if int(clan["score"]) != expected:
            issues.append({
                "code": "score_current_mismatch", "clan_id": int(clan["id"]),
                "clan_tag": clan["clan_tag"], "expected": expected,
                "actual": int(clan["score"]),
            })

    matches = conn.execute("SELECT * FROM farm_matches ORDER BY id").fetchall()
    for match in matches:
        match_id = int(match["id"])
        base_count = conn.execute(
            """SELECT COUNT(*) FROM farm_score_ledger
               WHERE match_id = ? AND entry_type IN ('win', 'loss')""",
            (match_id,),
        ).fetchone()[0]
        result_count = conn.execute(
            "SELECT COUNT(*) FROM farm_round_clans WHERE match_id = ?", (match_id,)
        ).fetchone()[0]
        expected_base = 2 if match["match_type"] == "internal" else 0
        expected_results = 2 if match["match_type"] == "internal" else 1
        if int(base_count) != expected_base:
            issues.append({
                "code": "match_base_ledger_count", "match_id": match_id,
                "expected": expected_base, "actual": int(base_count),
            })
        if int(result_count) != expected_results:
            issues.append({
                "code": "match_result_count", "match_id": match_id,
                "expected": expected_results, "actual": int(result_count),
            })
        if match["status"] == "revoked":
            reversal_count = conn.execute(
                """SELECT COUNT(*) FROM farm_score_ledger
                   WHERE match_id = ? AND entry_type = 'reversal'""",
                (match_id,),
            ).fetchone()[0]
            if int(reversal_count) != expected_base:
                issues.append({
                    "code": "reversal_count", "match_id": match_id,
                    "expected": expected_base, "actual": int(reversal_count),
                })

    rounds = conn.execute(
        "SELECT id, status FROM farm_rounds WHERE status IN ('completed', 'cancelled') ORDER BY id"
    ).fetchall()
    for round_row in rounds:
        total, resolved = conn.execute(
            """SELECT COUNT(*), SUM(CASE WHEN registration_status IN
                   ('internal_matched', 'match_failed', 'revoked') THEN 1 ELSE 0 END)
               FROM farm_round_clans WHERE round_id = ?""",
            (int(round_row["id"]),),
        ).fetchone()
        if int(total or 0) != int(resolved or 0):
            issues.append({
                "code": "round_resolution_count", "round_id": int(round_row["id"]),
                "status": round_row["status"], "total": int(total or 0),
                "resolved": int(resolved or 0),
            })
    return issues


def _default_db_path() -> Path:
    path = Path(DB_PATH)
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检查互刷系统积分与匹配一致性")
    parser.add_argument("--db-path", type=Path, default=_default_db_path())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    path = args.db_path.resolve()
    if not path.is_file():
        print(f"数据库不存在：{path}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        issues = audit_farm_system(conn)
    finally:
        conn.close()
    result = {"ok": not issues, "issue_count": len(issues), "issues": issues}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif issues:
        print(f"发现 {len(issues)} 项异常")
        for issue in issues:
            print(json.dumps(issue, ensure_ascii=False, sort_keys=True))
    else:
        print("互刷系统积分、匹配与场次一致性检查通过")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
