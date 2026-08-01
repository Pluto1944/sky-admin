"""一次性迁移脚本：将 results 表中 2026-07 的数据迁移到 league_teams 和 league_results 表。

用法：
  cd sky-admin
  python scripts/migrate_results_202607.py

功能：
1. 从 results.raw_metrics 提取 team_name/team_index/clan_tag/total_stars
2. 按 team_index 去重，写入 league_teams（队伍配置快照）
3. 逐条写入 league_results（玩家战绩）
4. 通过 accounts 表反查 account_name
5. 幂等执行（重复运行不会重复插入）
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.common import DB_PATH, LEAGUE_COMBAT

PERIOD = "2026-07"


def ensure_tables(conn: sqlite3.Connection) -> None:
    """确保 league_teams 和 league_results 表存在。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS league_teams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            period          TEXT NOT NULL,
            team_index      INTEGER NOT NULL,
            team_alias      TEXT NOT NULL,
            team_name       TEXT,
            clan_tag        TEXT,
            category        TEXT NOT NULL,
            member_count    INTEGER NOT NULL,
            leader          TEXT,
            league_level    TEXT,
            reserved_slots  INTEGER DEFAULT 0,
            UNIQUE(period, team_index)
        );

        CREATE TABLE IF NOT EXISTS league_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            period          TEXT NOT NULL,
            team_index      INTEGER NOT NULL,
            team_alias      TEXT NOT NULL,
            team_name       TEXT,
            clan_tag        TEXT,
            category        TEXT NOT NULL,
            player_tag      TEXT NOT NULL,
            account_name    TEXT,
            total_stars     INTEGER,
            attacks         INTEGER,
            raw_metrics     TEXT,
            UNIQUE(period, team_index, player_tag),
            FOREIGN KEY(player_tag) REFERENCES accounts(player_tag)
        );
    """)
    conn.commit()


def migrate() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # 1. 确保新表存在
    ensure_tables(conn)

    # 2. 读取 results 表 2026-07 数据
    rows = conn.execute(
        "SELECT * FROM results WHERE period = ? AND league_type = ?",
        (PERIOD, LEAGUE_COMBAT),
    ).fetchall()
    print(f"results 表 {PERIOD} combat 数据: {len(rows)} 条")

    if not rows:
        print("无数据，退出")
        conn.close()
        return

    # 3. 构建 accounts player_tag → account_name 映射
    acc_map = {
        r["player_tag"]: r["account_name"]
        for r in conn.execute("SELECT player_tag, account_name FROM accounts").fetchall()
    }

    # 4. 提取队伍配置（按 team_index 去重）
    team_configs: dict[int, dict] = {}
    for r in rows:
        metrics = json.loads(r["raw_metrics"]) if r["raw_metrics"] else {}
        ti = metrics.get("team_index")
        if ti is None:
            continue
        if ti not in team_configs:
            team_configs[ti] = {
                "team_index": ti,
                "team_alias": metrics.get("team_name", ""),
                "clan_tag": metrics.get("clan_tag", ""),
            }

    # 5. 写入 league_teams
    n_teams = 0
    for ti, cfg in sorted(team_configs.items()):
        conn.execute(
            """INSERT OR REPLACE INTO league_teams
               (period, team_index, team_alias, team_name, clan_tag, category,
                member_count, leader, league_level, reserved_slots)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (PERIOD, ti, cfg["team_alias"], None, cfg["clan_tag"],
             LEAGUE_COMBAT, 0, None, None, 0),
        )
        n_teams += 1
    conn.commit()
    print(f"league_teams: 写入 {n_teams} 条队伍配置")

    # 6. 写入 league_results
    n_ok = n_skip = 0
    for r in rows:
        metrics = json.loads(r["raw_metrics"]) if r["raw_metrics"] else {}
        ti = metrics.get("team_index")
        if ti is None:
            n_skip += 1
            continue

        player_tag = r["player_tag"]
        account_name = acc_map.get(player_tag)
        total_stars = metrics.get("total_stars")

        conn.execute(
            """INSERT OR REPLACE INTO league_results
               (period, team_index, team_alias, team_name, clan_tag, category,
                player_tag, account_name, total_stars, attacks, raw_metrics)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                PERIOD, ti, metrics.get("team_name", ""), None,
                metrics.get("clan_tag", ""), LEAGUE_COMBAT,
                player_tag, account_name, total_stars, None,
                r["raw_metrics"],
            ),
        )
        n_ok += 1

    conn.commit()
    print(f"league_results: 写入 {n_ok} 条，跳过 {n_skip} 条（无 team_index）")

    # 7. 验证
    lt_count = conn.execute(
        "SELECT COUNT(*) FROM league_teams WHERE period = ?", (PERIOD,)
    ).fetchone()[0]
    lr_count = conn.execute(
        "SELECT COUNT(*) FROM league_results WHERE period = ?", (PERIOD,)
    ).fetchone()[0]
    print(f"\n验证: league_teams={lt_count} 条, league_results={lr_count} 条")

    # 8. 按 team_index 分组统计
    print("\n按 team_index 分组统计:")
    for ti in sorted(team_configs.keys()):
        cfg = team_configs[ti]
        cnt = conn.execute(
            "SELECT COUNT(*) FROM league_results WHERE period = ? AND team_index = ?",
            (PERIOD, ti),
        ).fetchone()[0]
        print(f"  team_index={ti}  {cfg['team_alias']} ({cfg['clan_tag']}): {cnt} 人")

    conn.close()
    print("\n✅ 迁移完成")


if __name__ == "__main__":
    migrate()
