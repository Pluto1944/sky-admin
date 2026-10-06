#!/usr/bin/env python3
"""周期数据刷新调度器（常驻 loop 进程）。

统一管理需要周期性执行的任务，状态落 `sync_jobs` 表：

    current_wars 全部自有部落当前战争（战斗日 2 分钟，准备日动态 30/2 分钟）
    cwl_live    当月 CWL 联赛组与逐场战争（战斗日 2 分钟，准备日按轮次限频）
    cwl_assembly 正式名单与各联赛部落集结检查（每月 1 日 14:00 至 3 日 16:00）
    farm_stats  互刷部落统计（每 30 分钟）
    coc_sync    COC 玩家档案（每 6 小时）
    cwl         CWL 联赛战绩（每天触发，day==12 才真正拉取）
    player_details 玩家详情（每天，赛季进攻与活动估算）
    member_combat_stats 成员战斗摘要窗口清理（每天）
    capital_raid_status 都城突袭开启状态（每10分钟检查，已开启部落自动停拉）
    capital_member_stats 都城成员贡献（每6小时检查业务窗口）
    clan_games_stats 竞赛贡献（每6小时检查业务窗口）
    war_layout  公众号阵型群发（每天北京时间 09:00）

用法：
    python scripts/scheduler.py                      # loop 模式（生产，systemd 守护）
    python scripts/scheduler.py --once current_wars  # 手动刷新当前部落战缓存
    python scripts/scheduler.py --once cwl_live --force  # 手动刷新当月 CWL 实时缓存
    python scripts/scheduler.py --once cwl_assembly --force  # 手动重建当月名单快照并刷新集结
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
import hashlib
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
from shared.runtime_identity import capture_runtime_identity  # noqa: E402
from shared.service_runtime import record_service_runtime, touch_service_runtime  # noqa: E402

POLL_SECONDS = 60  # 主循环轮询间隔（秒）
BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
PLAYER_DETAIL_REQUEST_DELAY_SECONDS = max(
    0.0, float(os.getenv("COC_PLAYER_REQUEST_DELAY_SECONDS", "0.05"))
)


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
CWL_WAR_ACTIVE_REFRESH_MINUTES = 2
CWL_WAR_PREPARATION_REFRESH_MINUTES = 30
CWL_WAR_FIRST_PREPARATION_NEAR_START_MINUTES = 2
CWL_WAR_FIRST_PREPARATION_NEAR_START_WINDOW_MINUTES = 30
CWL_WAR_FALLBACK_REFRESH_MINUTES = 30


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


def _cwl_previous_round_just_ended(
    cache: dict,
    previous_war_tags: tuple[str, ...],
    cached_by_war_tag: dict[str, dict],
) -> bool:
    """上一轮确认结束且本场尚未在结束后尝试刷新时返回 True。"""
    if not previous_war_tags:
        return False
    previous = [cached_by_war_tag.get(tag) for tag in previous_war_tags]
    ended = [item for item in previous if item and item.get("state") == "warEnded"]
    if not ended:
        return False
    ended_at = [
        _parse_coc_time(item.get("updated_at") or item.get("attempted_at"))
        for item in ended
    ]
    ended_at = [value for value in ended_at if value is not None]
    checked_at = [
        _parse_coc_time(cache.get("updated_at")),
        _parse_coc_time(cache.get("attempted_at")),
    ]
    checked_at = [value for value in checked_at if value is not None]
    return bool(ended_at) and (not checked_at or max(checked_at) < max(ended_at))


def _cwl_war_refresh_due(
    cache: dict | None,
    *,
    round_number: int,
    previous_war_tags: tuple[str, ...],
    cached_by_war_tag: dict[str, dict],
    now: datetime,
) -> bool:
    """按 CWL 轮次关系判断一场未结束战争是否需要访问官方 API。"""
    if cache is None:
        return True
    state = cache.get("state")
    if state == "warEnded":
        return False
    age = _minutes_since(cache.get("attempted_at"), now)
    if state == "inWar":
        retry_minutes = CWL_WAR_ACTIVE_REFRESH_MINUTES
    elif state == "preparation":
        if round_number > 1 and _cwl_previous_round_just_ended(
            cache, previous_war_tags, cached_by_war_tag
        ):
            return True
        retry_minutes = CWL_WAR_PREPARATION_REFRESH_MINUTES
        if round_number == 1:
            try:
                payload = json.loads(cache.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            start_time = _parse_coc_time(payload.get("start_time"))
            if start_time is not None:
                minutes_until_start = (
                    start_time - now.astimezone(timezone.utc)
                ).total_seconds() / 60
                if minutes_until_start <= CWL_WAR_FIRST_PREPARATION_NEAR_START_WINDOW_MINUTES:
                    retry_minutes = CWL_WAR_FIRST_PREPARATION_NEAR_START_MINUTES
    else:
        retry_minutes = CWL_WAR_FALLBACK_REFRESH_MINUTES
    return age is None or age >= retry_minutes


def _archive_current_war(
    db: Database,
    item: dict,
    keep_ended: int = 45,
    cleanup_active: bool = True,
    affected_player_tags: set[str] | None = None,
) -> bool:
    """归档普通战争；可收集事实发生变化的玩家标签。"""
    from modules.coc_sync.war_history import is_archivable_war, war_history_record

    if not is_archivable_war(item):
        return False
    record = war_history_record(item)
    from modules.player.member_stats import materialize_war_member_facts
    from modules.player.repository import PlayerRepository
    from modules.player.service import PlayerService

    payload = json.dumps(record["data"], ensure_ascii=False, sort_keys=True)
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    db.conn.execute(
        """INSERT INTO war_history_cache
           (clan_tag, war_key, clan_name, category, opponent_tag, opponent_name,
            status, result, preparation_start_time, start_time, end_time,
            source, finalized_at, payload_version, payload_hash, data_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
               source = excluded.source,
               finalized_at = excluded.finalized_at,
               payload_version = excluded.payload_version,
               payload_hash = excluded.payload_hash,
               data_json = excluded.data_json,
               updated_at = excluded.updated_at""",
        (
            record["clan_tag"], record["war_key"], record["clan_name"],
            record["category"], record["opponent_tag"], record["opponent_name"],
            record["status"], record["result"], record["preparation_start_time"],
            record["start_time"], record["end_time"],
            record["source"], record["finalized_at"], record["payload_version"],
            payload_hash, payload, record["updated_at"],
        ),
    )
    fact_changes = materialize_war_member_facts(db.conn, item, record["updated_at"])
    if affected_player_tags is not None:
        affected_player_tags.update(fact_changes.changed_player_tags)
    player_service = PlayerService(PlayerRepository(db.conn))
    for player_tag in fact_changes.activity_player_tags:
        player_service.mark_activity(player_tag, record["updated_at"], "war_attack")
    # 兼容历史升级遗留的未结束草稿；新的归档链路只写 war_ended。
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
    db.conn.execute(
        """DELETE FROM member_war_facts
           WHERE clan_tag = ? AND NOT EXISTS (
               SELECT 1 FROM war_history_cache history
               WHERE history.clan_tag = member_war_facts.clan_tag
                 AND history.war_key = member_war_facts.war_key
                 AND history.status = 'war_ended'
           )""",
        (record["clan_tag"],),
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

        payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        war_key = None
        if item.get("status") == "war_ended":
            from modules.coc_sync.war_history import war_history_key
            war_key = war_history_key(item)
        db.conn.execute(
            """INSERT INTO current_war_cache
               (clan_tag, clan_name, category, status, data_json, error, updated_at,
                attempted_at, failure_count, war_key, expected_end_at, payload_version,
                payload_hash, last_success_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(clan_tag) DO UPDATE SET
                   clan_name = excluded.clan_name,
                   category = excluded.category,
                   status = excluded.status,
                   data_json = excluded.data_json,
                   error = excluded.error,
                   updated_at = excluded.updated_at,
                   attempted_at = excluded.attempted_at,
                   failure_count = excluded.failure_count,
                   war_key = excluded.war_key,
                   expected_end_at = excluded.expected_end_at,
                   payload_version = excluded.payload_version,
                   payload_hash = excluded.payload_hash,
                   last_success_at = excluded.last_success_at""",
            (
                item["clan_tag"],
                item["clan_name"],
                item["category"],
                item["status"],
                payload,
                item.get("error"),
                item["synced_at"],
                attempted_at,
                failure_count,
                war_key,
                item.get("end_time"),
                int(item.get("payload_version") or 1),
                payload_hash,
                item["synced_at"] if item["status"] != "error" else None,
            ),
        )
        if item["status"] != "error":
            # 进行中战争的事实用于活动观察和历史快照，但成员战斗摘要只统计
            # 已结束战争；因此仅在结束状态收集需要重算的账号。
            archived = _archive_current_war(
                db,
                item,
                affected_player_tags=None,
            )
            if archived:
                db.conn.execute(
                    """UPDATE current_war_cache SET history_sealed_at = ?
                       WHERE clan_tag = ? AND war_key = ?""",
                    (item["synced_at"], item["clan_tag"], war_key),
                )
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


def _refresh_cwl_projections(db: Database, teams: list[dict], period: str, timestamp: str) -> tuple[int, int]:
    """标记原始档案完整性，并只为完整分组重建联赛月度投影。"""
    from modules.coc_sync.cwl_live import group_war_tags
    from modules.coc_sync.cwl_projection import group_raw_status, rebuild_league_results
    from modules.coc_sync.official.mapper import normalize_tag

    complete = projected = 0
    for team in teams:
        clan_tag = normalize_tag(team.get("clan_tag"))
        if not clan_tag:
            continue
        group_row = db.conn.execute(
            "SELECT data_json, raw_status FROM cwl_live_group_cache WHERE period = ? AND clan_tag = ?",
            (period, clan_tag),
        ).fetchone()
        if not group_row or not group_row["data_json"]:
            continue
        try:
            group = json.loads(group_row["data_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        tags = group_war_tags(group)
        wars: dict[str, dict] = {}
        if tags:
            placeholders = ",".join("?" for _ in tags)
            rows = db.conn.execute(
                f"SELECT war_tag, data_json FROM cwl_live_war_cache WHERE war_tag IN ({placeholders})",
                tags,
            ).fetchall()
            for row in rows:
                try:
                    wars[normalize_tag(row["war_tag"])] = json.loads(row["data_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
        status = group_raw_status(group, wars)
        db.conn.execute(
            """UPDATE cwl_live_group_cache
               SET raw_status = ?, raw_complete_at = CASE WHEN ? = 'complete' THEN ? ELSE NULL END
               WHERE period = ? AND clan_tag = ?""",
            (status, status, timestamp, period, clan_tag),
        )
        if status != "complete":
            continue
        complete += 1
        if group_row["raw_status"] == "complete":
            continue
        rebuilt, _skipped = rebuild_league_results(
            db.conn, group, wars, team, rebuilt_at=timestamp,
        )
        projected += rebuilt
    return complete, projected


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
                    group_payload = json.dumps(group, ensure_ascii=False, sort_keys=True)
                    group_hash = hashlib.sha256(group_payload.encode("utf-8")).hexdigest()
                    db.conn.execute(
                        """INSERT INTO cwl_live_group_cache
                           (period, clan_tag, team_index, team_alias, team_name, category,
                            league_level, season, state, status, data_json, error,
                            updated_at, attempted_at, source, payload_version, payload_hash)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
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
                               attempted_at = excluded.attempted_at,
                               source = excluded.source,
                               payload_version = excluded.payload_version,
                               payload_hash = excluded.payload_hash""",
                        (
                            period, clan_tag, team["team_index"], team["team_alias"],
                            team.get("team_name"), team["category"], team.get("league_level"),
                            group.get("season"), group.get("state"), status,
                            group_payload, group.get("synced_at"), attempted_at,
                            "official_coc", int(group.get("payload_version") or 1), group_hash,
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
    round_context: dict[str, tuple[int, tuple[str, ...]]] = {}
    for group in group_payloads:
        previous_war_tags: tuple[str, ...] = ()
        for round_number, round_item in enumerate(group.get("rounds") or [], start=1):
            round_war_tags = tuple(group_war_tags({"rounds": [round_item]}))
            for war_tag in round_war_tags:
                round_context.setdefault(
                    war_tag, (round_number, previous_war_tags)
                )
                if war_tag not in seen_war_tags:
                    seen_war_tags.add(war_tag)
                    unique_war_tags.append(war_tag)
            previous_war_tags = round_war_tags

    cached_by_war_tag: dict[str, dict] = {}
    if unique_war_tags:
        placeholders = ",".join("?" for _ in unique_war_tags)
        cached_by_war_tag = {
            row["war_tag"]: dict(row)
            for row in db.conn.execute(
                f"SELECT * FROM cwl_live_war_cache WHERE war_tag IN ({placeholders})",
                unique_war_tags,
            ).fetchall()
        }

    war_ok = war_skipped = war_failed = 0
    from modules.player.member_stats import cwl_attack_counts
    from modules.player.repository import PlayerRepository
    from modules.player.service import PlayerService
    player_service = PlayerService(PlayerRepository(db.conn))
    own_cwl_tags = {team["clan_tag"] for team in teams if team.get("clan_tag")}
    for war_tag in unique_war_tags:
        cached = cached_by_war_tag.get(war_tag)
        if cached and cached.get("state") == "warEnded":
            war_skipped += 1
            continue
        round_number, previous_war_tags = round_context.get(war_tag, (0, ()))
        due = force or _cwl_war_refresh_due(
            cached,
            round_number=round_number,
            previous_war_tags=previous_war_tags,
            cached_by_war_tag=cached_by_war_tag,
            now=local_now,
        )
        if not due:
            war_skipped += 1
            continue
        try:
            war = service.fetch_cwl_war(war_tag)
            old_payload = None
            if cached and cached.get("data_json"):
                try:
                    old_payload = json.loads(cached["data_json"])
                except (TypeError, json.JSONDecodeError):
                    old_payload = None
            before_attacks = cwl_attack_counts(old_payload, own_cwl_tags)
            after_attacks = cwl_attack_counts(war, own_cwl_tags)
            war_payload = json.dumps(war, ensure_ascii=False, sort_keys=True)
            war_hash = hashlib.sha256(war_payload.encode("utf-8")).hexdigest()
            db.conn.execute(
                """INSERT INTO cwl_live_war_cache
                   (war_tag, season, state, status, data_json, error, updated_at, attempted_at,
                    source, finalized_at, payload_version, payload_hash)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(war_tag) DO UPDATE SET
                       season = excluded.season,
                       state = excluded.state,
                       status = excluded.status,
                       data_json = excluded.data_json,
                       error = NULL,
                       updated_at = excluded.updated_at,
                       attempted_at = excluded.attempted_at,
                       source = excluded.source,
                       finalized_at = excluded.finalized_at,
                       payload_version = excluded.payload_version,
                       payload_hash = excluded.payload_hash""",
                (
                    war_tag, period, war.get("state") or "unknown", war.get("status") or "unknown",
                    war_payload, war.get("synced_at"), attempted_at,
                    "official_coc", war.get("synced_at") if war.get("status") == "war_ended" else None,
                    int(war.get("payload_version") or 1), war_hash,
                ),
            )
            for player_tag, attacks in after_attacks.items():
                if player_tag in before_attacks and attacks > before_attacks[player_tag]:
                    player_service.mark_activity(
                        player_tag, war.get("synced_at") or attempted_at, "cwl_attack"
                    )
            cached_by_war_tag[war_tag] = {
                **(cached or {}),
                "war_tag": war_tag,
                "state": war.get("state") or "unknown",
                "status": war.get("status") or "unknown",
                "data_json": war_payload,
                "updated_at": war.get("synced_at"),
                "attempted_at": attempted_at,
            }
            war_ok += 1
        except Exception as exc:  # noqa: BLE001 - 单场失败隔离
            war_failed += 1
            if cached:
                db.conn.execute(
                    "UPDATE cwl_live_war_cache SET error = ?, attempted_at = ? WHERE war_tag = ?",
                    (str(exc), attempted_at, war_tag),
                )
                cached_by_war_tag[war_tag] = {
                    **cached,
                    "error": str(exc),
                    "attempted_at": attempted_at,
                }
            else:
                db.conn.execute(
                    """INSERT INTO cwl_live_war_cache
                       (war_tag, season, state, status, data_json, error, updated_at, attempted_at)
                       VALUES (?, ?, 'unknown', 'error', NULL, ?, NULL, ?)""",
                    (war_tag, period, str(exc), attempted_at),
                )
                cached_by_war_tag[war_tag] = {
                    "war_tag": war_tag,
                    "state": "unknown",
                    "status": "error",
                    "error": str(exc),
                    "attempted_at": attempted_at,
                }
        db.conn.commit()

    complete_groups, projected_rows = _refresh_cwl_projections(db, teams, period, attempted_at)
    db.conn.commit()
    db.close()
    if group_failed == len(teams) and not group_payloads:
        return {"status": "failed", "reason": f"{period} 全部 {len(teams)} 个联赛队伍同步失败"}
    suffix = f"，失败：组 {group_failed} / 战争 {war_failed}" if group_failed or war_failed else ""
    return {
        "status": "success",
        "reason": (
            f"{period} 队伍 {len(teams)}（更新 {group_ok}、等待 {group_waiting}），"
            f"战争更新 {war_ok}、跳过 {war_skipped}，完整分组 {complete_groups}、投影 {projected_rows} 行{suffix}"
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


def _run_player_details() -> dict:
    """每日补齐玩家详情，用于赛季进攻数和最近数据活动估算。"""
    from modules.coc_sync.official.mapper import map_player
    from modules.coc_sync.service import CocSyncService
    from modules.player.repository import PlayerRepository
    from modules.player.service import PlayerService

    db = Database(config.DB_PATH)
    db.init_schema()
    repo = PlayerRepository(db.conn)
    player_service = PlayerService(repo)
    service = CocSyncService(api_client=None)
    rows = db.conn.execute(
        "SELECT player_tag FROM accounts WHERE membership_status = 'member' ORDER BY player_tag"
    ).fetchall()
    success = 0
    failed = 0
    for row in rows:
        try:
            raw = service.fetch_player(row["player_tag"])
            player_service.update_from_coc(map_player(raw, set(config.ALLIANCE_CLAN_TAGS)))
            success += 1
        except Exception as exc:  # noqa: BLE001 - 单玩家失败隔离
            failed += 1
            print(f"[warn] 玩家详情 {row['player_tag']} 同步失败：{exc}", file=sys.stderr)
        if PLAYER_DETAIL_REQUEST_DELAY_SECONDS:
            time.sleep(PLAYER_DETAIL_REQUEST_DELAY_SECONDS)
    db.close()
    if not success and failed:
        return {"status": "failed", "reason": f"全部 {failed} 名玩家详情同步失败"}
    suffix = f"，失败 {failed}" if failed else ""
    return {"status": "success", "reason": f"同步玩家详情 {success}{suffix}"}


def _capital_window_open(local_now: datetime) -> bool:
    return (
        (local_now.weekday() == 1 and local_now.hour >= 3)
        or local_now.weekday() == 2
    )


def _run_capital_raid_status(force: bool = False, now: datetime | None = None) -> dict:
    """同步自有部落当前突袭周末是否已经开启。"""
    from modules.coc_sync.capital_status import (
        raid_weekend_window,
        summarize_capital_raid_status,
    )
    from modules.coc_sync.official.mapper import normalize_tag
    from modules.coc_sync.service import CocSyncService

    clans = [clan for clan in config.CLANS if clan.get("enabled", True)]
    if not clans:
        return {"status": "skipped", "reason": "没有配置已启用部落"}

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attempted_at = current.isoformat(timespec="seconds")
    weekend_start, weekend_end = raid_weekend_window(current)
    weekend_start_iso = weekend_start.isoformat(timespec="seconds")
    weekend_end_iso = weekend_end.isoformat(timespec="seconds")
    active = current < weekend_end

    db = Database(config.DB_PATH)
    db.init_schema()
    cached_by_tag = {
        row["clan_tag"]: dict(row)
        for row in db.conn.execute("SELECT * FROM capital_raid_status_cache").fetchall()
    }

    due = []
    locally_finalized = 0
    for clan in clans:
        clan_tag = normalize_tag(clan.get("tag"))
        cached = cached_by_tag.get(clan_tag)
        same_weekend = bool(cached and cached.get("weekend_start") == weekend_start_iso)
        if not force and same_weekend:
            status = cached.get("status")
            if active and status == "ongoing" and not cached.get("error"):
                continue
            if not active and status in {"ended", "missed"} and not cached.get("error"):
                continue
            if not active and status == "ongoing":
                db.conn.execute(
                    """UPDATE capital_raid_status_cache
                       SET status = 'ended', error = NULL, updated_at = ?, attempted_at = ?,
                           failure_count = 0
                       WHERE clan_tag = ?""",
                    (attempted_at, attempted_at, clan_tag),
                )
                locally_finalized += 1
                continue
            age = _minutes_since(cached.get("attempted_at"), current)
            refresh_minutes = 10 if active else 60
            if age is not None and age < refresh_minutes:
                continue
        due.append((clan, clan_tag, cached))

    service = CocSyncService()
    success = 0
    failed = 0
    for clan, clan_tag, previous in due:
        try:
            seasons = service.fetch_capital_raid_seasons(clan_tag, limit=2)
            status = summarize_capital_raid_status(seasons, current)
        except Exception as exc:  # noqa: BLE001 - 单部落失败隔离
            failure_count = int((previous or {}).get("failure_count") or 0) + 1
            if previous and previous.get("weekend_start") == weekend_start_iso:
                db.conn.execute(
                    """UPDATE capital_raid_status_cache
                       SET clan_name = ?, error = ?, attempted_at = ?, failure_count = ?
                       WHERE clan_tag = ?""",
                    (
                        clan.get("name") or clan_tag,
                        str(exc), attempted_at, failure_count, clan_tag,
                    ),
                )
            else:
                db.conn.execute(
                    """INSERT INTO capital_raid_status_cache
                       (clan_tag, clan_name, status, raid_state, weekend_start,
                        weekend_end, error, updated_at, attempted_at, failure_count)
                       VALUES (?, ?, 'sync_pending', NULL, ?, ?, ?, NULL, ?, ?)
                       ON CONFLICT(clan_tag) DO UPDATE SET
                           clan_name = excluded.clan_name,
                           status = excluded.status,
                           raid_state = NULL,
                           weekend_start = excluded.weekend_start,
                           weekend_end = excluded.weekend_end,
                           error = excluded.error,
                           updated_at = NULL,
                           attempted_at = excluded.attempted_at,
                           failure_count = excluded.failure_count""",
                    (
                        clan_tag, clan.get("name") or clan_tag,
                        weekend_start_iso, weekend_end_iso, str(exc),
                        attempted_at, failure_count,
                    ),
                )
            failed += 1
            print(f"[warn] 都城状态 {clan_tag} 同步失败：{exc}", file=sys.stderr)
            continue

        db.conn.execute(
            """INSERT INTO capital_raid_status_cache
               (clan_tag, clan_name, status, raid_state, weekend_start,
                weekend_end, error, updated_at, attempted_at, failure_count)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, 0)
               ON CONFLICT(clan_tag) DO UPDATE SET
                   clan_name = excluded.clan_name,
                   status = excluded.status,
                   raid_state = excluded.raid_state,
                   weekend_start = excluded.weekend_start,
                   weekend_end = excluded.weekend_end,
                   error = NULL,
                   updated_at = excluded.updated_at,
                   attempted_at = excluded.attempted_at,
                   failure_count = 0""",
            (
                clan_tag, clan.get("name") or clan_tag,
                status["status"], status["raid_state"],
                status["weekend_start"], status["weekend_end"],
                attempted_at, attempted_at,
            ),
        )
        success += 1

    db.conn.commit()
    db.close()
    if not due and not locally_finalized:
        return {"status": "skipped", "reason": f"{len(clans)} 个部落状态无需刷新"}
    if not success and failed and not locally_finalized:
        return {"status": "failed", "reason": f"全部 {failed} 个部落都城状态同步失败"}
    details = [f"同步 {success} 个部落"]
    if locally_finalized:
        details.append(f"结束 {locally_finalized} 个部落")
    if failed:
        details.append(f"失败 {failed}")
    skipped = len(clans) - len(due) - locally_finalized
    if skipped:
        details.append(f"跳过 {skipped}")
    return {"status": "success", "reason": "，".join(details)}


def _run_capital_member_stats(force: bool = False, now: datetime | None = None) -> dict:
    """每周二抓取最近已结束突袭周末；失败时周三仍可按 6 小时间隔重试。"""
    from modules.coc_sync.official.mapper import normalize_tag
    from modules.coc_sync.service import CocSyncService

    current = now or datetime.now(timezone.utc)
    local_now = current.astimezone(BUSINESS_TZ)
    if not force and not _capital_window_open(local_now):
        return {"status": "skipped", "reason": "不在周二03:00至周三的都城统计窗口"}

    db = Database(config.DB_PATH)
    db.init_schema()
    week_start = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    success_marker = week_start.replace(hour=3).astimezone(timezone.utc).isoformat(timespec="seconds")
    if not force:
        row = db.conn.execute(
            "SELECT MAX(fetched_at) AS fetched_at FROM capital_raid_member_results"
        ).fetchone()
        if row and row["fetched_at"] and row["fetched_at"] >= success_marker:
            db.close()
            return {"status": "skipped", "reason": "本周都城成员统计已完成"}

    service = CocSyncService()
    fetched_at = current.astimezone(timezone.utc).isoformat(timespec="seconds")
    success = 0
    failed = 0
    written = 0
    for clan in config.CLANS:
        if not clan.get("enabled", True):
            continue
        clan_tag = normalize_tag(clan.get("tag"))
        try:
            seasons = service.fetch_capital_raid_seasons(clan_tag, limit=8)
        except Exception as exc:  # noqa: BLE001 - 单部落失败隔离
            failed += 1
            print(f"[warn] 都城统计 {clan_tag} 同步失败：{exc}", file=sys.stderr)
            continue
        success += 1
        for season in seasons:
            state = str(season.get("state") or "").lower()
            if state and state != "ended":
                continue
            start_time = season.get("startTime")
            if not start_time:
                continue
            for member in season.get("members") or []:
                player_tag = normalize_tag(member.get("tag"))
                if not player_tag:
                    continue
                db.conn.execute(
                    """INSERT INTO capital_raid_member_results
                       (clan_tag, start_time, end_time, player_tag, player_name,
                        attack_limit, bonus_attack_limit, attacks,
                        capital_resources_looted, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(clan_tag, start_time, player_tag) DO UPDATE SET
                           end_time = excluded.end_time,
                           player_name = excluded.player_name,
                           attack_limit = excluded.attack_limit,
                           bonus_attack_limit = excluded.bonus_attack_limit,
                           attacks = excluded.attacks,
                           capital_resources_looted = excluded.capital_resources_looted,
                           fetched_at = excluded.fetched_at""",
                    (
                        clan_tag, start_time, season.get("endTime"), player_tag,
                        member.get("name"), int(member.get("attackLimit") or 0),
                        int(member.get("bonusAttackLimit") or 0),
                        int(member.get("attacks") or 0),
                        int(member.get("capitalResourcesLooted") or 0), fetched_at,
                    ),
                )
                written += 1
    db.conn.commit()
    db.close()
    if not success and failed:
        return {"status": "failed", "reason": f"全部 {failed} 个部落都城统计失败"}
    suffix = f"，失败部落 {failed}" if failed else ""
    return {"status": "success", "reason": f"都城部落 {success}，写入 {written} 条{suffix}"}


def _achievement_value(player: dict, name: str) -> int:
    for achievement in player.get("achievements") or []:
        if achievement.get("name") == name:
            try:
                return int(achievement.get("value") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _games_window_open(local_now: datetime) -> bool:
    return (local_now.day == 29 and local_now.hour >= 3) or local_now.day == 30


def _previous_period(local_now: datetime) -> str:
    first = local_now.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _run_clan_games_stats(force: bool = False, now: datetime | None = None) -> dict:
    """每月29日保存竞赛累计成就快照并与上期基准做差。"""
    from modules.coc_sync.official.mapper import map_player, normalize_tag
    from modules.coc_sync.service import CocSyncService
    from modules.player.repository import PlayerRepository
    from modules.player.service import PlayerService

    current = now or datetime.now(timezone.utc)
    local_now = current.astimezone(BUSINESS_TZ)
    in_result_window = _games_window_open(local_now)
    if not force and not in_result_window:
        return {"status": "skipped", "reason": "不在29日03:00至30日的竞赛统计窗口"}
    if force and not in_result_window and local_now.day >= 22:
        return {"status": "skipped", "reason": "竞赛已经开始，拒绝建立不完整的月初基准"}
    baseline_only = force and not in_result_window
    period = _previous_period(local_now) if baseline_only else local_now.strftime("%Y-%m")
    fetched_at = current.astimezone(timezone.utc).isoformat(timespec="seconds")
    db = Database(config.DB_PATH)
    db.init_schema()
    repo = PlayerRepository(db.conn)
    members = db.conn.execute(
        "SELECT player_tag FROM accounts WHERE membership_status = 'member' ORDER BY player_tag"
    ).fetchall()
    if not force:
        done = db.conn.execute(
            "SELECT COUNT(*) AS count FROM clan_games_member_snapshots WHERE period = ?",
            (period,),
        ).fetchone()["count"]
        if members and done >= len(members):
            db.close()
            return {"status": "skipped", "reason": f"{period} 竞赛成员统计已完成"}

    player_service = PlayerService(repo)
    service = CocSyncService()
    success = 0
    failed = 0
    for row in members:
        player_tag = row["player_tag"]
        try:
            player = service.fetch_player(player_tag)
            player_service.update_from_coc(map_player(player, set(config.ALLIANCE_CLAN_TAGS)))
            cumulative = _achievement_value(player, "Games Champion")
            previous = db.conn.execute(
                """SELECT cumulative_value FROM clan_games_member_snapshots
                   WHERE player_tag = ? AND period < ? ORDER BY period DESC LIMIT 1""",
                (player_tag, period),
            ).fetchone()
            complete = previous is not None and cumulative >= int(previous["cumulative_value"] or 0)
            points = cumulative - int(previous["cumulative_value"] or 0) if complete else None
            db.conn.execute(
                """INSERT INTO clan_games_member_snapshots
                   (period, player_tag, player_name, clan_tag, cumulative_value,
                    points, complete, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(period, player_tag) DO UPDATE SET
                       player_name = excluded.player_name,
                       clan_tag = excluded.clan_tag,
                       cumulative_value = excluded.cumulative_value,
                       points = excluded.points,
                       complete = excluded.complete,
                       fetched_at = excluded.fetched_at""",
                (
                    period, player_tag, player.get("name"),
                    normalize_tag((player.get("clan") or {}).get("tag")), cumulative,
                    points, int(complete), fetched_at,
                ),
            )
            db.conn.commit()
            success += 1
        except Exception as exc:  # noqa: BLE001 - 单玩家失败隔离
            failed += 1
            print(f"[warn] 竞赛统计 {player_tag} 同步失败：{exc}", file=sys.stderr)
        if PLAYER_DETAIL_REQUEST_DELAY_SECONDS:
            time.sleep(PLAYER_DETAIL_REQUEST_DELAY_SECONDS)
    db.close()
    if not success and failed:
        return {"status": "failed", "reason": f"全部 {failed} 名玩家竞赛统计失败"}
    suffix = f"，失败 {failed}" if failed else ""
    action = "竞赛结束基准" if baseline_only else "竞赛成员"
    return {"status": "success", "reason": f"{period} {action} {success}{suffix}"}


def _run_member_combat_stats() -> dict:
    """补齐历史档案的逐玩家事实；成员摘要在 API 查询时实时派生。"""
    from modules.player.member_stats import materialize_cached_war_facts

    db = Database(config.DB_PATH)
    db.init_schema()
    count = materialize_cached_war_facts(db.conn)
    db.conn.commit()
    db.close()
    return {"status": "success", "reason": f"物化 {count} 场普通战玩家事实"}


def _run_cwl_assembly(force: bool = False, now: datetime | None = None) -> dict:
    """生成正式名单月度快照，并按部落刷新集结检查缓存。"""
    from modules.coc_sync.cwl_assembly import (
        compare_roster_members,
        parse_published_roster,
        published_sheet_name,
        roster_content_hash,
        roster_membership_signature,
    )
    from modules.coc_sync.official.mapper import normalize_tag
    from modules.coc_sync.service import CocSyncService
    from shared.io_adapter.tencent_doc import TencentDocAdapter

    local_now = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TZ)
    period = local_now.strftime("%Y-%m")
    window_start = local_now.replace(day=1, hour=14, minute=0, second=0, microsecond=0)
    window_end = local_now.replace(day=3, hour=16, minute=0, second=0, microsecond=0)
    if not force and local_now < window_start:
        return {"status": "skipped", "reason": f"{period} 集结检查将在 1 日 14:00 开始"}

    db = Database(config.DB_PATH)
    db.init_schema()
    teams = [dict(row) for row in db.conn.execute(
        """SELECT period, team_index, team_alias, team_name, clan_tag,
                  category, member_count, league_level, leader
           FROM league_teams
           WHERE period = ? AND category IN ('combat', 'shell')
           ORDER BY team_index""",
        (period,),
    ).fetchall()]
    if not teams:
        db.close()
        return {"status": "skipped", "reason": f"{period} 无 league_teams 联赛队伍"}

    attempted_at = local_now.astimezone(timezone.utc).isoformat(timespec="seconds")
    snapshot_row = db.conn.execute(
        "SELECT * FROM cwl_roster_snapshots WHERE period = ? AND is_active = 1",
        (period,),
    ).fetchone()
    snapshot = dict(snapshot_row) if snapshot_row else None

    if not force and local_now >= window_end and snapshot is None:
        db.close()
        return {"status": "skipped", "reason": f"{period} 集结窗口已结束且没有正式名单快照"}

    if snapshot is None or force:
        source_sheet = published_sheet_name(period)
        file_id = os.environ.get("PUBLISH_DOC_FILE_ID", "").strip()
        if not file_id:
            db.close()
            return {"status": "failed", "reason": "未配置 PUBLISH_DOC_FILE_ID"}
        try:
            rows = TencentDocAdapter().read_sheet(file_id, source_sheet)
            roster = parse_published_roster(rows, teams)
            missing_leaders = [
                team for team in roster.get("teams", []) if not team.get("leader_name")
            ]
            if missing_leaders:
                profile_service = CocSyncService()
                for team in missing_leaders:
                    try:
                        profile = profile_service.fetch_clan_profile(team["clan_tag"])
                        team["leader_name"] = str(profile.get("leader_name") or "").strip()
                    except Exception:  # noqa: BLE001 - 抬头补充失败不应阻断正式成员快照
                        pass
            content_hash = roster_content_hash(roster)
            previous_roster = None
            if snapshot is not None:
                try:
                    previous_roster = json.loads(snapshot["data_json"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    previous_roster = None
            preserve_assembly = (
                previous_roster is not None
                and roster_membership_signature(previous_roster)
                == roster_membership_signature(roster)
            )
            next_revision = db.conn.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM cwl_roster_snapshots WHERE period = ?",
                (period,),
            ).fetchone()[0]
            with db.conn:
                db.conn.execute(
                    "UPDATE cwl_roster_snapshots SET is_active = 0 WHERE period = ? AND is_active = 1",
                    (period,),
                )
                cursor = db.conn.execute(
                    """INSERT INTO cwl_roster_snapshots
                       (period, revision, is_active, source_sheet, content_hash, data_json, created_at)
                       VALUES (?, ?, 1, ?, ?, ?, ?)""",
                    (
                        period, next_revision, source_sheet, content_hash,
                        json.dumps(roster, ensure_ascii=False), attempted_at,
                    ),
                )
                if snapshot is not None:
                    if preserve_assembly:
                        # 已冻结的集结记录必须继续指向实际核对时的 revision；
                        # 最新 active revision 仅供尚未冻结的队伍继续检查/展示。
                        pass
                    else:
                        db.conn.execute("DELETE FROM cwl_assembly_cache WHERE period = ?", (period,))
            snapshot = {
                "id": cursor.lastrowid,
                "period": period,
                "revision": next_revision,
                "data_json": json.dumps(roster, ensure_ascii=False),
            }
        except Exception as exc:  # noqa: BLE001 - 失败不能写入半成品快照
            db.close()
            return {"status": "failed", "reason": f"正式名单快照失败：{exc}"}

    try:
        roster = json.loads(snapshot["data_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        db.close()
        return {"status": "failed", "reason": "正式名单快照内容损坏"}

    # 截止时冻结尚未开启的部落；此后日常任务不再发外部请求。
    if not force and local_now >= window_end:
        changed = 0
        for team in roster.get("teams", []):
            clan_tag = normalize_tag(team.get("clan_tag"))
            existing = db.conn.execute(
                "SELECT locked_at FROM cwl_assembly_cache WHERE period = ? AND clan_tag = ?",
                (period, clan_tag),
            ).fetchone()
            if existing and existing["locked_at"]:
                continue
            db.conn.execute(
                """INSERT INTO cwl_assembly_cache
                   (period, clan_tag, roster_snapshot_id, team_index, team_alias,
                    team_name, category, status, data_json, error, updated_at,
                    attempted_at, locked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'cutoff', NULL, NULL, NULL, ?, ?)
                   ON CONFLICT(period, clan_tag) DO UPDATE SET
                       status = 'cutoff',
                       attempted_at = excluded.attempted_at,
                       locked_at = excluded.locked_at""",
                (
                    period, clan_tag, snapshot["id"], team.get("team_index"),
                    team.get("team_alias") or clan_tag, team.get("team_name"),
                    team.get("category") or "combat", attempted_at, attempted_at,
                ),
            )
            changed += 1
        db.conn.commit()
        db.close()
        return {"status": "skipped", "reason": f"{period} 集结窗口已结束，冻结 {changed} 个部落"}

    service = CocSyncService()
    success = failed = locked = skipped = 0
    for team in roster.get("teams", []):
        clan_tag = normalize_tag(team.get("clan_tag"))
        cached_row = db.conn.execute(
            "SELECT * FROM cwl_assembly_cache WHERE period = ? AND clan_tag = ?",
            (period, clan_tag),
        ).fetchone()
        cached = dict(cached_row) if cached_row else None
        if cached and cached.get("locked_at"):
            skipped += 1
            continue

        try:
            members = service.fetch_clan_members(clan_tag, team.get("team_name"))
            comparison = compare_roster_members(team.get("members") or [], members)
        except Exception as exc:  # noqa: BLE001 - 单部落失败隔离并保留成功缓存
            failed += 1
            if cached:
                db.conn.execute(
                    """UPDATE cwl_assembly_cache
                       SET error = ?, attempted_at = ?
                       WHERE period = ? AND clan_tag = ?""",
                    (str(exc), attempted_at, period, clan_tag),
                )
            else:
                db.conn.execute(
                    """INSERT INTO cwl_assembly_cache
                       (period, clan_tag, roster_snapshot_id, team_index, team_alias,
                        team_name, category, status, data_json, error, updated_at,
                        attempted_at, locked_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'error', NULL, ?, NULL, ?, NULL)""",
                    (
                        period, clan_tag, snapshot["id"], team.get("team_index"),
                        team.get("team_alias") or clan_tag, team.get("team_name"),
                        team.get("category") or "combat", str(exc), attempted_at,
                    ),
                )
            db.conn.commit()
            continue

        status = "checking"
        locked_at = None
        group_error = None
        try:
            group = service.fetch_cwl_group(team)
            if group and group.get("season") == period:
                status = "started"
                locked_at = attempted_at
                locked += 1
        except Exception as exc:  # noqa: BLE001 - 成员结果仍可成功缓存，下轮重试开赛检测
            group_error = f"联赛开启状态查询失败：{exc}"

        payload = {**team, **comparison}
        db.conn.execute(
            """INSERT INTO cwl_assembly_cache
               (period, clan_tag, roster_snapshot_id, team_index, team_alias,
                team_name, category, status, data_json, error, updated_at,
                attempted_at, locked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(period, clan_tag) DO UPDATE SET
                   roster_snapshot_id = excluded.roster_snapshot_id,
                   team_index = excluded.team_index,
                   team_alias = excluded.team_alias,
                   team_name = excluded.team_name,
                   category = excluded.category,
                   status = excluded.status,
                   data_json = excluded.data_json,
                   error = excluded.error,
                   updated_at = excluded.updated_at,
                   attempted_at = excluded.attempted_at,
                   locked_at = excluded.locked_at""",
            (
                period, clan_tag, snapshot["id"], team.get("team_index"),
                team.get("team_alias") or clan_tag, team.get("team_name"),
                team.get("category") or "combat", status,
                json.dumps(payload, ensure_ascii=False), group_error,
                attempted_at, attempted_at, locked_at,
            ),
        )
        db.conn.commit()
        success += 1

    db.close()
    if not success and failed:
        return {"status": "failed", "reason": f"全部 {failed} 个待检查部落同步失败"}
    suffix = f"，失败 {failed}" if failed else ""
    if locked:
        suffix += f"，本轮冻结 {locked}"
    if skipped:
        suffix += f"，已冻结跳过 {skipped}"
    return {"status": "success", "reason": f"检查 {success} 个联赛部落{suffix}"}


def _run_cwl(force: bool = False) -> dict:
    """只从已完整的本地 CWL 原始档案重建 league_results。"""
    today = datetime.now(BUSINESS_TZ)
    if not force and today.day != 12:
        return {"status": "skipped", "reason": f"非12号（今天{today.day}号），跳过"}
    period = today.strftime("%Y-%m")
    db = Database(config.DB_PATH)
    db.init_schema()
    teams = [dict(row) for row in db.conn.execute(
        """SELECT period, team_index, team_alias, team_name, clan_tag,
                  category, member_count, league_level
           FROM league_teams WHERE period = ? AND category IN ('combat', 'shell')
           ORDER BY team_index""",
        (period,),
    ).fetchall()]
    if not teams:
        db.close()
        return {"status": "skipped", "reason": f"{period} 无 league_teams 联赛队伍"}
    complete, written = _refresh_cwl_projections(
        db, teams, period, today.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )
    db.conn.commit()
    db.close()
    if not complete:
        return {"status": "skipped", "reason": f"{period} 尚无完整 CWL 原始档案"}
    return {"status": "success", "reason": f"{period} 完整分组 {complete}，重建 {written} 条战绩投影"}


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
    "cwl_assembly": {
        "name": "CWL集结检查",
        "interval": 5,
        "run": _run_cwl_assembly,
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
    "player_details": {
        "name": "COC玩家详情",
        "interval": 1440,
        "include_in_all": False,
        "run": _run_player_details,
    },
    "member_combat_stats": {
        "name": "成员战斗摘要",
        "interval": 1440,
        "run": _run_member_combat_stats,
    },
    "capital_raid_status": {
        "name": "都城突袭状态",
        "interval": 10,
        "run": _run_capital_raid_status,
    },
    "capital_member_stats": {
        "name": "都城成员贡献",
        "interval": 360,
        "include_in_all": False,
        "run": _run_capital_member_stats,
    },
    "clan_games_stats": {
        "name": "竞赛成员贡献",
        "interval": 360,
        "include_in_all": False,
        "run": _run_clan_games_stats,
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
        if job_id in {
            "current_wars", "cwl", "cwl_live", "cwl_assembly",
            "capital_raid_status", "capital_member_stats", "clan_games_stats",
        }:
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
    runtime_identity = capture_runtime_identity("scheduler")
    record_service_runtime(db.conn, runtime_identity)
    print(
        f"[{now_iso()}] 调度器启动，轮询间隔 {POLL_SECONDS}s，"
        f"版本 {runtime_identity.release_version}，提交 {runtime_identity.git_commit[:12]}"
    )
    while True:
        touch_service_runtime(db.conn, "scheduler")
        now_ts = datetime.now(timezone.utc).timestamp()
        for job_id, job in JOBS.items():
            row = _get_row(db, job_id)
            if not row.get("enabled", 1):
                continue
            next_ts = _parse_next_run_at(row)
            if next_ts is not None and now_ts < next_ts:
                continue
            result = run_one(db, job_id)
            touch_service_runtime(db.conn, "scheduler")
            print(f"[{now_iso()}] {job['name']}({job_id}): {result.get('status')} {result.get('reason', '')}")
        touch_service_runtime(db.conn, "scheduler")
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
        help="配合 --once：cwl 跳过 12 号判断；cwl_live/cwl_assembly 跳过月初窗口判断",
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
