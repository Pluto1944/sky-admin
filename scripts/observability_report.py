#!/usr/bin/env python3
"""Read-only scheduler and external-request observability report."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402

load_env()

import config  # noqa: E402


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _request_summary(conn: sqlite3.Connection, since: str) -> list[dict]:
    if not _table_exists(conn, "external_request_events"):
        return []
    rows = conn.execute(
        """SELECT provider, operation, outcome, http_status, duration_ms
           FROM external_request_events
           WHERE started_at >= ?
           ORDER BY provider, operation""",
        (since,),
    ).fetchall()
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[(row["provider"], row["operation"])].append(row)

    result = []
    for (provider, operation), items in sorted(grouped.items()):
        durations = [int(item["duration_ms"] or 0) for item in items]
        failures = sum(
            item["outcome"] not in {"success", "expected_http_status"}
            for item in items
        )
        rate_limited = sum(
            item["outcome"] == "rate_limited" or item["http_status"] == 429
            for item in items
        )
        result.append({
            "provider": provider,
            "operation": operation,
            "requests": len(items),
            "failures": failures,
            "rate_limited": rate_limited,
            "success_rate": round((len(items) - failures) / len(items), 4),
            "avg_duration_ms": round(sum(durations) / len(durations)),
            "p95_duration_ms": _percentile(durations, 0.95),
            "max_duration_ms": max(durations),
        })
    return result


def _job_summary(conn: sqlite3.Connection, since: str) -> list[dict]:
    if not _table_exists(conn, "sync_job_runs"):
        return []
    rows = conn.execute(
        """SELECT job_id, status, duration_ms, external_request_count,
                  external_failure_count, rate_limited_count, started_at
           FROM sync_job_runs
           WHERE started_at >= ?
           ORDER BY job_id, started_at""",
        (since,),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[row["job_id"]].append(row)

    result = []
    for job_id, items in sorted(grouped.items()):
        durations = [
            int(item["duration_ms"])
            for item in items
            if item["duration_ms"] is not None
        ]
        result.append({
            "job_id": job_id,
            "runs": len(items),
            "failed_runs": sum(item["status"] == "failed" for item in items),
            "running_runs": sum(item["status"] == "running" for item in items),
            "external_requests": sum(int(item["external_request_count"] or 0) for item in items),
            "external_failures": sum(int(item["external_failure_count"] or 0) for item in items),
            "rate_limited": sum(int(item["rate_limited_count"] or 0) for item in items),
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "p95_duration_ms": _percentile(durations, 0.95),
            "max_duration_ms": max(durations) if durations else None,
            "last_started_at": max(item["started_at"] for item in items),
        })
    return result


def _freshness(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    if _table_exists(conn, "current_war_cache"):
        result["current_wars"] = [dict(row) for row in conn.execute(
            """SELECT clan_tag, clan_name, status,
                      COALESCE(last_success_at, updated_at) AS last_success_at,
                      attempted_at, failure_count
               FROM current_war_cache ORDER BY clan_tag"""
        ).fetchall()]
    if _table_exists(conn, "clan_profile_cache"):
        result["clan_profiles"] = [dict(row) for row in conn.execute(
            """SELECT clan_tag, clan_name, status, updated_at, attempted_at
               FROM clan_profile_cache ORDER BY clan_tag"""
        ).fetchall()]
    if _table_exists(conn, "accounts"):
        result["member_profiles"] = [dict(row) for row in conn.execute(
            """SELECT clan_tag, COUNT(*) AS members, MAX(last_synced_at) AS last_synced_at
               FROM accounts
               WHERE clan_tag IS NOT NULL AND membership_status = 'member'
               GROUP BY clan_tag ORDER BY clan_tag"""
        ).fetchall()]
    if _table_exists(conn, "cwl_live_group_cache"):
        result["cwl_groups"] = [dict(row) for row in conn.execute(
            """SELECT period, clan_tag, status, raw_status, updated_at, attempted_at
               FROM cwl_live_group_cache
               WHERE period = (SELECT MAX(period) FROM cwl_live_group_cache)
               ORDER BY clan_tag"""
        ).fetchall()]
    return result


def build_report(
    conn: sqlite3.Connection,
    *,
    hours: int = 24,
    now: datetime | None = None,
) -> dict:
    if hours <= 0:
        raise ValueError("hours must be positive")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    since = (current - timedelta(hours=hours)).isoformat(timespec="seconds")
    return {
        "generated_at": current.isoformat(timespec="seconds"),
        "window_hours": hours,
        "since": since,
        "requests": _request_summary(conn, since),
        "jobs": _job_summary(conn, since),
        "freshness": _freshness(conn),
    }


def _print_text(report: dict) -> None:
    print(f"观测窗口：最近 {report['window_hours']} 小时（自 {report['since']}）")
    print("\n外部请求")
    if not report["requests"]:
        print("  暂无观测数据")
    for item in report["requests"]:
        print(
            f"  {item['provider']}/{item['operation']}: {item['requests']} 次，"
            f"失败 {item['failures']}，429 {item['rate_limited']}，"
            f"成功率 {item['success_rate']:.1%}，p95 {item['p95_duration_ms']}ms"
        )

    print("\n调度任务")
    if not report["jobs"]:
        print("  暂无观测数据")
    for item in report["jobs"]:
        print(
            f"  {item['job_id']}: {item['runs']} 轮，失败 {item['failed_runs']}，"
            f"未完成 {item['running_runs']}，"
            f"外部请求 {item['external_requests']}，p95 {item['p95_duration_ms']}ms"
        )

    print("\n数据新鲜度")
    for name, rows in report["freshness"].items():
        print(f"  {name}: {len(rows)} 条")
        for row in rows:
            identity = row.get("clan_tag") or row.get("period") or "-"
            state = row.get("status") or row.get("raw_status") or "-"
            updated = (
                row.get("last_success_at")
                or row.get("last_synced_at")
                or row.get("updated_at")
                or "-"
            )
            print(f"    {identity}: {state}，最近成功/更新 {updated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="只读输出调度与外部请求观测报告")
    parser.add_argument("--db", default=config.DB_PATH, help="SQLite 数据库路径")
    parser.add_argument("--hours", type=int, default=24, help="统计窗口小时数")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        raise SystemExit(f"数据库不存在：{db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = build_report(conn, hours=args.hours)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text(report)


if __name__ == "__main__":
    main()
