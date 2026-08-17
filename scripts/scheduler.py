#!/usr/bin/env python3
"""周期数据刷新调度器（常驻 loop 进程）。

统一管理 4 类需要周期性刷新的任务，状态落 `sync_jobs` 表：

    farm_stats  互刷部落统计（每 30 分钟）
    coc_sync    COC 玩家档案（每 6 小时）
    war_results 普通部落战战绩（每天）
    cwl         CWL 联赛战绩（每天触发，day==12 才真正拉取）

用法：
    python scripts/scheduler.py                      # loop 模式（生产，systemd 守护）
    python scripts/scheduler.py --once farm_stats    # 手动执行单个任务（调试）
    python scripts/scheduler.py --once all           # 手动执行全部任务
    python scripts/scheduler.py --once cwl --force   # --force 跳过 day==12 判断
    python scripts/scheduler.py --list               # 查看所有任务状态
    python scripts/scheduler.py --enable farm_stats  # 启用任务
    python scripts/scheduler.py --disable farm_stats # 停用任务
    python scripts/scheduler.py --set-interval farm_stats 60   # 调整间隔（分钟）

设计要点：
- 纯间隔模型（interval_min），不引入 cron。
- 失败也推进 next_run_at，避免失败任务每轮被高频重试。
- 单任务异常不影响其它任务与常驻进程。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# 确保项目根目录在 sys.path（脚本可能从任意 cwd 启动）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

import config  # noqa: E402
from shared.db.connection import Database  # noqa: E402

POLL_SECONDS = 60  # 主循环轮询间隔（秒）


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ═══════════════════════════════════════════════════════════════════════
# 各任务 run 函数
# ═══════════════════════════════════════════════════════════════════════

def _run_farm_stats() -> dict:
    """拉取所有互刷部落统计，写入 farm_stats 表。"""
    farm_clans = config.get_farm_clans()
    if not farm_clans:
        return {"status": "skipped", "reason": "没有配置互刷部落"}

    from modules.coc_sync.clashking.farm_stats import get_all_farm_stats

    stats_list = get_all_farm_stats(farm_clans, delay=0.3)
    db = Database(config.DB_PATH)
    db.init_schema()
    ts = now_iso()
    success = 0
    for stats in stats_list:
        db.conn.execute(
            """INSERT OR REPLACE INTO farm_stats
               (clan_tag, clan_name, category, member_count, stats_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                stats["clan_tag"],
                stats["clan_name"],
                stats.get("category", "farm"),
                stats.get("member_count", 0),
                json.dumps(stats, ensure_ascii=False),
                ts,
            ),
        )
        success += 1
    db.conn.commit()
    db.close()

    if not success:
        return {"status": "failed", "reason": "0 个部落写入成功"}
    return {"status": "success", "reason": f"同步 {success} 个互刷部落"}


def _run_coc_sync() -> dict:
    """同步联盟部落成员到 accounts 表。"""
    from modules.coc_sync.service import CocSyncService
    from modules.player.repository import PlayerRepository
    from modules.player.service import PlayerService

    db = Database(config.DB_PATH)
    db.init_schema()
    player_service = PlayerService(PlayerRepository(db.conn))
    svc = CocSyncService(player_service)
    stats = svc.sync_clans()
    db.close()

    reason = (
        f"部落 {stats['clans']}，成员 {stats['members']}，"
        f"新增 {stats['created']}，更新 {stats['updated']}，退部 {stats['left']}"
    )
    if stats["failed_clans"]:
        return {"status": "failed", "reason": reason + f"，失败部落 {stats['failed_clans']}"}
    return {"status": "success", "reason": reason}


def _run_war_results() -> dict:
    """拉取战营部落战战绩，写入 war_results 表。"""
    from modules.coc_sync.clashking.client import (
        fetch_war_log, is_cwl_war, aggregate_regular_war_players,
    )

    clan_tag = "#2QQ"  # 战营主部落
    wars = fetch_war_log(clan_tag, limit=200)
    if not wars:
        return {"status": "failed", "reason": "ClashKing API 未返回任何 war log"}

    regular_wars = [w for w in wars if not is_cwl_war(w)]
    players = aggregate_regular_war_players(regular_wars, clan_tag)
    if not players:
        return {"status": "skipped", "reason": "没有普通部落战玩家数据"}

    from scripts.fetch_war_data import _write_to_db

    n_ok = _write_to_db(players, clan_tag)
    return {"status": "success", "reason": f"写入 {n_ok} 条战绩"}


