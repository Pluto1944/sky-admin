"""API 路由定义。

当前提供：
- GET /api/ping            健康检查
- GET /api/members          成员列表（读取 accounts 表）
- GET /api/clan/overview    自有部落概览（读取 accounts 缓存）
- GET /api/clan/league-stats  联赛战绩统计（滚动窗口三星率）
- POST /api/wechat/login    微信登录
- GET /api/wechat/me        当前用户信息
- POST /api/wechat/bind     绑定游戏账号
"""
from __future__ import annotations

import json
import os
import requests
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from modules.player.repository import PlayerRepository
from modules.coc_sync.current_war import current_war_summary
from modules.coc_sync.cwl_live import build_cwl_dashboard, group_war_tags
from modules.coc_sync.official.mapper import normalize_tag
from modules.coc_sync.war_history import war_history_summary
from .deps import get_repo, get_db
from .auth import create_token, require_user
from shared.db.connection import Database
from config import CLANS, CLAN_CATEGORY_LABELS, DB_PATH, LEAGUE_COMBAT, get_farm_clans

router = APIRouter(prefix="/api")


@router.get("/ping")
def ping():
    """健康检查接口。返回服务状态和时间戳。"""
    from datetime import datetime, timezone

    return {
        "status": "ok",
        "service": "sky-admin-api",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/members")
def list_members(repo: PlayerRepository = Depends(get_repo)):
    """获取所有 COC 成员列表。

    从 accounts 表读取，返回每个成员的：
    - player_tag, account_name, exp_level, trophies, league_name
    - town_hall_level, clan_tag, clan_role, status
    - membership_status, last_synced_at, updated_at
    """
    try:
        members = repo.list_all()
        return {
            "count": len(members),
            "members": members,
            "clans": [
                {"tag": clan["tag"], "name": clan.get("name") or clan["tag"]}
                for clan in CLANS
                if clan.get("enabled", True)
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {e}")


# ── 当前部落战 ────────────────────────────────────────────────


def _enabled_clans() -> list[dict]:
    return [clan for clan in CLANS if clan.get("enabled", True)]


def _safe_coc_raw(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _safe_number(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clan_overview_items(db: Database) -> list[dict]:
    """从本地 accounts 快照聚合自有部落概览。

    请求路径不访问 COC API；每个配置部落始终占一个固定顺序的卡片，
    即使尚未同步到成员数据，也返回空聚合而不影响其他部落。
    """
    rows = db.conn.execute(
        """SELECT account_name, town_hall_level, trophies, clan_tag, clan_role,
                  coc_raw, last_synced_at
           FROM accounts
           WHERE membership_status = 'member'"""
    ).fetchall()
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        tag = normalize_tag(row["clan_tag"])
        if tag:
            grouped[tag].append(row)

    result = []
    for order, configured in enumerate(_enabled_clans()):
        tag = normalize_tag(configured["tag"])
        members = grouped.get(tag, [])
        town_halls: dict[int, int] = defaultdict(int)
        roles: dict[str, int] = defaultdict(int)
        leaders = []
        total_donations = 0
        total_received = 0
        synced_at = []
        town_hall_total = 0
        trophies_total = 0
        trophies_count = 0

        for member in members:
            town_hall = _safe_number(member["town_hall_level"])
            if town_hall > 0:
                town_halls[town_hall] += 1
                town_hall_total += town_hall
            trophies = _safe_number(member["trophies"])
            if trophies > 0:
                trophies_total += trophies
                trophies_count += 1
            role = member["clan_role"] or "member"
            roles[role] += 1
            if role == "leader" and member["account_name"]:
                leaders.append(member["account_name"])
            raw = _safe_coc_raw(member["coc_raw"])
            total_donations += _safe_number(raw.get("donations"))
            total_received += _safe_number(raw.get("donationsReceived"))
            if member["last_synced_at"]:
                synced_at.append(member["last_synced_at"])

        member_count = len(members)
        town_hall_count = sum(town_halls.values())
        result.append({
            "clan_tag": tag,
            "clan_name": configured.get("name") or configured["tag"],
            "category": configured.get("category", "normal"),
            "category_label": CLAN_CATEGORY_LABELS.get(
                configured.get("category", "normal"),
                configured.get("category", "normal"),
            ),
            "config_order": order,
            "member_count": member_count,
            "capacity": 50,
            "leader_name": " / ".join(leaders) if leaders else None,
            "average_town_hall": round(town_hall_total / town_hall_count, 1) if town_hall_count else 0,
            "average_trophies": round(trophies_total / trophies_count) if trophies_count else 0,
            "total_donations": total_donations,
            "total_donations_received": total_received,
            "average_donations": round(total_donations / member_count, 1) if member_count else 0,
            "town_hall_distribution": [
                {"level": level, "count": town_halls[level]}
                for level in sorted(town_halls, reverse=True)
            ],
            "role_distribution": {
                role: roles[role]
                for role in ("leader", "coLeader", "admin", "member")
                if roles[role]
            },
            "updated_at": max(synced_at) if synced_at else None,
        })
    return result


@router.get("/clan/overview")
def clan_overview(db: Database = Depends(get_db)):
    """返回全部已启用自有部落的轻量概览卡片。"""
    details = _clan_overview_items(db)
    summary_fields = (
        "clan_tag", "clan_name", "category", "category_label", "config_order",
        "member_count", "capacity", "leader_name", "average_town_hall", "average_trophies",
        "total_donations", "updated_at",
    )
    clans = [{key: item[key] for key in summary_fields} for item in details]
    updated = [item["updated_at"] for item in clans if item["updated_at"]]
    return {
        "updated_at": max(updated) if updated else None,
        "clans": clans,
    }


@router.get("/clan/overview/{clan_tag}")
def clan_overview_detail(clan_tag: str, db: Database = Depends(get_db)):
    """返回单个已启用自有部落的聚合详情。"""
    normalized = normalize_tag(clan_tag)
    item = next(
        (item for item in _clan_overview_items(db) if item["clan_tag"] == normalized),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="部落不在允许查询的自有部落列表中")
    profile_row = db.conn.execute(
        """SELECT status, data_json, updated_at
           FROM clan_profile_cache WHERE clan_tag = ?""",
        (normalized,),
    ).fetchone()
    profile = None
    if profile_row and profile_row["data_json"]:
        try:
            loaded = json.loads(profile_row["data_json"])
            profile = loaded if isinstance(loaded, dict) else None
        except (TypeError, json.JSONDecodeError):
            profile = None
    item["profile"] = profile
    item["profile_status"] = profile_row["status"] if profile_row else "pending"
    item["profile_updated_at"] = profile_row["updated_at"] if profile_row else None
    return item


def _pending_current_war(clan: dict) -> dict:
    return {
        "clan_tag": normalize_tag(clan["tag"]),
        "clan_name": clan.get("name") or clan["tag"],
        "category": clan.get("category", "normal"),
        "status": "sync_pending",
        "state": "syncPending",
        "war_type": None,
        "team_size": 0,
        "attacks_per_member": 0,
        "preparation_start_time": None,
        "start_time": None,
        "end_time": None,
        "result": "pending",
        "clan": None,
        "opponent": None,
        "rows": [],
        "error": None,
        "synced_at": None,
    }


def _cached_current_wars(db: Database) -> dict[str, dict]:
    rows = db.conn.execute(
        "SELECT clan_tag, data_json FROM current_war_cache"
    ).fetchall()
    result = {}
    for row in rows:
        try:
            result[normalize_tag(row["clan_tag"])] = json.loads(row["data_json"])
        except (TypeError, json.JSONDecodeError):
            continue
    return result


@router.get("/clan/current-wars")
def current_wars(db: Database = Depends(get_db)):
    """返回全部已启用自有部落的当前战争摘要。"""
    cached = _cached_current_wars(db)
    clans = []
    categories = []
    seen_categories = set()
    updated = []
    for order, configured in enumerate(_enabled_clans()):
        tag = normalize_tag(configured["tag"])
        item = cached.get(tag) or _pending_current_war(configured)
        item.update({
            "clan_tag": tag,
            "clan_name": configured.get("name") or configured["tag"],
            "category": configured.get("category", "normal"),
            "config_order": order,
        })
        clans.append(current_war_summary(item))
        if item.get("synced_at"):
            updated.append(item["synced_at"])
        category = configured.get("category", "normal")
        if category not in seen_categories:
            seen_categories.add(category)
            categories.append({
                "key": category,
                "label": CLAN_CATEGORY_LABELS.get(category, category),
            })
    return {
        "updated_at": max(updated) if updated else None,
        "categories": categories,
        "clans": clans,
    }


@router.get("/clan/current-wars/{clan_tag}")
def current_war_detail(clan_tag: str, db: Database = Depends(get_db)):
    """返回单个配置部落的当前战争详情。"""
    normalized = normalize_tag(clan_tag)
    configured = next(
        (clan for clan in _enabled_clans() if normalize_tag(clan["tag"]) == normalized),
        None,
    )
    if configured is None:
        raise HTTPException(status_code=404, detail="部落不在允许查询的自有部落列表中")
    item = _cached_current_wars(db).get(normalized) or _pending_current_war(configured)
    item.update({
        "clan_tag": normalized,
        "clan_name": configured.get("name") or configured["tag"],
        "category": configured.get("category", "normal"),
    })
    return item


@router.get("/clan/war-history")
def war_history(clan_tag: Optional[str] = None, db: Database = Depends(get_db)):
    """返回每个自有部落最近 15 场已结束普通部落战的轻量摘要。"""
    configured_by_tag = {
        normalize_tag(clan["tag"]): clan for clan in _enabled_clans()
    }
    selected = normalize_tag(clan_tag) if clan_tag else None
    if selected and selected not in configured_by_tag:
        raise HTTPException(status_code=404, detail="部落不在允许查询的自有部落列表中")

    rows = db.conn.execute(
        """SELECT clan_tag, war_key, data_json, updated_at
           FROM war_history_cache
           WHERE status = 'war_ended'
           ORDER BY end_time DESC, war_key DESC"""
    ).fetchall()
    counts: dict[str, int] = defaultdict(int)
    wars = []
    updated = []
    for row in rows:
        tag = normalize_tag(row["clan_tag"])
        if tag not in configured_by_tag or (selected and tag != selected) or counts[tag] >= 15:
            continue
        item = _load_json(row["data_json"])
        if not item:
            continue
        configured = configured_by_tag[tag]
        item.update({
            "clan_tag": tag,
            "clan_name": configured.get("name") or tag,
            "category": configured.get("category", "normal"),
        })
        wars.append(war_history_summary(item, row["war_key"]))
        counts[tag] += 1
        if row["updated_at"]:
            updated.append(row["updated_at"])

    categories = []
    seen_categories = set()
    clans = []
    for configured in _enabled_clans():
        tag = normalize_tag(configured["tag"])
        category = configured.get("category", "normal")
        clans.append({
            "clan_tag": tag,
            "clan_name": configured.get("name") or tag,
            "category": category,
        })
        if category not in seen_categories:
            seen_categories.add(category)
            categories.append({
                "key": category,
                "label": CLAN_CATEGORY_LABELS.get(category, category),
            })
    return {
        "limit_per_clan": 15,
        "updated_at": max(updated) if updated else None,
        "categories": categories,
        "clans": clans,
        "wars": wars,
    }


@router.get("/clan/war-history/{clan_tag}/{war_key}")
def war_history_detail(clan_tag: str, war_key: str, db: Database = Depends(get_db)):
    """返回一场已归档普通部落战的完整详情。"""
    normalized = normalize_tag(clan_tag)
    configured = next(
        (clan for clan in _enabled_clans() if normalize_tag(clan["tag"]) == normalized),
        None,
    )
    if configured is None:
        raise HTTPException(status_code=404, detail="部落不在允许查询的自有部落列表中")
    row = db.conn.execute(
        """SELECT data_json FROM war_history_cache
           WHERE clan_tag = ? AND war_key = ? AND status = 'war_ended'""",
        (normalized, war_key),
    ).fetchone()
    item = _load_json(row["data_json"]) if row else None
    if not item:
        raise HTTPException(status_code=404, detail="历史部落战不存在")
    item.update({
        "war_key": war_key,
        "clan_tag": normalized,
        "clan_name": configured.get("name") or normalized,
        "category": configured.get("category", "normal"),
        "is_history": True,
    })
    return item


# ── CWL 联赛实时看板 ──────────────────────────────────────────


def _current_cwl_live_period() -> str:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def _valid_period(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m") == value
    except (TypeError, ValueError):
        return False


def _cwl_live_teams(db: Database, period: str) -> list[dict]:
    rows = db.conn.execute(
        """SELECT period, team_index, team_alias, team_name, clan_tag,
                  category, member_count, league_level
           FROM league_teams
           WHERE period = ? AND category IN ('combat', 'shell')
           ORDER BY team_index""",
        (period,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["clan_tag"] = normalize_tag(item.get("clan_tag"))
        result.append(item)
    return result


def _load_json(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def _cwl_live_group_row(db: Database, period: str, clan_tag: str) -> dict | None:
    row = db.conn.execute(
        "SELECT * FROM cwl_live_group_cache WHERE period = ? AND clan_tag = ?",
        (period, clan_tag),
    ).fetchone()
    return dict(row) if row else None


def _cwl_live_wars(db: Database, group: dict) -> dict[str, dict]:
    war_tags = group_war_tags(group)
    if not war_tags:
        return {}
    placeholders = ",".join("?" for _ in war_tags)
    rows = db.conn.execute(
        f"SELECT war_tag, data_json FROM cwl_live_war_cache WHERE war_tag IN ({placeholders})",
        war_tags,
    ).fetchall()
    result = {}
    for row in rows:
        data = _load_json(row["data_json"])
        if data:
            result[normalize_tag(row["war_tag"])] = data
    return result


def _pending_cwl_summary(team: dict, cache: dict | None = None) -> dict:
    return {
        "period": team.get("period"),
        "team_index": team.get("team_index"),
        "team_alias": team.get("team_alias"),
        "team_name": team.get("team_name") or team.get("team_alias") or team.get("clan_tag"),
        "clan_tag": team.get("clan_tag"),
        "category": team.get("category"),
        "member_count": team.get("member_count", 0),
        "league_level": team.get("league_level") or "-",
        "season": (cache or {}).get("season"),
        "status": (cache or {}).get("status") or "waiting",
        "current_round": None,
        "rank": None,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "attack_stars": 0,
        "league_stars": 0,
        "average_destruction": 0.0,
        "synced_at": (cache or {}).get("updated_at"),
        "error": (cache or {}).get("error"),
    }


def _cwl_live_available_periods(db: Database) -> list[dict]:
    """返回当前月份，以及逐场详情完整的历史月份。"""
    current = _current_cwl_live_period()
    periods = [
        row["period"] for row in db.conn.execute(
            """SELECT DISTINCT period FROM league_teams
               WHERE category IN ('combat', 'shell')
               ORDER BY period DESC"""
        ).fetchall()
    ]
    if current not in periods:
        periods.insert(0, current)

    result = []
    for period in periods:
        teams = _cwl_live_teams(db, period)
        if period == current:
            result.append({"period": period, "label": f"{period[:4]}年{int(period[5:])}月", "current": True})
            continue
        if not teams:
            continue
        group_rows = db.conn.execute(
            "SELECT clan_tag, data_json FROM cwl_live_group_cache WHERE period = ?",
            (period,),
        ).fetchall()
        groups = {
            normalize_tag(row["clan_tag"]): _load_json(row["data_json"])
            for row in group_rows
        }
        war_rows = db.conn.execute(
            "SELECT war_tag, data_json FROM cwl_live_war_cache WHERE season = ?",
            (period,),
        ).fetchall()
        wars = {
            normalize_tag(row["war_tag"]): _load_json(row["data_json"])
            for row in war_rows
        }
        complete = True
        for team in teams:
            group = groups.get(team.get("clan_tag"))
            if not group or group.get("season") != period:
                complete = False
                break
            war_tags = group_war_tags(group)
            if not war_tags or any(
                tag not in wars or not wars[tag] or wars[tag].get("status") != "war_ended"
                for tag in war_tags
            ):
                complete = False
                break
        if complete:
            result.append({"period": period, "label": f"{period[:4]}年{int(period[5:])}月", "current": False})
    return result


def _build_cwl_live_summary(db: Database, period: str) -> dict:
    teams = _cwl_live_teams(db, period)
    clans = []
    updated = []
    for team in teams:
        if not team.get("clan_tag"):
            clans.append({**_pending_cwl_summary(team), "status": "error", "error": "联赛队伍缺少部落标签"})
            continue
        cache = _cwl_live_group_row(db, period, team["clan_tag"])
        group = _load_json((cache or {}).get("data_json"))
        if not group or group.get("season") != period:
            item = _pending_cwl_summary(team, cache)
        else:
            dashboard = build_cwl_dashboard(group, _cwl_live_wars(db, group))
            item = {**dashboard["summary"], "error": (cache or {}).get("error")}
        if item.get("synced_at"):
            updated.append(item["synced_at"])
        clans.append(item)
    return {
        "period": period,
        "updated_at": max(updated) if updated else None,
        "categories": [
            {"key": "combat", "label": "实战队"},
            {"key": "shell", "label": "壳子队"},
        ],
        "available_periods": _cwl_live_available_periods(db),
        "clans": clans,
    }


@router.get("/clan/cwl-live")
def cwl_live(period: Optional[str] = None, db: Database = Depends(get_db)):
    """返回当月联赛参赛部落卡片；只读本地缓存。"""
    selected_period = period or _current_cwl_live_period()
    if not _valid_period(selected_period):
        raise HTTPException(status_code=400, detail="period 必须为 YYYY-MM")
    return _build_cwl_live_summary(db, selected_period)


@router.get("/clan/cwl-live/{clan_tag}")
def cwl_live_detail(
    clan_tag: str,
    period: Optional[str] = None,
    round: Optional[int] = None,
    db: Database = Depends(get_db),
):
    """返回当月单个自有联赛部落的战斗日和联赛总览。"""
    selected_period = period or _current_cwl_live_period()
    if not _valid_period(selected_period):
        raise HTTPException(status_code=400, detail="period 必须为 YYYY-MM")
    normalized = normalize_tag(clan_tag)
    teams = _cwl_live_teams(db, selected_period)
    team = next((item for item in teams if item.get("clan_tag") == normalized), None)
    if team is None:
        raise HTTPException(status_code=404, detail="部落不在当月联赛队伍列表中")

    cache = _cwl_live_group_row(db, selected_period, normalized)
    group = _load_json((cache or {}).get("data_json"))
    if group and group.get("season") == selected_period:
        result = build_cwl_dashboard(group, _cwl_live_wars(db, group))
        result["error"] = (cache or {}).get("error")
    else:
        summary = _pending_cwl_summary(team, cache)
        result = {
            "period": selected_period,
            "team": {
                "team_index": team.get("team_index"),
                "team_alias": team.get("team_alias"),
                "team_name": team.get("team_name") or team.get("team_alias"),
                "clan_tag": normalized,
                "category": team.get("category"),
                "member_count": team.get("member_count"),
                "league_level": team.get("league_level"),
            },
            "season": None,
            "group_state": None,
            "status": summary["status"],
            "current_round": None,
            "summary": summary,
            "rounds": [],
            "overview": {
                "town_halls": {"levels": [], "rows": []},
                "standings": {"round_count": 0, "rows": []},
                "offense": {"round_count": 0, "rows": []},
                "defense": {"round_count": 0, "rows": []},
            },
            "updated_at": summary.get("synced_at"),
            "error": summary.get("error"),
        }

    summary_response = _build_cwl_live_summary(db, selected_period)
    result["available_teams"] = [
        {
            "team_index": item.get("team_index"),
            "team_alias": item.get("team_alias"),
            "team_name": item.get("team_name"),
            "clan_tag": item.get("clan_tag"),
            "display_name": item.get("team_name") or item.get("team_alias") or item.get("clan_tag"),
        }
        for item in summary_response["clans"]
        if item.get("clan_tag")
    ]
    if round is not None:
        result["requested_round"] = max(1, min(round, len(result["rounds"]) or 1))
    return result


# ── 联赛战绩统计 ──────────────────────────────────────────────


def _get_current_period() -> str:
    """获取当前 CWL 月份（YYYY-MM 格式）。

    规则：以每月 10 号为分界线。
    - 10 号之前 → 上个月（CWL 刚结束或进行中）
    - 10 号及之后 → 当月（CWL 已开始）
    """
    now = datetime.now()
    if now.day < 10:
        # 10 号之前，CWL 通常刚结束，基准月份为上个月
        month = now.month - 1
        year = now.year
        if month == 0:
            month = 12
            year -= 1
    else:
        month = now.month
        year = now.year
    return f"{year}-{month:02d}"


def _get_window_months(period: str, window_size: int) -> list[str]:
    """根据基准月份和窗口大小，返回前 N 个完整月份列表。

    例如 period="2026-08", window_size=3 → ["2026-06", "2026-07", "2026-08"]
    注意：不包含基准月份之后的数据。
    """
    year, month = map(int, period.split("-"))
    months = []
    for i in range(window_size):
        m = month - (window_size - 1 - i)
        y = year
        if m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    return months


def _calc_rate(numerator: int, denominator: int) -> Optional[float]:
    """计算三星率，除数为 0 返回 None。"""
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _max_fetched_at(conn, table: str, column: str, values: list) -> Optional[str]:
    """查询指定表最近一次数据同步时间（fetched_at 最大值）。

    用于前端展示「数据更新于」信息。
    fetched_at 可能包含非时间戳标记（如 "local_json"），需过滤掉。
    """
    placeholders = ",".join("?" for _ in values)
    row = conn.execute(
        f"""SELECT fetched_at FROM {table}
            WHERE {column} IN ({placeholders})
              AND fetched_at IS NOT NULL
              AND fetched_at GLOB '[0-9][0-9][0-9][0-9]-*'
            ORDER BY fetched_at DESC LIMIT 1""",
        values,
    ).fetchone()
    return row["fetched_at"] if row else None


@router.get("/clan/league-stats")
def league_stats(
    period: Optional[str] = None,
    db: Database = Depends(get_db),
):
    """获取联赛战绩统计（滚动窗口三星率）。

    查询参数：
        period: 基准月份（YYYY-MM），不传则自动取当前 CWL 月份

    返回每个战营成员的 6 列滚动三星率：
        offense_1m, offense_3m, offense_6m,
        defense_1m, defense_3m, defense_6m
    """
    conn = db.conn

    # 确定基准月份
    if period is None:
        period = _get_current_period()

    # 生成三个窗口的月份列表
    months_1m = _get_window_months(period, 1)
    months_3m = _get_window_months(period, 3)
    months_6m = _get_window_months(period, 6)
    all_months = list(set(months_1m + months_3m + months_6m))

    if not all_months:
        return {"stats": [], "period": period}

    # ── 1. 查询当月战营成员 ──
    member_rows = conn.execute(
        """SELECT a.player_tag, a.account_name, a.town_hall_level
           FROM registrations r
           JOIN accounts a ON a.account_name = r.account_name
           WHERE r.period = ?
             AND r.account_type = ?
           ORDER BY a.account_name""",
        (period, LEAGUE_COMBAT),
    ).fetchall()

    if not member_rows:
        return {"stats": [], "period": period}

    # ── 2. LEFT JOIN 查询 league_results 表中所有相关月份的数据 ──
    placeholders = ",".join("?" for _ in all_months)
    lr_rows = conn.execute(
        f"""SELECT lr.player_tag, lr.period, lr.attacks, lr.offense_3stars,
                   lr.defense_3stars, lr.defense_total
            FROM league_results lr
            WHERE lr.period IN ({placeholders})
              AND lr.player_tag IN (
                  SELECT a.player_tag
                  FROM registrations r
                  JOIN accounts a ON a.account_name = r.account_name
                  WHERE r.period = ? AND r.account_type = ?
              )""",
        (*all_months, period, LEAGUE_COMBAT),
    ).fetchall()

    # ── 3. 按 player_tag 分组聚合 ──
    # 每个窗口累计值
    windows = {
        "1m": set(months_1m),
        "3m": set(months_3m),
        "6m": set(months_6m),
    }

    # player_tag → {window_key: {offense_3stars, attacks, defense_3stars, defense_total}}
    stats_map: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {wk: {"offense_3stars": 0, "attacks": 0, "defense_3stars": 0, "defense_total": 0}
                 for wk in windows},
    )

    for row in lr_rows:
        tag = row["player_tag"]
        p = row["period"]
        for wk_key, wk_months in windows.items():
            if p in wk_months:
                stats_map[tag][wk_key]["offense_3stars"] += row["offense_3stars"] or 0
                stats_map[tag][wk_key]["attacks"] += row["attacks"] or 0
                stats_map[tag][wk_key]["defense_3stars"] += row["defense_3stars"] or 0
                stats_map[tag][wk_key]["defense_total"] += row["defense_total"] or 0

    # ── 4. 组装返回结果 ──
    result = []
    for member in member_rows:
        tag = member["player_tag"]
        st = stats_map.get(tag, {})

        item = {
            "player_tag": tag,
            "account_name": member["account_name"],
            "town_hall_level": member["town_hall_level"],
            "offense_1m": _calc_rate(
                st.get("1m", {}).get("offense_3stars", 0),
                st.get("1m", {}).get("attacks", 0),
            ),
            "offense_3m": _calc_rate(
                st.get("3m", {}).get("offense_3stars", 0),
                st.get("3m", {}).get("attacks", 0),
            ),
            "offense_6m": _calc_rate(
                st.get("6m", {}).get("offense_3stars", 0),
                st.get("6m", {}).get("attacks", 0),
            ),
            "defense_1m": _calc_rate(
                st.get("1m", {}).get("defense_3stars", 0),
                st.get("1m", {}).get("defense_total", 0),
            ),
            "defense_3m": _calc_rate(
                st.get("3m", {}).get("defense_3stars", 0),
                st.get("3m", {}).get("defense_total", 0),
            ),
            "defense_6m": _calc_rate(
                st.get("6m", {}).get("defense_3stars", 0),
                st.get("6m", {}).get("defense_total", 0),
            ),
        }
        result.append(item)

    # 数据更新时间：取相关月份 league_results 最近一次同步时间
    updated_at = _max_fetched_at(conn, "league_results", "period", all_months)

    return {
        "period": period,
        "stats": result,
        "updated_at": updated_at,
    }


# ── 部落战战绩统计 ──────────────────────────────────────────────


@router.get("/clan/war-stats")
def war_stats(
    db: Database = Depends(get_db),
):
    """获取部落战战绩统计（按场次滚动窗口三星率）。

    返回每个战营成员的 6 列滚动三星率：
        offense_5, offense_15, offense_45,
        defense_5, defense_15, defense_45

    窗口定义：按 end_time 倒序取每个玩家各自最近 N 场的数据。
    """
    conn = db.conn

    # 确定基准月份（用于筛选战营成员）
    period = _get_current_period()

    # ── 1. 查询当月战营成员 ──
    member_rows = conn.execute(
        """SELECT a.player_tag, a.account_name, a.town_hall_level
           FROM registrations r
           JOIN accounts a ON a.account_name = r.account_name
           WHERE r.period = ?
             AND r.account_type = ?
           ORDER BY a.account_name""",
        (period, LEAGUE_COMBAT),
    ).fetchall()

    if not member_rows:
        return {"stats": [], "period": period}

    member_tags = {r["player_tag"] for r in member_rows}

    # ── 2. 查询 war_results 表，按 end_time 倒序 ──
    wr_rows = conn.execute(
        """SELECT wr.player_tag, wr.end_time, wr.attacks, wr.offense_3stars,
                  wr.defense_3stars, wr.defense_total
           FROM war_results wr
           WHERE wr.clan_tag = '#2QQ'
             AND wr.player_tag IN (
                 SELECT a.player_tag
                 FROM registrations r
                 JOIN accounts a ON a.account_name = r.account_name
                 WHERE r.period = ? AND r.account_type = ?
             )
           ORDER BY wr.end_time DESC""",
        (period, LEAGUE_COMBAT),
    ).fetchall()

    # ── 3. 按 player_tag 分组，截取最近 N 场 ──
    # player_tag → [{end_time, attacks, offense_3stars, defense_3stars, defense_total}, ...]
    # 已按 end_time DESC 排序，直接按顺序分组即可
    player_wars: dict[str, list[dict]] = defaultdict(list)
    for row in wr_rows:
        player_wars[row["player_tag"]].append({
            "attacks": row["attacks"] or 0,
            "offense_3stars": row["offense_3stars"] or 0,
            "defense_3stars": row["defense_3stars"] or 0,
            "defense_total": row["defense_total"] or 0,
        })

    windows = {"5": 5, "15": 15, "45": 45}

    def _aggregate_window(war_list: list[dict], n: int) -> dict[str, int]:
        """取 war_list 前 n 场，累计战绩数据。"""
        subset = war_list[:n]
        return {
            "offense_3stars": sum(w["offense_3stars"] for w in subset),
            "attacks": sum(w["attacks"] for w in subset),
            "defense_3stars": sum(w["defense_3stars"] for w in subset),
            "defense_total": sum(w["defense_total"] for w in subset),
        }

    # ── 4. 组装返回结果 ──
    result = []
    for member in member_rows:
        tag = member["player_tag"]
        wars = player_wars.get(tag, [])

        item = {
            "player_tag": tag,
            "account_name": member["account_name"],
            "town_hall_level": member["town_hall_level"],
        }

        for wk_key, wk_n in windows.items():
            agg = _aggregate_window(wars, wk_n)
            item[f"offense_{wk_key}"] = _calc_rate(agg["offense_3stars"], agg["attacks"])
            item[f"defense_{wk_key}"] = _calc_rate(agg["defense_3stars"], agg["defense_total"])

        result.append(item)

    # 数据更新时间：取战营 war_results 最近一次同步时间
    updated_at = _max_fetched_at(conn, "war_results", "clan_tag", ["#2QQ"])

    return {
        "period": period,
        "stats": result,
        "updated_at": updated_at,
    }


# ── 互刷部落配置 ──────────────────────────────────────────────


@router.get("/clan/farm-config")
def farm_config(db: Database = Depends(get_db)):
    """获取所有互刷部落的实时配置和去速本配置。

    从 farm_stats 缓存表读取（由定时脚本 sync_farm_stats.py 刷新），毫秒级响应。
    返回每个 farm 类别部落的：
    - 部落实时配置（从部落成员统计各 TH 分布）
    - 部落去速本后实时配置（从部落战数据用阶段归类法统计）
    - updated_at 数据更新时间
    """
    conn = db.conn
    rows = conn.execute(
        "SELECT clan_tag, clan_name, category, member_count, stats_json, updated_at "
        "FROM farm_stats"
    ).fetchall()

    if not rows:
        return {"clans": [], "updated_at": None}

    # 按配置中的互刷部落顺序排列（一营 → 八营）
    tag_order = {c["tag"]: i for i, c in enumerate(get_farm_clans())}
    rows = sorted(rows, key=lambda r: tag_order.get(r["clan_tag"], 999))

    import json
    clans = []
    for row in rows:
        try:
            stats = json.loads(row["stats_json"])
        except (json.JSONDecodeError, TypeError):
            stats = {}
        clans.append(stats)

    return {
        "clans": clans,
        "updated_at": rows[0]["updated_at"] if rows else None,
    }


# ── 微信小程序接口 ──────────────────────────────────────────────


def _get_wechat_config() -> tuple[str, str]:
    """获取微信 AppID 和 AppSecret（由 app.py 中的 load_env() 预先加载）。"""
    return os.environ.get("WECHAT_APPID", ""), os.environ.get("WECHAT_SECRET", "")


def _wechat_code2openid(code: str) -> str:
    """用微信 code 换取 openid。"""
    appid, secret = _get_wechat_config()
    if not appid or not secret:
        raise HTTPException(status_code=500, detail="服务端未配置微信 AppID/AppSecret")
    url = "https://api.weixin.qq.com/sns/jscode2session"
    resp = requests.get(url, params={
        "appid": appid,
        "secret": secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }, timeout=10)
    data = resp.json()
    if "errcode" in data and data["errcode"] != 0:
        raise HTTPException(status_code=400, detail=f"微信登录失败: {data.get('errmsg', '未知错误')}")
    return data["openid"]


@router.post("/wechat/login")
def wechat_login(payload: dict, db: Database = Depends(get_db)):
    """微信登录。

    入参：{ "code": "微信 wx.login() 返回的 code" }
    出参：{ "token": "xxx", "user": { "openid", "nickname", "role", "account_name", "player_tag" } }

    首次登录自动创建用户记录（role=member, 未绑定）。
    """
    code = payload.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code 参数")

    openid = _wechat_code2openid(code)
    conn = db.conn

    # 查已有用户
    row = conn.execute("SELECT * FROM wechat_users WHERE openid = ?", (openid,)).fetchone()

    if row:
        token = create_token(openid, row["role"])
        return {
            "token": token,
            "user": {
                "openid": row["openid"],
                "nickname": row["nickname"],
                "role": row["role"],
                "account_name": row["account_name"],
                "player_tag": row["player_tag"],
            },
        }

    # 新用户：插入记录
    from shared.db.connection import now_iso
    now = now_iso()
    conn.execute(
        "INSERT INTO wechat_users (openid, role, created_at, updated_at) VALUES (?, 'member', ?, ?)",
        (openid, now, now),
    )
    conn.commit()

    token = create_token(openid, "member")
    return {
        "token": token,
        "user": {
            "openid": openid,
            "nickname": None,
            "role": "member",
            "account_name": None,
            "player_tag": None,
        },
    }


@router.get("/wechat/me")
def wechat_me(user: dict = Depends(require_user), db: Database = Depends(get_db)):
    """获取当前用户信息。

    需要登录（Authorization: Bearer <token>）。
    """
    openid = user["openid"]
    conn = db.conn
    row = conn.execute("SELECT * FROM wechat_users WHERE openid = ?", (openid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "openid": row["openid"],
        "nickname": row["nickname"],
        "avatar_url": row["avatar_url"],
        "role": row["role"],
        "account_name": row["account_name"],
        "player_tag": row["player_tag"],
        "created_at": row["created_at"],
    }


@router.post("/wechat/bind")
def wechat_bind(payload: dict, user: dict = Depends(require_user), db: Database = Depends(get_db)):
    """绑定游戏账号。

    入参（可传一个或两个）：
        { "account_name": "游戏昵称" }  或  { "player_tag": "#XXXX" }
    不做校验，直接写入 wechat_users 表。
    """
    openid = user["openid"]
    account_name = payload.get("account_name")
    player_tag = payload.get("player_tag")

    if not account_name and not player_tag:
        raise HTTPException(status_code=400, detail="至少需要 account_name 或 player_tag")

    conn = db.conn

    # 查用户是否存在
    row = conn.execute("SELECT * FROM wechat_users WHERE openid = ?", (openid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在，请先登录")

    from shared.db.connection import now_iso
    now = now_iso()

    # 构建 UPDATE 语句（只更新传入的字段）
    sets = []
    params = []
    if account_name is not None:
        sets.append("account_name = ?")
        params.append(account_name)
    if player_tag is not None:
        sets.append("player_tag = ?")
        params.append(player_tag)
    sets.append("updated_at = ?")
    params.append(now)
    params.append(openid)

    conn.execute(f"UPDATE wechat_users SET {', '.join(sets)} WHERE openid = ?", params)
    conn.commit()

    # 返回更新后的用户信息
    row = conn.execute("SELECT * FROM wechat_users WHERE openid = ?", (openid,)).fetchone()
    return {
        "success": True,
        "user": {
            "openid": row["openid"],
            "nickname": row["nickname"],
            "role": row["role"],
            "account_name": row["account_name"],
            "player_tag": row["player_tag"],
        },
    }
