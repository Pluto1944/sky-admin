#!/usr/bin/env python3
"""互刷部落统计定时同步脚本。

从 COC API 拉取所有互刷部落的成员+部落战数据，计算实时配置和去速本配置，
写入 farm_stats 表供 API 接口直接读取。

用法：
    python scripts/sync_farm_stats.py          # 单次同步
    python scripts/sync_farm_stats.py --loop   # 循环模式（每 30 分钟一次）
    python scripts/sync_farm_stats.py --loop --interval 60  # 自定义间隔（分钟）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="同步互刷部落统计到数据库")
    parser.add_argument("--loop", action="store_true", help="循环模式，持续运行")
    parser.add_argument("--interval", type=int, default=30, help="循环间隔（分钟），默认 30")
    args = parser.parse_args()

    # 确保项目根目录在 sys.path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    from config import DB_PATH, get_farm_clans
    from shared.db.connection import Database

    db = Database(DB_PATH)
    db.init_schema()

    def do_sync() -> None:
        """执行一次同步。"""
        farm_clans = get_farm_clans()
        if not farm_clans:
            print(f"[{now_iso()}] 没有配置互刷部落，跳过")
            return

        print(f"[{now_iso()}] 开始同步 {len(farm_clans)} 个互刷部落...")

        from modules.coc_sync.clashking.farm_stats import get_all_farm_stats

        try:
            stats_list = get_all_farm_stats(farm_clans, delay=0.3)
        except Exception as e:
            print(f"[{now_iso()}] 拉取 COC API 失败: {e}")
            return

        ts = now_iso()
        success = 0
        fail = 0

        for stats in stats_list:
            tag = stats["clan_tag"]
            name = stats["clan_name"]
            try:
                db.conn.execute(
                    """INSERT OR REPLACE INTO farm_stats
                       (clan_tag, clan_name, category, member_count, stats_json, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        tag,
                        name,
                        stats.get("category", "farm"),
                        stats.get("member_count", 0),
                        json.dumps(stats, ensure_ascii=False),
                        ts,
                    ),
                )
                db.conn.commit()
                success += 1
                print(f"  [OK] {name} ({tag})")
            except Exception as e:
                fail += 1
                print(f"  [FAIL] {name} ({tag}): {e}")

        print(f"[{now_iso()}] 同步完成: 成功 {success}, 失败 {fail}")

    # 先跑一次
    do_sync()

    if args.loop:
        print(f"进入循环模式，每 {args.interval} 分钟同步一次...")
        while True:
            time.sleep(args.interval * 60)
            do_sync()

    db.close()


if __name__ == "__main__":
    main()
