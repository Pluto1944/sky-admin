"""带联盟上下文的 M2 API。

这些接口只读现有本地缓存，不触发外部 COC 请求。旧 ``/api/clan/*`` 与
``/api/members`` 在迁移期继续可用；新接口的联盟范围和管理字段全部由后端组装。
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from modules.alliance.access import (
    AllianceContext,
    ensure_sky_admin_membership,
    list_alliance_contexts,
    resolve_alliance_context,
)
from modules.coc_sync.current_war import current_war_summary
from modules.coc_sync.official.mapper import normalize_tag
from modules.player.member_stats import member_summary_map
from shared.db.connection import Database

from . import routes as legacy_routes
from .auth import require_user
from .deps import get_db


router = APIRouter(prefix="/api")


def _context(user: dict, alliance_id: int, db: Database) -> AllianceContext:
    context = resolve_alliance_context(db.conn, user["openid"], alliance_id)
    if context is None:
        # 统一返回 404，避免枚举其他联盟是否存在。
        raise HTTPException(status_code=404, detail="联盟不存在或当前用户无权访问")
    return context


def _subscribed_clan(context: AllianceContext, clan_tag: str):
    clan = context.clan(clan_tag)
    if clan is None:
        raise HTTPException(status_code=404, detail="部落不在当前联盟订阅范围内")
    return clan


def _management_required(context: AllianceContext, clan_tag: str) -> None:
    clan = _subscribed_clan(context, clan_tag)
    if not clan.management_allowed:
        raise HTTPException(status_code=403, detail="该部落未认证或当前用户没有管理权限")


def _safe_raw(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _alliance_clan_overviews(db: Database, context: AllianceContext) -> list[dict]:
    tags = list(context.clan_tags)
    grouped: dict[str, list] = defaultdict(list)
    if tags:
        placeholders = ",".join("?" for _ in tags)
        rows = db.conn.execute(
            f"""SELECT account_name, town_hall_level, trophies, clan_tag,
                       clan_role, coc_raw, last_synced_at
                FROM accounts
                WHERE membership_status = 'member' AND clan_tag IN ({placeholders})""",
            tags,
        ).fetchall()
        for row in rows:
            grouped[normalize_tag(row["clan_tag"])].append(row)

    result = []
    for clan in context.clans:
        members = grouped.get(clan.clan_tag, [])
        th_total = 0
        th_count = 0
        trophy_total = 0
        trophy_count = 0
        donations = 0
        leaders = []
        updated = []
        for member in members:
            town_hall = _number(member["town_hall_level"])
            trophies = _number(member["trophies"])
            if town_hall:
                th_total += town_hall
                th_count += 1
            if trophies:
                trophy_total += trophies
                trophy_count += 1
            donations += _number(_safe_raw(member["coc_raw"]).get("donations"))
            if member["clan_role"] == "leader" and member["account_name"]:
                leaders.append(member["account_name"])
            if member["last_synced_at"]:
                updated.append(member["last_synced_at"])
        result.append({
            **clan.as_dict(),
            "member_count": len(members),
            "capacity": 50,
            "leader_name": " / ".join(leaders) if leaders else None,
            "average_town_hall": round(th_total / th_count, 1) if th_count else 0,
            "average_trophies": round(trophy_total / trophy_count) if trophy_count else 0,
            "total_donations": donations,
            "updated_at": max(updated) if updated else None,
        })
    return result


@router.get("/me/alliances")
def my_alliances(user: dict = Depends(require_user), db: Database = Depends(get_db)):
    """列出当前用户的有效联盟；访问记录本身不授予联盟成员资格。"""
    ensure_sky_admin_membership(db.conn, user["openid"])
    contexts = list_alliance_contexts(db.conn, user["openid"])
    visit_rows = db.conn.execute(
        """SELECT visits.alliance_id, visits.is_default, visits.last_visited_at
           FROM alliance_visits AS visits
           JOIN wechat_users AS users ON users.id = visits.user_id
           WHERE users.openid = ?""",
        (user["openid"],),
    ).fetchall()
    visits = {int(row["alliance_id"]): row for row in visit_rows}
    items = []
    for context in contexts:
        item = context.as_dict(include_clans=False)
        visit = visits.get(context.alliance_id)
        item["is_default"] = bool(visit and visit["is_default"])
        item["last_visited_at"] = visit["last_visited_at"] if visit else None
        items.append(item)
    return {"count": len(items), "alliances": items}


@router.get("/alliances/{alliance_id}")
def alliance_detail(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    member_count = db.conn.execute(
        """SELECT COUNT(*) FROM alliance_members
           WHERE alliance_id = ? AND status = 'active'""",
        (alliance_id,),
    ).fetchone()[0]
    return {**context.as_dict(), "active_user_count": int(member_count)}


@router.get("/alliances/{alliance_id}/clans")
def alliance_clans(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    clans = _alliance_clan_overviews(db, context)
    return {
        "alliance_id": alliance_id,
        "count": len(clans),
        "clans": clans,
        "updated_at": max(
            (item["updated_at"] for item in clans if item["updated_at"]), default=None
        ),
    }


@router.get("/alliances/{alliance_id}/members")
def alliance_members(
    alliance_id: int,
    page: int = 1,
    page_size: int = 100,
    clan_tag: str = "",
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """返回联盟订阅部落中的游戏成员，按逐部落权限白名单输出字段。"""
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page/page_size 超出允许范围")
    context = _context(user, alliance_id, db)
    selected = normalize_tag(clan_tag) if clan_tag else None
    if selected:
        _subscribed_clan(context, selected)
    selected_tags = [selected] if selected else [clan.clan_tag for clan in context.clans]
    if not selected_tags:
        return {
            "alliance_id": alliance_id, "count": 0, "page": page,
            "page_size": page_size, "total_pages": 1, "members": [],
            "updated_at": None,
        }

    placeholders = ",".join("?" for _ in selected_tags)
    rows = db.conn.execute(
        f"""SELECT player_tag, account_name, town_hall_level, clan_tag, clan_role,
                   trophies, league_name, coc_raw, season_attack_wins,
                   last_activity_at, last_activity_reason, activity_observed_since,
                   player_name, status, history_score, last_synced_at
            FROM accounts
            WHERE membership_status = 'member' AND clan_tag IN ({placeholders})
            ORDER BY clan_tag, town_hall_level DESC, account_name, player_tag""",
        selected_tags,
    ).fetchall()
    summary = member_summary_map(
        db.conn,
        [row["player_tag"] for row in rows],
        clan_tags=selected_tags,
    )
    clan_by_tag = {clan.clan_tag: clan for clan in context.clans}
    items = []
    for row in rows:
        tag = normalize_tag(row["clan_tag"])
        access = clan_by_tag[tag]
        raw = _safe_raw(row["coc_raw"])
        item = {
            "player_tag": row["player_tag"],
            "account_name": row["account_name"],
            "clan_tag": tag,
            "clan_name": access.clan_name,
            "town_hall_level": row["town_hall_level"],
            "clan_role": row["clan_role"],
            "trophies": row["trophies"],
            "league_name": row["league_name"],
            "donations": _number(raw.get("donations")),
            "donations_received": _number(raw.get("donationsReceived")),
            "season_attack_wins": row["season_attack_wins"],
            "last_synced_at": row["last_synced_at"],
            "data_level": access.effective_access,
        }
        if access.management_allowed:
            try:
                reasons = json.loads(row["last_activity_reason"] or "[]")
            except (TypeError, json.JSONDecodeError):
                reasons = []
            stats = summary.get(row["player_tag"], {})
            item["management"] = {
                "player_name": row["player_name"],
                "registration_status": row["status"],
                "history_score": row["history_score"],
                "last_activity_at": row["last_activity_at"],
                "last_activity_reasons": reasons if isinstance(reasons, list) else [],
                "activity_observed_since": row["activity_observed_since"],
                "war_recent_15": stats.get("war_recent_15"),
                "cwl_recent_3m": stats.get("cwl_recent_3m"),
                "capital_recent_4w": stats.get("capital_recent_4w"),
                "clan_games": stats.get("clan_games"),
                "combat_updated_at": stats.get("combat_updated_at"),
            }
        items.append(item)

    count = len(items)
    offset = (page - 1) * page_size
    return {
        "alliance_id": alliance_id,
        "count": count,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (count + page_size - 1) // page_size),
        "members": items[offset:offset + page_size],
        "updated_at": max(
            (item["last_synced_at"] for item in items if item["last_synced_at"]), default=None
        ),
    }


@router.get("/alliances/{alliance_id}/wars/current")
def alliance_current_wars(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    cached = legacy_routes._cached_current_wars(db)
    items = []
    updated = []
    for clan in context.clans:
        configured = {
            "tag": clan.clan_tag, "name": clan.clan_name, "category": clan.category,
        }
        item = cached.get(clan.clan_tag) or legacy_routes._pending_current_war(configured)
        item.update({
            "clan_tag": clan.clan_tag,
            "clan_name": clan.clan_name,
            "category": clan.category,
            "config_order": clan.sort_order,
        })
        items.append(current_war_summary(item))
        if item.get("synced_at"):
            updated.append(item["synced_at"])
    return {"alliance_id": alliance_id, "updated_at": max(updated) if updated else None, "clans": items}


@router.get("/alliances/{alliance_id}/wars/current/{clan_tag}")
def alliance_current_war_detail(
    alliance_id: int,
    clan_tag: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    clan = _subscribed_clan(context, clan_tag)
    configured = {"tag": clan.clan_tag, "name": clan.clan_name, "category": clan.category}
    item = legacy_routes._cached_current_wars(db).get(clan.clan_tag)
    item = item or legacy_routes._pending_current_war(configured)
    item.update({
        "clan_tag": clan.clan_tag, "clan_name": clan.clan_name,
        "category": clan.category,
    })
    return item


def _historical_cwl_allowed(context: AllianceContext, period: str) -> None:
    if period == legacy_routes._current_cwl_live_period():
        return
    if any(not clan.management_allowed for clan in context.clans):
        raise HTTPException(status_code=403, detail="历史联赛数据需要全部相关部落的管理权限")


@router.get("/alliances/{alliance_id}/cwl/live")
def alliance_cwl_live(
    alliance_id: int,
    period: Optional[str] = None,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    selected_period = period or legacy_routes._current_cwl_live_period()
    if not legacy_routes._valid_period(selected_period):
        raise HTTPException(status_code=400, detail="period 必须为 YYYY-MM")
    _historical_cwl_allowed(context, selected_period)
    result = legacy_routes._build_cwl_live_summary(db, selected_period)
    result["alliance_id"] = alliance_id
    result["clans"] = [
        item for item in result["clans"]
        if normalize_tag(item.get("clan_tag")) in context.clan_tags
    ]
    result["updated_at"] = max(
        (item.get("synced_at") for item in result["clans"] if item.get("synced_at")),
        default=None,
    )
    return result


@router.get("/alliances/{alliance_id}/cwl/live/{clan_tag}")
def alliance_cwl_live_detail(
    alliance_id: int,
    clan_tag: str,
    period: Optional[str] = None,
    round: Optional[int] = None,
    view: Optional[str] = None,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    clan = _subscribed_clan(context, clan_tag)
    selected_period = period or legacy_routes._current_cwl_live_period()
    if selected_period != legacy_routes._current_cwl_live_period():
        _management_required(context, clan.clan_tag)
    result = legacy_routes.cwl_live_detail(
        clan.clan_tag, period=period, round=round, db=db, view=view,
    )
    result["alliance_id"] = alliance_id
    result["available_teams"] = [
        item for item in result.get("available_teams", [])
        if normalize_tag(item.get("clan_tag")) in context.clan_tags
    ]
    return result