def _run_cwl(force: bool = False) -> dict:
    """拉取当月 CWL 联赛战绩，写入 league_results + results 表。

    仅每月 12 号执行（force=True 跳过日期判断，供调试/补数据）。
    日期按东八区（Asia/Shanghai）判断，与业务时区一致。
    """
    from datetime import timezone as _tz, timedelta as _td

    cst = _tz(_td(hours=8))  # Asia/Shanghai
    today = datetime.now(cst)
    if not force and today.day != 12:
        return {"status": "skipped", "reason": f"非12号（今天{today.day}号），跳过"}

    period = today.strftime("%Y-%m")

    from scripts.fetch_cwl_data import _load_teams_from_db, _fetch_and_write, _cold_start_from_json

    teams = _load_teams_from_db(period)
    if teams:
        ok_teams, n_ok, _n_skip, _source_map = _fetch_and_write(period, teams)
        if not ok_teams:
            return {"status": "failed", "reason": f"{period} 全部队伍拉取失败"}
        if n_ok == 0:
            return {"status": "skipped", "reason": f"{period} 0 条战绩写入（不在 accounts）"}
        return {"status": "success", "reason": f"{period} 写入 {n_ok} 条（{len(ok_teams)}/{len(teams)} 队）"}

    # 冷启动：league_teams 无记录，从本地 JSON 导入
    ok_teams, n_ok, _n_skip = _cold_start_from_json(period)
    if n_ok == 0:
        return {"status": "skipped", "reason": f"{period} 无 league_teams 且无本地 JSON"}
    return {"status": "success", "reason": f"{period} 冷启动写入 {n_ok} 条"}


# ═══════════════════════════════════════════════════════════════════════
# 任务注册表
# ═══════════════════════════════════════════════════════════════════════

