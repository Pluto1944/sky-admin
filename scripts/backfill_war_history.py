#!/usr/bin/env python3
"""从 ClashKing 回填各自有部落最近 15 场普通部落战完整详情。

默认只执行 dry-run；全部部落请求和数据校验通过后，显式传入 ``--apply`` 才写库。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

import config  # noqa: E402
from modules.coc_sync.clashking.client import fetch_war_log, is_cwl_war  # noqa: E402
from modules.coc_sync.current_war import normalize_current_war  # noqa: E402
from modules.coc_sync.war_history import is_archivable_war, war_history_key  # noqa: E402
from scripts.scheduler import _archive_current_war  # noqa: E402
from shared.db.connection import Database  # noqa: E402


def prepare_clan_history(raw_wars: list[dict], clan: dict, keep: int, synced_at: str) -> list[dict]:
    """筛选、标准化并校验一个自有部落的历史普通战争。"""
    prepared = []
    seen = set()
    candidates = sorted(
        (
            war for war in raw_wars
            if not is_cwl_war(war) and war.get("state") == "warEnded"
        ),
        key=lambda war: war.get("endTime") or "",
        reverse=True,
    )
    for raw in candidates:
        item = normalize_current_war(raw, clan, synced_at)
        key = war_history_key(item)
        if not is_archivable_war(item) or item.get("status") != "war_ended" or not key:
            continue
        if not item.get("end_time") or not item.get("opponent"):
            continue
        if int(item.get("team_size") or 0) <= 0 or len(item.get("rows") or []) < int(item["team_size"]):
            continue
        if key in seen:
            continue
        seen.add(key)
        prepared.append(item)
        if len(prepared) >= keep:
            break
    return prepared


def run(limit: int = 100, keep: int = 15, apply: bool = False) -> int:
    clans = [clan for clan in config.CLANS if clan.get("enabled", True)]
    synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundles = []
    errors = []
    print(f"普通部落战历史 {'APPLY' if apply else 'DRY-RUN'}：{len(clans)} 个自有部落")
    for clan in clans:
        name = clan.get("name") or clan["tag"]
        try:
            raw = fetch_war_log(clan["tag"], limit=limit)
            wars = prepare_clan_history(raw, clan, keep, synced_at)
            bundles.append((clan, wars))
            newest = wars[0]["end_time"] if wars else "-"
            oldest = wars[-1]["end_time"] if wars else "-"
            print(f"[ok] {name} {clan['tag']}：{len(wars)} 场，{oldest} ～ {newest}")
        except Exception as exc:  # noqa: BLE001 - 所有部落成功后才允许统一写库
            errors.append(f"{name} {clan['tag']}: {exc}")
            print(f"[error] {name} {clan['tag']}：{exc}", file=sys.stderr)

    if errors:
        print(f"失败 {len(errors)} 个部落，拒绝写入。", file=sys.stderr)
        return 1
    total = sum(len(wars) for _, wars in bundles)
    if not apply:
        print(f"DRY-RUN 通过：{len(bundles)} 个部落、{total} 场；未写数据库。")
        return 0

    db = Database(config.DB_PATH)
    db.init_schema()
    try:
        db.conn.execute("BEGIN IMMEDIATE")
        for _, wars in bundles:
            for item in reversed(wars):
                _archive_current_war(
                    db,
                    item,
                    keep_ended=keep,
                    cleanup_active=False,
                )
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    finally:
        db.close()
    print(f"写入完成：{len(bundles)} 个部落、最多 {keep} 场/部落、共处理 {total} 场。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回填各自有部落最近普通部落战详情")
    parser.add_argument("--limit", type=int, default=100, help="每个部落拉取的历史日志上限")
    parser.add_argument("--keep", type=int, default=15, help="每个部落保留的已结束战争数")
    parser.add_argument("--apply", action="store_true", help="校验通过后写数据库；默认 dry-run")
    args = parser.parse_args()
    if args.limit < 1 or args.keep < 1:
        parser.error("--limit 和 --keep 必须大于 0")
    return run(args.limit, args.keep, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
