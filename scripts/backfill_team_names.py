"""旁路脚本：通过 COC API get_clan 接口回填 league_teams.team_name（COC 真实部落名称）。

用于历史数据补全场景（如迁移后 team_name 为空，或 CWL 赛季已结束无法再拉）。

用法：
  cd sky-admin
  python scripts/backfill_team_names.py --period 2026-07

会按 clan_tag 逐个查询 COC API，回填 league_teams.team_name 和 league_results.team_name。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env
load_env()

from modules.coc_sync.api_client import CocApiClient, CocApiError
from config import DB_PATH


def backfill(period: str) -> None:
    if not os.environ.get("COC_API_TOKEN"):
        print("❌ 未设置 COC_API_TOKEN")
        raise SystemExit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 读取 league_teams 中 team_name 为空的队伍
    rows = conn.execute(
        "SELECT * FROM league_teams WHERE period = ? AND team_name IS NULL ORDER BY team_index",
        (period,),
    ).fetchall()

    if not rows:
        print(f"league_teams 中 {period} 没有需要回填的队伍（全部已有 team_name）")
        conn.close()
        return

    print(f"需要回填 {len(rows)} 支队伍:")
    for r in rows:
        print(f"  team_index={r['team_index']}  alias={r['team_alias']}  tag={r['clan_tag']}")

    client = CocApiClient()
    updated_teams = 0
    updated_results = 0

    for r in rows:
        clan_tag = r["clan_tag"]
        ti = r["team_index"]
        if not clan_tag:
            continue

        try:
            clan = client.get_clan(clan_tag)
            name = clan.get("name", "")
        except CocApiError as e:
            print(f"  ❌ {clan_tag}: {e}")
            continue

        if not name:
            print(f"  ⚠️ {clan_tag}: API 返回空名称")
            continue

        print(f"  ✅ {clan_tag} → {name}")

        # 回填 league_teams
        conn.execute(
            "UPDATE league_teams SET team_name = ? WHERE period = ? AND team_index = ?",
            (name, period, ti),
        )
        updated_teams += 1

        # 回填 league_results
        conn.execute(
            "UPDATE league_results SET team_name = ? WHERE period = ? AND team_index = ?",
            (name, period, ti),
        )
        updated_results += conn.total_changes

    conn.commit()

    # 验证
    remaining = conn.execute(
        "SELECT COUNT(*) FROM league_teams WHERE period = ? AND team_name IS NULL",
        (period,),
    ).fetchone()[0]

    print(f"\n回填完成: league_teams {updated_teams} 支, league_results 约 {updated_results} 条")
    print(f"剩余未回填: {remaining} 支")

    # 打印最终结果
    final = conn.execute(
        "SELECT * FROM league_teams WHERE period = ? ORDER BY team_index",
        (period,),
    ).fetchall()
    print(f"\n{period} league_teams 最终状态:")
    for r in final:
        print(f"  ti={r['team_index']}  alias={r['team_alias']}  coc_name={r['team_name']}  tag={r['clan_tag']}")

    conn.close()


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="回填 league_teams.team_name")
    parser.add_argument("--period", required=True, help="月份，如 2026-07")
    args = parser.parse_args()
    backfill(args.period)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
