"""拉取普通部落战数据并写入数据库。

流程：
  1. 从 ClashKing API 拉取指定部落的 war log
  2. 筛选非 CWL 的普通部落战（is_cwl_war 为 False）
  3. 调用 aggregate_regular_war_players() 汇总玩家战绩（满星前统计）
  4. 写入 war_results 表（ON CONFLICT DO NOTHING 保证幂等）

用法：
  python scripts/fetch_war_data.py --clan-tag "#2QQ" --limit 200
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

from modules.coc_sync.clashking.client import (  # noqa: E402
    fetch_war_log, is_cwl_war, aggregate_regular_war_players,
)
from config import DB_PATH, LEAGUE_COMBAT  # noqa: E402


def _write_to_db(players: list[dict], clan_tag: str) -> int:
    """写入 war_results 表，ON CONFLICT DO NOTHING 保证幂等。

    Returns:
        写入的行数
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute("SELECT player_tag, account_name FROM accounts")
    known_tags = {r[0]: r[1] for r in cur.fetchall()}

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n_ok = 0
    n_skip = 0

    for p in players:
        tag = p["tag"]
        if tag not in known_tags:
            n_skip += 1
            continue

        account_name = known_tags[tag]
        raw_metrics = {
            "total_stars": p["total_stars"],
            "offense_3stars": p["offense_3stars"],
            "offense_total": p["total_attacks"],
            "defense_3stars": p["defense_3stars"],
            "defense_total": p["defense_total"],
            "clan_tag": clan_tag,
        }

        conn.execute(
            """INSERT OR IGNORE INTO war_results
               (clan_tag, player_tag, account_name, town_hall_level, end_time,
                total_stars, attacks, offense_3stars, defense_3stars, defense_total,
                fetched_at, raw_metrics)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                clan_tag, tag, account_name, p.get("town_hall_level", 0),
                p["end_time"], p["total_stars"], p["total_attacks"],
                p["offense_3stars"], p["defense_3stars"], p["defense_total"],
                fetched_at, json.dumps(raw_metrics, ensure_ascii=False),
            ),
        )

        if conn.total_changes > n_ok + n_skip:
            n_ok += 1

    conn.commit()
    conn.close()

    if n_skip:
        print(f"  ⏭ 跳过 {n_skip} 条（不在 accounts 表中）")
    return n_ok


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="拉取普通部落战数据并写入 war_results 表")
    parser.add_argument("--clan-tag", default="#2QQ", help="部落标签（默认 #2QQ）")
    parser.add_argument("--limit", type=int, default=200, help="API 拉取条数上限（默认 200）")
    args = parser.parse_args()

    clan_tag = args.clan_tag
    print(f"部落: {clan_tag}")

    # ── 1. 拉取 war log ──
    print("拉取 war log ...")
    wars = fetch_war_log(clan_tag, limit=args.limit)
    print(f"  共 {len(wars)} 条 war log")

    if not wars:
        print("⚠️  ClashKing API 未返回任何 war log")
        return 1

    # ── 2. 筛选普通部落战 ──
    regular_wars = [w for w in wars if not is_cwl_war(w)]
    print(f"  其中普通部落战: {len(regular_wars)} 场")

    # 列出普通部落战概要
    for w in regular_wars[:5]:
        end_time = w.get("endTime", "")[:10]
        team_size = w.get("teamSize", "?")
        enemy = w.get("opponent", {}).get("name", "?")
        if _normalize_tag(w.get("clan", {}).get("tag", "")) == _normalize_tag(clan_tag):
            enemy = w.get("opponent", {}).get("name", "?")
        else:
            enemy = w.get("clan", {}).get("name", "?")
        print(f"    {end_time}  {team_size}v{team_size}  vs {enemy}")
    if len(regular_wars) > 5:
        print(f"    ... 共 {len(regular_wars)} 场")

    if not regular_wars:
        print("⚠️  没有普通部落战数据")
        return 0

    # ── 3. 汇总玩家战绩 ──
    print("汇总玩家战绩（满星前统计）...")
    players = aggregate_regular_war_players(regular_wars, clan_tag)
    print(f"  共 {len(players)} 名玩家有战绩数据")

    if not players:
        print("⚠️  没有玩家战绩数据")
        return 0

    # ── 4. 写入数据库 ──
    print("写入 war_results 表 ...")
    n_ok = _write_to_db(players, clan_tag)
    print(f"✅ 写入 {n_ok} 条记录（跳过已存在的）")

    return 0


def _normalize_tag(tag: str) -> str:
    return tag.strip().lstrip("#").upper()


if __name__ == "__main__":
    raise SystemExit(main())