JOBS = {
    "farm_stats": {
        "name": "互刷部落统计",
        "interval": 30,
        "run": _run_farm_stats,
    },
    "coc_sync": {
        "name": "COC玩家档案",
        "interval": 360,
        "run": _run_coc_sync,
    },
    "war_results": {
        "name": "普通部落战战绩",
        "interval": 1440,
        "run": _run_war_results,
    },
    "cwl": {
        "name": "CWL联赛战绩",
        "interval": 1440,
        "run": _run_cwl,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# 状态读写
# ═══════════════════════════════════════════════════════════════════════

def _open_db() -> Database:
    db = Database(config.DB_PATH)
    db.init_schema()
    return db


def _ensure_rows(db: Database) -> None:
    """确保每个任务在 sync_jobs 中有一行（首次运行时补入）。"""
    for job_id, job in JOBS.items():
        db.conn.execute(
            """INSERT OR IGNORE INTO sync_jobs
               (job_id, job_name, interval_min, enabled, last_status)
               VALUES (?, ?, ?, 1, 'never')""",
            (job_id, job["name"], job["interval"]),
        )
    db.conn.commit()


def _get_row(db: Database, job_id: str) -> dict:
    row = db.conn.execute(
        "SELECT * FROM sync_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return dict(row) if row else {}


def _update(db: Database, job_id: str, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [job_id]
    db.conn.execute(f"UPDATE sync_jobs SET {sets} WHERE job_id = ?", vals)
    db.conn.commit()


# ═══════════════════════════════════════════════════════════════════════
# 核心：run_one + 主循环
# ═══════════════════════════════════════════════════════════════════════

def run_one(db: Database, job_id: str, force: bool = False) -> dict:
    """执行单个任务并更新状态。返回执行结果 dict。"""
    job = JOBS[job_id]
    _update(db, job_id, last_status="running", last_error="")

    start = time.monotonic()
    try:
        run_fn = job["run"]
        if job_id == "cwl":
            result = run_fn(force=force)
        else:
            result = run_fn()
        duration = time.monotonic() - start
        status = result.get("status", "success")
        reason = result.get("reason", "")
        _update(
            db, job_id,
            last_status=status,
            last_duration=round(duration, 2),
            last_error=reason if status != "success" else "",
        )
        _increment(db, job_id, failed=(status == "failed"))
    except Exception as e:  # noqa: BLE001 —— 单任务隔离，兜住一切异常
        duration = time.monotonic() - start
        _update(
            db, job_id,
            last_status="failed",
            last_duration=round(duration, 2),
            last_error=str(e),
        )
        _increment(db, job_id, failed=True)
        result = {"status": "failed", "reason": str(e)}

    # 无论成败都推进 next_run_at，避免失败任务每轮被高频重试
    interval = int(_get_row(db, job_id).get("interval_min") or JOBS[job_id]["interval"])
    next_at = (datetime.now(timezone.utc).timestamp() + interval * 60)
    next_iso = datetime.fromtimestamp(next_at, tz=timezone.utc).isoformat(timespec="seconds")
    _update(db, job_id, last_run_at=now_iso(), next_run_at=next_iso)

    return result


def _increment(db: Database, job_id: str, failed: bool) -> None:
    """累计运行次数（失败额外累计失败次数）。"""
    if failed:
        db.conn.execute(
            "UPDATE sync_jobs SET run_count = run_count + 1, fail_count = fail_count + 1 WHERE job_id = ?",
            (job_id,),
        )
    else:
        db.conn.execute(
            "UPDATE sync_jobs SET run_count = run_count + 1 WHERE job_id = ?",
            (job_id,),
        )
    db.conn.commit()


def _parse_next_run_at(row: dict) -> float | None:
    """解析 next_run_at 为 epoch 秒；空/非法返回 None（表示到期立即执行）。"""
    val = row.get("next_run_at")
    if not val:
        return None
    try:
        return datetime.fromisoformat(val).timestamp()
    except (ValueError, TypeError):
        return None


def loop() -> None:
    """常驻主循环。"""
    db = _open_db()
    _ensure_rows(db)
    print(f"[{now_iso()}] 调度器启动，轮询间隔 {POLL_SECONDS}s")
    while True:
        now_ts = datetime.now(timezone.utc).timestamp()
        for job_id, job in JOBS.items():
            row = _get_row(db, job_id)
            if not row.get("enabled", 1):
                continue
            next_ts = _parse_next_run_at(row)
            if next_ts is not None and now_ts < next_ts:
                continue
            result = run_one(db, job_id)
            print(f"[{now_iso()}] {job['name']}({job_id}): {result.get('status')} {result.get('reason', '')}")
        time.sleep(POLL_SECONDS)


# ═══════════════════════════════════════════════════════════════════════
# CLI 管理命令
# ═══════════════════════════════════════════════════════════════════════

def cmd_once(job_id: str, force: bool) -> None:
    db = _open_db()
    _ensure_rows(db)
    targets = list(JOBS.keys()) if job_id == "all" else [job_id]
    for jid in targets:
        if jid not in JOBS:
            print(f"未知任务: {jid}", file=sys.stderr)
            continue
        result = run_one(db, jid, force=force)
        print(f"{JOBS[jid]['name']}({jid}): {result.get('status')} {result.get('reason', '')}")
    db.close()


def cmd_list() -> None:
    db = _open_db()
    _ensure_rows(db)
    rows = db.conn.execute("SELECT * FROM sync_jobs ORDER BY job_id").fetchall()
    if not rows:
        print("（无任务记录）")
        db.close()
        return
    header = f"{'job_id':<12} {'job_name':<14} {'interval':>8} {'enabled':>7} {'status':<8} {'run':>5} {'fail':>5} {'duration':>8}  last_run_at"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['job_id']:<12} {r['job_name'] or '':<14} "
            f"{r['interval_min']:>8} {r['enabled']:>7} {r['last_status'] or 'never':<8} "
            f"{r['run_count']:>5} {r['fail_count']:>5} "
            f"{r['last_duration'] if r['last_duration'] is not None else '-':>8}  "
            f"{r['last_run_at'] or '-'}"
        )
        if r["last_error"]:
            print(f"  └─ error: {r['last_error']}")
    db.close()


def cmd_enable(job_id: str, enabled: bool) -> None:
    db = _open_db()
    _ensure_rows(db)
    if job_id not in JOBS:
        print(f"未知任务: {job_id}", file=sys.stderr)
        db.close()
        return
    _update(db, job_id, enabled=1 if enabled else 0)
    print(f"{JOBS[job_id]['name']}({job_id}): {'已启用' if enabled else '已停用'}")
    db.close()


def cmd_set_interval(job_id: str, minutes: int) -> None:
    if minutes <= 0:
        print("间隔必须为正整数（分钟）", file=sys.stderr)
        return
    db = _open_db()
    _ensure_rows(db)
    if job_id not in JOBS:
        print(f"未知任务: {job_id}", file=sys.stderr)
        db.close()
        return
    _update(db, job_id, interval_min=minutes)
    print(f"{JOBS[job_id]['name']}({job_id}): 间隔已设为 {minutes} 分钟")
    db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="周期数据刷新调度器")
    parser.add_argument("--once", metavar="JOB|all", default=None, help="单次执行指定任务或 all")
    parser.add_argument("--force", action="store_true", help="配合 --once，跳过 CWL 的 day==12 判断")
    parser.add_argument("--list", action="store_true", help="查看所有任务状态")
    parser.add_argument("--enable", metavar="JOB", default=None, help="启用任务")
    parser.add_argument("--disable", metavar="JOB", default=None, help="停用任务")
    parser.add_argument("--set-interval", metavar="JOB", nargs=2, default=None,
                        help="调整任务间隔：JOB 分钟数（如 farm_stats 60）")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return 0
    if args.once:
        cmd_once(args.once, args.force)
        return 0
    if args.enable:
        cmd_enable(args.enable, True)
        return 0
    if args.disable:
        cmd_enable(args.disable, False)
        return 0
    if args.set_interval:
        job_id, minutes = args.set_interval
        try:
            minutes = int(minutes)
        except ValueError:
            print("间隔分钟数必须是整数", file=sys.stderr)
            return 1
        cmd_set_interval(job_id, minutes)
        return 0

    # 默认：loop 模式
    try:
        loop()
    except KeyboardInterrupt:
        print("\n调度器已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
