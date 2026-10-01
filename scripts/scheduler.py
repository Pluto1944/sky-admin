#!/usr/bin/env python3
"""周期数据刷新调度器（常驻 loop 进程）。

统一管理 7 类需要周期性执行的任务，状态落 `sync_jobs` 表：

    current_wars 全部自有部落当前战争（战斗日 2 分钟，准备日动态 30/2 分钟）
    cwl_live    当月 CWL 联赛组与逐场战争（活跃期每 2 分钟）
    farm_stats  互刷部落统计（每 30 分钟）
    coc_sync    COC 玩家档案（每 6 小时）
    war_results 普通部落战战绩（每天）
    cwl         CWL 联赛战绩（每天触发，day==12 才真正拉取）
    war_layout  公众号阵型群发（每天北京时间 09:00）

用法：
    python scripts/scheduler.py                      # loop 模式（生产，systemd 守护）
    python scripts/scheduler.py --once current_wars  # 手动刷新当前部落战缓存
    python scripts/scheduler.py --once cwl_live --force  # 手动刷新当月 CWL 实时缓存
    python scripts/scheduler.py --once farm_stats    # 手动执行单个任务（调试）
    python scripts/scheduler.py --once all           # 手动执行全部任务
    python scripts/scheduler.py --once cwl --force   # --force 跳过 day==12 判断
    python scripts/scheduler.py --list               # 查看所有任务状态
    python scripts/scheduler.py --enable farm_stats  # 启用任务
    python scripts/scheduler.py --disable farm_stats # 停用任务
    python scripts/scheduler.py --set-interval farm_stats 60   # 调整间隔（分钟）

设计要点：
- 默认使用间隔模型；固定业务时刻使用 daily_at，不引入 cron。
- 失败也推进 next_run_at，避免失败任务每轮被高频重试。
- 单任务异常不影响其它任务与常驻进程。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# 确保项目根目录在 sys.path（脚本可能从任意 cwd 启动）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

import config  # noqa: E402
from shared.db.connection import Database  # noqa: E402

POLL_SECONDS = 60  # 主循环轮询间隔（秒）
BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


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


CURRENT_WAR_REFRESH_MINUTES = {
    "in_war": 2,
    "not_in_war": 5,
    "war_ended": 5,
    "cwl": 30,
}
CURRENT_WAR_ERROR_BACKOFF_MINUTES = (5, 10, 20, 30)
CURRENT_WAR_PREPARATION_MINUTES = 30
CURRENT_WAR_PREPARATION_NEAR_START_MINUTES = 2
CURRENT_WAR_PREPARATION_NEAR_START_WINDOW_MINUTES = 30


def _parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _current_war_refresh_minutes(cache: dict, now: datetime) -> int:
    """根据缓存状态返回单部落的下次官方 API 重试间隔。"""
    failures = int(cache.get("failure_count") or 0)
    if cache.get("status") == "error" or failures > 0:
        failures = max(1, failures)
        index = min(failures - 1, len(CURRENT_WAR_ERROR_BACKOFF_MINUTES) - 1)
        return CURRENT_WAR_ERROR_BACKOFF_MINUTES[index]
    if cache.get("status") == "preparation":
        try:
            payload = json.loads(cache.get("data_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        start_time = _parse_coc_time(payload.get("start_time"))
        if start_time is not None:
            minutes_until_start = (
                start_time - now.astimezone(timezone.utc)
            ).total_seconds() / 60
            if minutes_until_start <= CURRENT_WAR_PREPARATION_NEAR_START_WINDOW_MINUTES:
                return CURRENT_WAR_PREPARATION_NEAR_START_MINUTES
        return CURRENT_WAR_PREPARATION_MINUTES
    return CURRENT_WAR_REFRESH_MINUTES.get(cache.get("status"), 30)


def _archive_current_war(
    db: Database,
    item: dict,
    keep_ended: int = 15,
    cleanup_active: bool = True,
) -> bool:
    """把普通战争快照幂等归档，并仅保留该部落最近若干场已结束战争。"""
    from modules.coc_sync.war_history import is_archivable_war, war_history_record

    if not is_archivable_war(item):
        return False
    record = war_history_record(item)
    db.conn.execute(
        """INSERT INTO war_history_cache
           (clan_tag, war_key, clan_name, category, opponent_tag, opponent_name,
            status, result, preparation_start_time, start_time, end_time,
            data_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(clan_tag, war_key) DO UPDATE SET
               clan_name = excluded.clan_name,
               category = excluded.category,
               opponent_tag = excluded.opponent_tag,
               opponent_name = excluded.opponent_name,
               status = excluded.status,
               result = excluded.result,
               preparation_start_time = excluded.preparation_start_time,
               start_time = excluded.start_time,
               end_time = excluded.end_time,
               data_json = excluded.data_json,
               updated_at = excluded.updated_at""",
        (
            record["clan_tag"], record["war_key"], record["clan_name"],
            record["category"], record["opponent_tag"], record["opponent_name"],
            record["status"], record["result"], record["preparation_start_time"],
            record["start_time"], record["end_time"],
            json.dumps(record["data"], ensure_ascii=False), record["updated_at"],
        ),
    )
    # 实时同步发现新战争时清理旧草稿；历史回填不得删除当前活动战争快照。
    if cleanup_active:
        db.conn.execute(
            """DELETE FROM war_history_cache
               WHERE clan_tag = ? AND status != 'war_ended' AND war_key != ?""",
            (record["clan_tag"], record["war_key"]),
        )
    db.conn.execute(
        """DELETE FROM war_history_cache
           WHERE clan_tag = ? AND status = 'war_ended' AND war_key IN (
               SELECT war_key FROM war_history_cache
               WHERE clan_tag = ? AND status = 'war_ended'
               ORDER BY end_time DESC, war_key DESC
               LIMIT -1 OFFSET ?
           )""",
        (record["clan_tag"], record["clan_tag"], keep_ended),
    )
    return True


def _run_current_wars(force: bool = False, now: datetime | None = None) -> dict:
    """按战争状态增量拉取已启用自有部落，写入当前战争缓存。"""
    from modules.coc_sync.service import CocSyncService
    from modules.coc_sync.official.mapper import normalize_tag

    clans = [
        {
            "tag": normalize_tag(clan["tag"]),
            "name": clan.get("name"),
            "category": clan.get("category", "normal"),
        }
        for clan in config.CLANS
        if clan.get("enabled", True)
    ]
    if not clans:
        return {"status": "skipped", "reason": "没有配置已启用部落"}

    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attempted_at = current_time.isoformat(timespec="seconds")
    db = Database(config.DB_PATH)
    db.init_schema()
    cached_by_tag = {
        row["clan_tag"]: dict(row)
        for row in db.conn.execute("SELECT * FROM current_war_cache").fetchall()
    }
    due_clans = []
    for clan in clans:
        cached = cached_by_tag.get(clan["tag"])
        if force or cached is None:
            due_clans.append(clan)
            continue
        age = _minutes_since(cached.get("attempted_at") or cached.get("updated_at"), current_time)
        if age is None or age >= _current_war_refresh_minutes(cached, current_time):
            due_clans.append(clan)

    if not due_clans:
        db.close()
        return {"status": "skipped", "reason": f"{len(clans)} 个部落均未到刷新时间"}

    items = CocSyncService().fetch_current_wars(due_clans)
    success = 0
    failed = 0
    for item in items:
        previous = cached_by_tag.get(item["clan_tag"], {})
        failure_count = (
            int(previous.get("failure_count") or 0) + 1
            if item["status"] == "error"
            else 0
        )
        if item["status"] == "error" and previous.get("data_json") and previous.get("status") != "error":
            # 短暂网络异常不应抹掉上一次成功的战争快照。仅记录本次失败，
            # API 继续返回可用快照，并通过 sync_error 告知前端数据可能陈旧。
            db.conn.execute(
                """UPDATE current_war_cache
                   SET clan_name = ?, category = ?, error = ?, attempted_at = ?, failure_count = ?
                   WHERE clan_tag = ?""",
                (
                    item["clan_name"], item["category"], item.get("error"),
                    attempted_at, failure_count, item["clan_tag"],
                ),
            )
            failed += 1
            continue

        db.conn.execute(
            """INSERT INTO current_war_cache
               (clan_tag, clan_name, category, status, data_json, error, updated_at,
                attempted_at, failure_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(clan_tag) DO UPDATE SET
                   clan_name = excluded.clan_name,
                   category = excluded.category,
                   status = excluded.status,
                   data_json = excluded.data_json,
                   error = excluded.error,
                   updated_at = excluded.updated_at,
                   attempted_at = excluded.attempted_at,
                   failure_count = excluded.failure_count""",
            (
                item["clan_tag"],
                item["clan_name"],
                item["category"],
                item["status"],
                json.dumps(item, ensure_ascii=False),
                item.get("error"),
                item["synced_at"],
                attempted_at,
                failure_count,
            ),
        )
        if item["status"] != "error":
            _archive_current_war(db, item)
        if item["status"] == "error":
            failed += 1
        else:
            success += 1
    db.conn.commit()
    db.close()

    if not success:
        return {"status": "failed", "reason": f"全部 {failed} 个部落同步失败"}
    suffix = f"，失败 {failed}" if failed else ""
    skipped = len(clans) - len(due_clans)
    if skipped:
        suffix += f"，按状态跳过 {skipped}"
    return {"status": "success", "reason": f"同步 {success} 个部落{suffix}"}


def _minutes_since(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60)
    except (TypeError, ValueError):
        return None


def _run_cwl_live(force: bool = False, now: datetime | None = None) -> dict:
    """增量刷新当前月份 CWL 联赛组与逐场战争缓存。"""
    from modules.coc_sync.cwl_live import group_war_tags
    from modules.coc_sync.official.mapper import normalize_tag
    from modules.coc_sync.service import CocSyncService

    local_now = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TZ)
    period = local_now.strftime("%Y-%m")
    if not force and local_now.day > 12:
        return {"status": "skipped", "reason": f"{period} 已过联赛实时窗口（今天{local_now.day}号）"}

    db = Database(config.DB_PATH)
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
        return {"status": "skipped", "reason": f"{period} 无 league_teams 联赛队伍"}

    service = CocSyncService()
    attempted_at = local_now.astimezone(timezone.utc).isoformat(timespec="seconds")
    group_payloads: list[dict] = []
    group_ok = group_waiting = group_failed = 0

    for team in teams:
        clan_tag = normalize_tag(team.get("clan_tag"))
        if not clan_tag:
            group_failed += 1
            continue
        team["clan_tag"] = clan_tag
        cached = db.conn.execute(
            "SELECT * FROM cwl_live_group_cache WHERE period = ? AND clan_tag = ?",
            (period, clan_tag),
        ).fetchone()
        cached = dict(cached) if cached else None
        age = _minutes_since((cached or {}).get("attempted_at"), local_now)
        due = force or cached is None or (cached.get("status") != "ended" and (age is None or age >= 30))

        if due:
            try:
                group = service.fetch_cwl_group(team)
                if group and group.get("season") == period:
                    status = "ended" if group.get("state") == "ended" else "active"
                    db.conn.execute(
                        """INSERT INTO cwl_live_group_cache
                           (period, clan_tag, team_index, team_alias, team_name, category,
                            league_level, season, state, status, data_json, error,
                            updated_at, attempted_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                           ON CONFLICT(period, clan_tag) DO UPDATE SET
                               team_index = excluded.team_index,
                               team_alias = excluded.team_alias,
                               team_name = excluded.team_name,
                               category = excluded.category,
                               league_level = excluded.league_level,
                               season = excluded.season,
                               state = excluded.state,
                               status = excluded.status,
                               data_json = excluded.data_json,
                               error = NULL,
                               updated_at = excluded.updated_at,
                               attempted_at = excluded.attempted_at""",
                        (
                            period, clan_tag, team["team_index"], team["team_alias"],
                            team.get("team_name"), team["category"], team.get("league_level"),
                            group.get("season"), group.get("state"), status,
                            json.dumps(group, ensure_ascii=False), group.get("synced_at"), attempted_at,
                        ),
                    )
                    group_ok += 1
                elif cached and cached.get("data_json"):
                    db.conn.execute(
                        """UPDATE cwl_live_group_cache
                           SET error = ?, attempted_at = ?
                           WHERE period = ? AND clan_tag = ?""",
                        ("官方暂未返回当前赛季联赛组", attempted_at, period, clan_tag),
                    )
                    group_waiting += 1
                else:
                    message = (
                        f"官方返回赛季 {group.get('season')}，与 {period} 不一致"
                        if group and group.get("season") else "等待联赛开启"
                    )
                    db.conn.execute(
                        """INSERT INTO cwl_live_group_cache
                           (period, clan_tag, team_index, team_alias, team_name, category,
                            league_level, season, state, status, data_json, error,
                            updated_at, attempted_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting', NULL, ?, NULL, ?)
                           ON CONFLICT(period, clan_tag) DO UPDATE SET
                               team_index = excluded.team_index,
                               team_alias = excluded.team_alias,
                               team_name = excluded.team_name,
                               category = excluded.category,
                               league_level = excluded.league_level,
                               season = excluded.season,
                               state = excluded.state,
                               status = 'waiting',
                               error = excluded.error,
                               attempted_at = excluded.attempted_at""",
                        (
                            period, clan_tag, team["team_index"], team["team_alias"],
                            team.get("team_name"), team["category"], team.get("league_level"),
                            group.get("season") if group else None,
                            group.get("state") if group else None,
                            message, attempted_at,
                        ),
                    )
                    group_waiting += 1
            except Exception as exc:  # noqa: BLE001 - 单队失败隔离
                group_failed += 1
                if cached:
                    db.conn.execute(
                        """UPDATE cwl_live_group_cache SET error = ?, attempted_at = ?
                           WHERE period = ? AND clan_tag = ?""",
                        (str(exc), attempted_at, period, clan_tag),
                    )
                else:
                    db.conn.execute(
                        """INSERT INTO cwl_live_group_cache
                           (period, clan_tag, team_index, team_alias, team_name, category,
                            league_level, status, error, updated_at, attempted_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'error', ?, NULL, ?)""",
                        (
                            period, clan_tag, team["team_index"], team["team_alias"],
                            team.get("team_name"), team["category"], team.get("league_level"),
                            str(exc), attempted_at,
                        ),
                    )
            db.conn.commit()

        row = db.conn.execute(
            "SELECT data_json FROM cwl_live_group_cache WHERE period = ? AND clan_tag = ?",
            (period, clan_tag),
        ).fetchone()
        if row and row["data_json"]:
            try:
                group_payloads.append(json.loads(row["data_json"]))
            except (TypeError, json.JSONDecodeError):
                pass

    unique_war_tags = []
    seen_war_tags = set()
    for group in group_payloads:
        for war_tag in group_war_tags(group):
            if war_tag not in seen_war_tags:
                seen_war_tags.add(war_tag)
                unique_war_tags.append(war_tag)

    war_ok = war_skipped = war_failed = 0
    for war_tag in unique_war_tags:
        cached = db.conn.execute(
            "SELECT * FROM cwl_live_war_cache WHERE war_tag = ?", (war_tag,)
        ).fetchone()
        cached = dict(cached) if cached else None
        if cached and cached.get("state") == "warEnded":
            war_skipped += 1
            continue
        age = _minutes_since((cached or {}).get("attempted_at"), local_now)
        cached_state = (cached or {}).get("state")
        retry_minutes = 2 if cached_state in {"preparation", "inWar"} else 30
        due = force or cached is None or age is None or age >= retry_minutes
        if not due:
            war_skipped += 1
            continue
        try:
            war = service.fetch_cwl_war(war_tag)
            db.conn.execute(
                """INSERT INTO cwl_live_war_cache
                   (war_tag, season, state, status, data_json, error, updated_at, attempted_at)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                   ON CONFLICT(war_tag) DO UPDATE SET
                       season = excluded.season,
                       state = excluded.state,
                       status = excluded.status,
                       data_json = excluded.data_json,
                       error = NULL,
                       updated_at = excluded.updated_at,
                       attempted_at = excluded.attempted_at""",
                (
                    war_tag, period, war.get("state") or "unknown", war.get("status") or "unknown",
                    json.dumps(war, ensure_ascii=False), war.get("synced_at"), attempted_at,
                ),
            )
            war_ok += 1
        except Exception as exc:  # noqa: BLE001 - 单场失败隔离
            war_failed += 1
            if cached:
                db.conn.execute(
                    "UPDATE cwl_live_war_cache SET error = ?, attempted_at = ? WHERE war_tag = ?",
                    (str(exc), attempted_at, war_tag),
                )
            else:
                db.conn.execute(
                    """INSERT INTO cwl_live_war_cache
                       (war_tag, season, state, status, data_json, error, updated_at, attempted_at)
                       VALUES (?, ?, 'unknown', 'error', NULL, ?, NULL, ?)""",
                    (war_tag, period, str(exc), attempted_at),
                )
        db.conn.commit()

    db.close()
    if group_failed == len(teams) and not group_payloads:
        return {"status": "failed", "reason": f"{period} 全部 {len(teams)} 个联赛队伍同步失败"}
    suffix = f"，失败：组 {group_failed} / 战争 {war_failed}" if group_failed or war_failed else ""
    return {
        "status": "success",
        "reason": (
            f"{period} 队伍 {len(teams)}（更新 {group_ok}、等待 {group_waiting}），"
            f"战争更新 {war_ok}、跳过 {war_skipped}{suffix}"
        ),
    }


def _sync_clan_profiles(db: Database, service) -> dict:
    """同步已启用自有部落官方资料，失败时保留上次成功缓存。"""
    profiles = service.fetch_clan_profiles()
    success = 0
    failed = 0
    for result in profiles:
        if result["status"] == "success":
            profile = result["data"]
            db.conn.execute(
                """INSERT INTO clan_profile_cache
                   (clan_tag, clan_name, category, status, data_json, error,
                    updated_at, attempted_at)
                   VALUES (?, ?, ?, 'success', ?, NULL, ?, ?)
                   ON CONFLICT(clan_tag) DO UPDATE SET
                       clan_name = excluded.clan_name,
                       category = excluded.category,
                       status = 'success',
                       data_json = excluded.data_json,
                       error = NULL,
                       updated_at = excluded.updated_at,
                       attempted_at = excluded.attempted_at""",
                (
                    profile["clan_tag"], profile["name"], profile["category"],
                    json.dumps(profile, ensure_ascii=False), profile["synced_at"],
                    result["attempted_at"],
                ),
            )
            success += 1
            continue

        existing = db.conn.execute(
            "SELECT data_json FROM clan_profile_cache WHERE clan_tag = ?",
            (result["clan_tag"],),
        ).fetchone()
        if existing and existing["data_json"]:
            db.conn.execute(
                """UPDATE clan_profile_cache
                   SET status = 'stale', error = ?, attempted_at = ?
                   WHERE clan_tag = ?""",
                (result["error"], result["attempted_at"], result["clan_tag"]),
            )
        else:
            db.conn.execute(
                """INSERT INTO clan_profile_cache
                   (clan_tag, clan_name, category, status, data_json, error,
                    updated_at, attempted_at)
                   VALUES (?, ?, ?, 'error', NULL, ?, NULL, ?)
                   ON CONFLICT(clan_tag) DO UPDATE SET
                       clan_name = excluded.clan_name,
                       category = excluded.category,
                       status = 'error',
                       error = excluded.error,
                       attempted_at = excluded.attempted_at""",
                (
                    result["clan_tag"], result["clan_name"], result["category"],
                    result["error"], result["attempted_at"],
                ),
            )
        failed += 1
    db.conn.commit()
    return {"success": success, "failed": failed}


def _run_coc_sync() -> dict:
    """同步联盟部落成员和部落官方资料。"""
    from modules.coc_sync.service import CocSyncService
    from modules.player.repository import PlayerRepository
    from modules.player.service import PlayerService

    db = Database(config.DB_PATH)
    db.init_schema()
    player_service = PlayerService(PlayerRepository(db.conn))
    svc = CocSyncService(player_service)
    stats = svc.sync_clans()
    profile_stats = _sync_clan_profiles(db, svc)
    db.close()

    reason = (
        f"部落 {stats['clans']}，成员 {stats['members']}，"
        f"新增 {stats['created']}，更新 {stats['updated']}，退部 {stats['left']}，"
        f"部落资料 {profile_stats['success']}/{profile_stats['success'] + profile_stats['failed']}"
    )
    if stats["failed_clans"] or profile_stats["failed"]:
        suffix = f"，成员失败部落 {stats['failed_clans']}" if stats["failed_clans"] else ""
        if profile_stats["failed"]:
            suffix += f"，资料失败 {profile_stats['failed']} 个"
        return {"status": "failed", "reason": reason + suffix}
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


def _run_war_layout() -> dict:
    """增量采集阵型，创建草稿并按配置决定是否群发。"""
    from modules.war_layout.scheduler_job import build_http_service, run_job
    from modules.war_layout.settings import WarLayoutSettings

    settings = WarLayoutSettings.from_env()
    settings.validate_schedule()
    if not settings.enabled:
        return {"status": "skipped", "reason": "WAR_LAYOUT_ENABLED 未启用"}
    settings.validate_x()
    settings.validate_wechat()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(settings.db_path))
    try:
        service = build_http_service(connection, settings)
        # Keep the scheduler in draft-only mode unless the explicit
        # WAR_LAYOUT_AUTO_MASS_SEND switch is enabled.
        result = run_job(service, settings, dry_run=False)
    finally:
        connection.close()
    if result["status"] != "success":
        return result
    if result.get("mass_send_msg_id"):
        reason = f"群发已提交：帖子 {result['posts']}，阵型 {result['layouts']}"
    elif result.get("draft_media_id"):
        reason = f"仅创建草稿：帖子 {result['posts']}，阵型 {result['layouts']}"
    else:
        reason = f"无新增阵型：帖子 {result['posts']}"
    return {**result, "reason": reason}


# ═══════════════════════════════════════════════════════════════════════
# 任务注册表
# ═══════════════════════════════════════════════════════════════════════

JOBS = {
    "current_wars": {
        "name": "当前部落战",
        "interval": 2,
        "run": _run_current_wars,
    },
    "cwl_live": {
        "name": "CWL实时看板",
        "interval": 2,
        "run": _run_cwl_live,
    },
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
    "war_layout": {
        "name": "公众号阵型更新",
        "interval": 1440,
        "daily_at": os.getenv("WAR_LAYOUT_DAILY_TIME", "09:00").strip(),
        "enabled_default": os.getenv("WAR_LAYOUT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"),
        # `--once all` is commonly used for data refreshes. Never make that
        # broad command publish an external message.
        "include_in_all": False,
        "run": _run_war_layout,
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
        next_run_at = _next_run_iso(job) if job.get("daily_at") else None
        db.conn.execute(
            """INSERT OR IGNORE INTO sync_jobs
               (job_id, job_name, interval_min, enabled, next_run_at, last_status)
               VALUES (?, ?, ?, ?, ?, 'never')""",
            (job_id, job["name"], job["interval"], int(job.get("enabled_default", True)), next_run_at),
        )
        db.conn.execute(
            "UPDATE sync_jobs SET job_name = ? WHERE job_id = ?",
            (job["name"], job_id),
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
        if job_id in {"current_wars", "cwl", "cwl_live"}:
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
    if job.get("daily_at"):
        next_iso = _next_run_iso(job)
    else:
        interval = int(_get_row(db, job_id).get("interval_min") or JOBS[job_id]["interval"])
        next_at = datetime.now(timezone.utc).timestamp() + interval * 60
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


def _next_run_iso(job: dict, now: datetime | None = None) -> str:
    """Return the next fixed business-time run as an aware UTC timestamp."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TZ)
    hour, minute = (int(part) for part in job["daily_at"].split(":"))
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).isoformat(timespec="seconds")


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
    targets = [jid for jid, job in JOBS.items() if job.get("include_in_all", True)] if job_id == "all" else [job_id]
    for jid in targets:
        if jid not in JOBS:
            print(f"未知任务: {jid}", file=sys.stderr)
            continue
        # 手动执行 current_wars 的语义是立即全量刷新，不受状态限频影响。
        result = run_one(db, jid, force=(force or jid == "current_wars"))
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
    fields = {"enabled": 1 if enabled else 0}
    if enabled and JOBS[job_id].get("daily_at"):
        fields["next_run_at"] = _next_run_iso(JOBS[job_id])
    _update(db, job_id, **fields)
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="配合 --once：cwl 跳过 12 号判断，cwl_live 跳过月初窗口判断",
    )
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
