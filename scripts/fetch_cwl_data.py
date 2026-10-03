"""从完整本地 CWL 原始档案重建 ``league_results`` 投影。

此脚本不访问 ClashKing 或其他聚合 API，也不导入只含汇总数字的 JSON。
``league_results`` 只能由 ``cwl_live_group_cache`` 与
``cwl_live_war_cache`` 中完整的官方逐场档案生成；历史资料应使用
``scripts/backfill_cwl_live.py`` 回填这些档案后再执行本脚本。

``--period`` 是 CWL 实际发生月，例如 ``2026-08``。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402

load_env()

from config import DB_PATH  # noqa: E402
from modules.coc_sync.cwl_live import group_war_tags  # noqa: E402
from modules.coc_sync.cwl_projection import (  # noqa: E402
    group_raw_status,
    rebuild_league_results,
)
from modules.coc_sync.official.mapper import normalize_tag  # noqa: E402
from shared.db.connection import Database  # noqa: E402


def rebuild_period_from_raw(period: str) -> tuple[int, int, int]:
    """从本地完整 CWL 档案重建一个月投影，不访问外部 API。

    返回 ``(完整分组数, 写入行数, 不完整分组数)``。不完整分组不会改写其
    既有投影，避免因短暂缺档把已验证的月度统计清空。
    """
    db = Database(DB_PATH)
    db.init_schema()
    teams = [dict(row) for row in db.conn.execute(
        """SELECT period, team_index, team_alias, team_name, clan_tag,
                  category, member_count, league_level
           FROM league_teams
           WHERE period = ? AND category IN ('combat', 'shell')
           ORDER BY team_index""",
        (period,),
    ).fetchall()]
    if not teams:
        db.close()
        return 0, 0, 0

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    complete = written = incomplete = 0
    try:
        db.conn.execute("BEGIN IMMEDIATE")
        for team in teams:
            clan_tag = normalize_tag(team.get("clan_tag"))
            row = db.conn.execute(
                "SELECT data_json FROM cwl_live_group_cache WHERE period = ? AND clan_tag = ?",
                (period, clan_tag),
            ).fetchone()
            if not row or not row["data_json"]:
                incomplete += 1
                continue
            try:
                group = json.loads(row["data_json"])
            except (TypeError, json.JSONDecodeError):
                incomplete += 1
                continue

            tags = group_war_tags(group)
            wars: dict[str, dict] = {}
            if tags:
                placeholders = ",".join("?" for _ in tags)
                for war_row in db.conn.execute(
                    f"SELECT war_tag, data_json FROM cwl_live_war_cache WHERE war_tag IN ({placeholders})",
                    tags,
                ):
                    try:
                        wars[normalize_tag(war_row["war_tag"])] = json.loads(
                            war_row["data_json"] or "{}"
                        )
                    except (TypeError, json.JSONDecodeError):
                        continue

            status = group_raw_status(group, wars)
            db.conn.execute(
                """UPDATE cwl_live_group_cache
                   SET raw_status = ?,
                       raw_complete_at = CASE WHEN ? = 'complete' THEN ? ELSE NULL END
                   WHERE period = ? AND clan_tag = ?""",
                (status, status, timestamp, period, clan_tag),
            )
            if status != "complete":
                incomplete += 1
                continue
            complete += 1
            rows, _skipped = rebuild_league_results(
                db.conn, group, wars, team, rebuilt_at=timestamp
            )
            written += rows
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    finally:
        db.close()
    return complete, written, incomplete


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="从完整本地 CWL 档案重建 league_results 表")
    parser.add_argument("--period", required=True, help="CWL 月份（实际发生月），如 2026-08")
    args = parser.parse_args()

    complete, written, incomplete = rebuild_period_from_raw(args.period)
    if complete == 0:
        print("没有完整 CWL 原始档案；请先使用 backfill_cwl_live.py 完成逐场回填。")
        return 1
    if incomplete:
        print(f"{incomplete} 支队伍档案不完整，未生成其投影。")
        return 1
    print(f"已从 {complete} 个完整分组重建 {written} 条 league_results（period={args.period}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
