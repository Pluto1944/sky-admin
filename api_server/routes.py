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
from modules.coc_sync.cwl_live import build_cwl_attack_reminder, build_cwl_dashboard, group_war_tags
from modules.coc_sync.official.mapper import normalize_tag
from modules.coc_sync.war_history import war_history_summary
from .deps import get_repo, get_db
from .auth import create_token, require_user
from shared.db.connection import Database
from shared.release import read_release_version
from config import CLANS, CLAN_CATEGORY_LABELS, DB_PATH, LEAGUE_COMBAT, get_farm_clans

router = APIRouter(prefix="/api")


@router.get("/ping")
def ping():
    """健康检查接口。返回服务状态、发布版本和时间戳。"""
    from datetime import datetime, timezone

    return {
        "status": "ok",
        "service": "sky-admin-api",
        "version": read_release_version(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/members")
def list_members(
    repo: PlayerRepository = Depends(get_repo),
    db: Database = Depends(get_db),
):
    """获取所有 COC 成员列表。

    从 accounts 表读取，返回每个成员的：
    - player_tag, account_name, exp_level, trophies, league_name
    - town_hall_level, clan_tag, clan_role, status
    - membership_status, last_synced_at, updated_at
    """
    try:
        from modules.player.member_stats import member_summary_map

        raw_members = repo.list_all()
        summaries = member_summary_map(
            db.conn, [member["player_tag"] for member in raw_members]
        )
        configured = {
            normalize_tag(clan["tag"]): clan
            for clan in CLANS
            if clan.get("enabled", True)
        }
        members = []
        for source in raw_members:
            member = dict(source)
            raw = _safe_coc_raw(member.pop("coc_raw", None))
            member["donations"] = _safe_number(raw.get("donations"))
            member["donations_received"] = _safe_number(raw.get("donationsReceived"))
            try:
                reasons = json.loads(member.get("last_activity_reason") or "[]")
            except (TypeError, json.JSONDecodeError):
                reasons = []
            member.pop("last_activity_reason", None)
            member["last_activity_reasons"] = reasons if isinstance(reasons, list) else []
            clan = configured.get(normalize_tag(member.get("clan_tag")))
            member["clan_name"] = clan.get("name") if clan else None
            member["clan_category"] = clan.get("category") if clan else None
            member.update(summaries.get(member["player_tag"], {}))
            members.append(member)
        updated_values = [member.get("last_synced_at") for member in members if member.get("last_synced_at")]
        return {
            "count": len(members),
            "members": members,
            "updated_at": max(updated_values) if updated_values else None,
            "clans": [
                {
                    "tag": normalize_tag(clan["tag"]),
                    "name": clan.get("name") or clan["tag"],
                    "category": clan.get("category", "normal"),
                    "category_label": CLAN_CATEGORY_LABELS.get(
                        clan.get("category", "normal"), clan.get("category", "normal")
                    ),
                }
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
        """SELECT clan_tag, status, data_json, error, updated_at, attempted_at,
                  failure_count
           FROM current_war_cache"""
    ).fetchall()
    result = {}
    for row in rows:
        try:
            item = json.loads(row["data_json"])
            item.update({
                "sync_error": row["error"],
                "sync_attempted_at": row["attempted_at"],
                "sync_failure_count": int(row["failure_count"] or 0),
                "is_stale": bool(row["error"] and row["status"] != "error"),
            })
            result[normalize_tag(row["clan_tag"])] = item
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
                  category, member_count, league_level, leader
           FROM league_teams
           WHERE period = ? AND category IN ('combat', 'shell')
           ORDER BY team_index""",
        (period,),
    ).fetchall()
    management = _cwl_roster_team_metadata(db, period)
    result = []
    for row in rows:
        item = dict(row)
        item["clan_tag"] = normalize_tag(item.get("clan_tag"))
        metadata = management.get(item["clan_tag"], {})
        item["leader_name"] = (
            str(metadata.get("leader_name") or "").strip()
            or str(item.get("leader") or "").strip()
        )
        item["manager_names"] = str(metadata.get("manager_names") or "").strip()
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


def _cwl_roster_team_metadata(db: Database, period: str) -> dict[str, dict]:
    row = db.conn.execute(
        "SELECT data_json FROM cwl_roster_snapshots WHERE period = ? AND is_active = 1",
        (period,),
    ).fetchone()
    roster = _load_json(row["data_json"] if row else None) or {}
    return {
        normalize_tag(team.get("clan_tag")): team
        for team in roster.get("teams", [])
        if normalize_tag(team.get("clan_tag"))
    }


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
        "leader_name": team.get("leader_name") or "",
        "manager_names": team.get("manager_names") or "",
        "season": (cache or {}).get("season"),
        "status": (cache or {}).get("status") or "waiting",
        "current_round": None,
        "current_result": None,
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
            item["leader_name"] = team.get("leader_name") or ""
            item["manager_names"] = team.get("manager_names") or ""
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


@router.get("/clan/cwl-check-in")
def cwl_check_in(db: Database = Depends(get_db)):
    """返回当月各联赛队伍的当前战斗日和未出刀成员。"""
    period = _current_cwl_live_period()
    teams = _cwl_live_teams(db, period)
    items = []
    updated = []
    for team in teams:
        clan_tag = team.get("clan_tag")
        cache = _cwl_live_group_row(db, period, clan_tag) if clan_tag else None
        group = _load_json((cache or {}).get("data_json"))
        if group and group.get("season") == period:
            item = build_cwl_attack_reminder(group, _cwl_live_wars(db, group))
            item["error"] = (cache or {}).get("error")
        else:
            item = {
                "period": period,
                "team_index": team.get("team_index"),
                "team_alias": team.get("team_alias"),
                "team_name": team.get("team_name") or team.get("team_alias") or clan_tag,
                "clan_tag": clan_tag,
                "category": team.get("category"),
                "league_level": team.get("league_level"),
                "status": "error" if not clan_tag or (cache or {}).get("status") == "error" else "waiting",
                "round": None,
                "opponent": None,
                "start_time": None,
                "end_time": None,
                "team_size": 0,
                "attacked_count": 0,
                "pending_count": 0,
                "pending_members": [],
                "updated_at": (cache or {}).get("updated_at"),
                "error": "联赛队伍缺少部落标签" if not clan_tag else (cache or {}).get("error"),
            }
        if item.get("updated_at"):
            updated.append(item["updated_at"])
        items.append(item)

    status_order = {"in_war": 0, "preparation": 1, "waiting": 2, "ended": 3, "error": 4}
    items.sort(key=lambda item: (
        status_order.get(item.get("status"), 9),
        item.get("end_time") or item.get("start_time") or "99999999",
        item.get("team_index") if item.get("team_index") is not None else 999,
    ))
    return {
        "period": period,
        "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_at": max(updated) if updated else None,
        "summary": {
            "team_count": len(items),
            "active_team_count": sum(item["status"] == "in_war" for item in items),
            "preparation_team_count": sum(item["status"] == "preparation" for item in items),
            "pending_attack_count": sum(item["pending_count"] for item in items),
        },
        "teams": items,
    }


def _active_cwl_roster_snapshot(db: Database, period: str) -> dict | None:
    row = db.conn.execute(
        "SELECT * FROM cwl_roster_snapshots WHERE period = ? AND is_active = 1",
        (period,),
    ).fetchone()
    return dict(row) if row else None


def _cwl_assembly_item(team: dict, cache: dict | None) -> dict:
    payload = _load_json((cache or {}).get("data_json")) or {}
    status = (cache or {}).get("status") or "waiting_check"
    return {
        "period": team.get("period"),
        "team_index": team.get("team_index"),
        "team_alias": team.get("team_alias"),
        "team_name": team.get("team_name") or team.get("team_alias") or team.get("clan_tag"),
        "clan_tag": team.get("clan_tag"),
        "category": team.get("category"),
        "status": status,
        "official_count": payload.get("official_count", 0),
        "current_count": payload.get("current_count", 0),
        "present_count": payload.get("present_count", 0),
        "missing_count": payload.get("missing_count", 0),
        "extra_count": payload.get("extra_count", 0),
        "updated_at": (cache or {}).get("updated_at"),
        "attempted_at": (cache or {}).get("attempted_at"),
        "locked_at": (cache or {}).get("locked_at"),
        "error": (cache or {}).get("error"),
    }


@router.get("/clan/cwl-assembly")
def cwl_assembly(db: Database = Depends(get_db)):
    """返回当月联赛集结检查的部落汇总；只读本地缓存。"""
    period = _current_cwl_live_period()
    teams = _cwl_live_teams(db, period)
    snapshot = _active_cwl_roster_snapshot(db, period)
    caches = {
        normalize_tag(row["clan_tag"]): dict(row)
        for row in db.conn.execute(
            "SELECT * FROM cwl_assembly_cache WHERE period = ?",
            (period,),
        ).fetchall()
    }
    items = [_cwl_assembly_item(team, caches.get(team.get("clan_tag"))) for team in teams]
    updated = [item["updated_at"] for item in items if item.get("updated_at")]
    return {
        "period": period,
        "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "ready" if snapshot else "waiting_roster",
        "snapshot": ({
            "revision": snapshot.get("revision"),
            "created_at": snapshot.get("created_at"),
        } if snapshot else None),
        "updated_at": max(updated) if updated else None,
        "summary": {
            "team_count": len(items),
            "checked_team_count": sum(bool(item.get("updated_at")) for item in items),
            "locked_team_count": sum(bool(item.get("locked_at")) for item in items),
            "missing_count": sum(item["missing_count"] for item in items),
            "extra_count": sum(item["extra_count"] for item in items),
        },
        "teams": items,
    }


@router.get("/clan/cwl-assembly/{clan_tag}")
def cwl_assembly_detail(clan_tag: str, db: Database = Depends(get_db)):
    """返回当月单个联赛部落的集结详情。"""
    period = _current_cwl_live_period()
    normalized = normalize_tag(clan_tag)
    team = next(
        (item for item in _cwl_live_teams(db, period) if item.get("clan_tag") == normalized),
        None,
    )
    if team is None:
        raise HTTPException(status_code=404, detail="部落不在当月联赛队伍列表中")
    snapshot = _active_cwl_roster_snapshot(db, period)
    row = db.conn.execute(
        "SELECT * FROM cwl_assembly_cache WHERE period = ? AND clan_tag = ?",
        (period, normalized),
    ).fetchone()
    cache = dict(row) if row else None
    result = _cwl_assembly_item(team, cache)
    payload = _load_json((cache or {}).get("data_json")) or {}
    result.update({
        "snapshot_revision": snapshot.get("revision") if snapshot else None,
        "missing_members": payload.get("missing_members", []),
        "extra_members": payload.get("extra_members", []),
        "present_members": payload.get("present_members", []),
    })
    return result


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
    clan_tag: Optional[str] = None,
    db: Database = Depends(get_db),
):
    """按指定自有部落的固定战争窗口返回当前实际成员攻防三星率。"""
    conn = db.conn
    configured = {normalize_tag(clan["tag"]): clan for clan in _enabled_clans()}
    default_tag = normalize_tag("#2QQ")
    selected = normalize_tag(clan_tag) if clan_tag else (
        default_tag if default_tag in configured else next(iter(configured), None)
    )
    if not selected or selected not in configured:
        raise HTTPException(status_code=404, detail="部落不在允许查询的自有部落列表中")

    member_rows = conn.execute(
        """SELECT player_tag, account_name, town_hall_level
           FROM accounts
           WHERE clan_tag = ? AND COALESCE(membership_status, 'member') != 'left'
           ORDER BY account_name""",
        (selected,),
    ).fetchall()
    history_rows = conn.execute(
        """SELECT war_key, updated_at FROM war_history_cache
           WHERE clan_tag = ? AND status = 'war_ended'
           ORDER BY end_time DESC, war_key DESC LIMIT 45""",
        (selected,),
    ).fetchall()
    windows = {"5": [row["war_key"] for row in history_rows[:5]],
               "15": [row["war_key"] for row in history_rows[:15]],
               "45": [row["war_key"] for row in history_rows]}
    member_tags = [row["player_tag"] for row in member_rows]
    facts_by_player: dict[str, dict[str, dict]] = defaultdict(dict)
    if member_tags and history_rows:
        member_placeholders = ",".join("?" for _ in member_tags)
        key_placeholders = ",".join("?" for _ in history_rows)
        fact_rows = conn.execute(
            f"""SELECT player_tag, war_key, offense_effective_attacks,
                       offense_effective_3stars, defense_effective_attacks,
                       defense_effective_3stars
                FROM member_war_facts
                WHERE clan_tag = ? AND status = 'war_ended'
                  AND player_tag IN ({member_placeholders})
                  AND war_key IN ({key_placeholders})""",
            (selected, *member_tags, *(row["war_key"] for row in history_rows)),
        ).fetchall()
        for row in fact_rows:
            facts_by_player[row["player_tag"]][row["war_key"]] = dict(row)

    def _aggregate(player_tag: str, keys: list[str]) -> dict[str, int]:
        facts = facts_by_player.get(player_tag, {})
        rows = [facts[key] for key in keys if key in facts]
        return {
            "offense_3stars": sum(int(row["offense_effective_3stars"] or 0) for row in rows),
            "attacks": sum(int(row["offense_effective_attacks"] or 0) for row in rows),
            "defense_3stars": sum(int(row["defense_effective_3stars"] or 0) for row in rows),
            "defense_total": sum(int(row["defense_effective_attacks"] or 0) for row in rows),
        }

    result = []
    for member in member_rows:
        tag = member["player_tag"]
        item = {
            "player_tag": tag,
            "account_name": member["account_name"],
            "town_hall_level": member["town_hall_level"],
        }
        for wk_key, keys in windows.items():
            agg = _aggregate(tag, keys)
            item[f"offense_{wk_key}"] = _calc_rate(agg["offense_3stars"], agg["attacks"])
            item[f"defense_{wk_key}"] = _calc_rate(agg["defense_3stars"], agg["defense_total"])
            item[f"offense_{wk_key}_sample"] = {
                "three_stars": agg["offense_3stars"], "attacks": agg["attacks"],
            }
            item[f"defense_{wk_key}_sample"] = {
                "three_stars": agg["defense_3stars"], "attacks": agg["defense_total"],
            }
        result.append(item)
    return {
        "clan_tag": selected,
        "clan_name": configured[selected].get("name") or selected,
        "stats": result,
        "updated_at": max((row["updated_at"] for row in history_rows if row["updated_at"]), default=None),
        "history_coverage": {"available": len(history_rows), "target": 45, "complete": len(history_rows) >= 45},
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
