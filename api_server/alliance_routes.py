"""带联盟上下文的 M2 API。

这些接口只读现有本地缓存，不触发外部 COC 请求。旧 ``/api/clan/*`` 与
``/api/members`` 在迁移期继续可用；新接口的联盟范围和管理字段全部由后端组装。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modules.alliance.access import (
    AllianceContext,
    ensure_sky_admin_membership,
    list_alliance_contexts,
    resolve_alliance_context,
)
from modules.alliance.cwl_config import (
    CwlConfigError,
    add_team,
    confirm_season,
    copy_previous,
    correct_frozen_tag,
    create_season,
    delete_team,
    list_seasons,
    season_payload,
    update_team,
)
from modules.alliance.free_alliance import (
    FREE_CATEGORIES,
    FREE_CATEGORY_LABELS,
    FreeAllianceError,
    archive_free_alliance,
    create_free_alliance,
    enqueue_initialization,
    free_alliance_capability,
    reconcile_sync_targets,
    rename_free_alliance,
    request_manual_refresh,
    subscribe_free_clan,
    subscription_status,
)
from modules.coc_sync.current_war import current_war_summary
from modules.coc_sync.official.mapper import normalize_tag
from modules.player.member_stats import member_summary_map
from shared.db.connection import Database
from config import CLAN_CATEGORY_LABELS

from . import routes as legacy_routes
from .auth import require_user
from .deps import get_db


router = APIRouter(prefix="/api")


class CwlTeamInput(BaseModel):
    clan_tag: str
    clan_name: str | None = None
    team_alias: str | None = None
    category: str = "shell"
    sort_order: int = 0


class CwlTagCorrectionInput(BaseModel):
    clan_tag: str
    reason: str


class FreeAllianceCreateInput(BaseModel):
    name: str | None = None


class FreeAllianceRenameInput(BaseModel):
    name: str


class FreeClanSubscriptionInput(BaseModel):
    clan_tag: str
    category: str
    clan_name: str | None = None


class FreeRefreshInput(BaseModel):
    resource_types: list[str] = Field(default_factory=lambda: ["current_war"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _context(user: dict, alliance_id: int, db: Database) -> AllianceContext:
    context = resolve_alliance_context(db.conn, user["openid"], alliance_id)
    if context is None:
        # 统一返回 404，避免枚举其他联盟是否存在。
        raise HTTPException(status_code=404, detail="联盟不存在或当前用户无权访问")
    return context


def _free_error(exc: FreeAllianceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


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

    war_status, capital_status = legacy_routes._clan_operating_status(db)
    result = []
    for clan in context.clans:
        members = grouped.get(clan.clan_tag, [])
        th_total = 0
        th_count = 0
        trophy_total = 0
        trophy_count = 0
        donations = 0
        donations_received = 0
        leaders = []
        updated = []
        town_halls: dict[int, int] = defaultdict(int)
        roles: dict[str, int] = defaultdict(int)
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
            donations_received += _number(_safe_raw(member["coc_raw"]).get("donationsReceived"))
            if town_hall:
                town_halls[town_hall] += 1
            if member["clan_role"]:
                roles[member["clan_role"]] += 1
            if member["clan_role"] == "leader" and member["account_name"]:
                leaders.append(member["account_name"])
            if member["last_synced_at"]:
                updated.append(member["last_synced_at"])
        result.append({
            **clan.as_dict(),
            "category_label": CLAN_CATEGORY_LABELS.get(clan.category, clan.category),
            "config_order": clan.sort_order,
            "member_count": len(members),
            "capacity": 50,
            "leader_name": " / ".join(leaders) if leaders else None,
            "average_town_hall": round(th_total / th_count, 1) if th_count else 0,
            "average_trophies": round(trophy_total / trophy_count) if trophy_count else 0,
            "total_donations": donations,
            "total_donations_received": donations_received,
            "average_donations": round(donations / len(members), 1) if members else 0,
            "town_hall_distribution": [
                {"level": level, "count": town_halls[level]}
                for level in sorted(town_halls, reverse=True)
            ],
            "role_distribution": {
                role: roles[role]
                for role in ("leader", "coLeader", "admin", "member")
                if roles[role]
            },
            "war_status": war_status.get(clan.clan_tag),
            "capital_status": capital_status.get(clan.clan_tag),
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
    return {
        "count": len(items),
        "alliances": items,
        "features": {
            "free_alliance": free_alliance_capability(db.conn, user["openid"]),
        },
    }


@router.post("/me/alliances", status_code=201)
def create_my_free_alliance(
    payload: FreeAllianceCreateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """Create the current user's one internal-gray free alliance."""
    try:
        alliance_id = create_free_alliance(
            db.conn, user["openid"], name=payload.name,
        )
    except FreeAllianceError as exc:
        raise _free_error(exc) from exc
    context = _context(user, alliance_id, db)
    return {**context.as_dict(), "is_default": True}


@router.patch("/alliances/{alliance_id}")
def rename_my_free_alliance(
    alliance_id: int,
    payload: FreeAllianceRenameInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        rename_free_alliance(
            db.conn, user["openid"], alliance_id, payload.name,
        )
    except FreeAllianceError as exc:
        raise _free_error(exc) from exc
    return _context(user, alliance_id, db).as_dict()


@router.get("/alliances/{alliance_id}/subscription")
def free_subscription(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    if context.plan_code != "free":
        raise HTTPException(status_code=409, detail="该接口仅适用于免费联盟")
    clan = context.clans[0] if context.clans else None
    return {
        "alliance": context.as_dict(include_clans=False),
        "clan": clan.as_dict() if clan else None,
        "categories": [
            {"key": item, "label": FREE_CATEGORY_LABELS[item]}
            for item in FREE_CATEGORIES
        ],
        "sync": subscription_status(db.conn, alliance_id, clan.clan_tag) if clan else [],
    }


@router.put("/alliances/{alliance_id}/subscription")
def save_free_subscription(
    alliance_id: int,
    payload: FreeClanSubscriptionInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        clan = subscribe_free_clan(
            db.conn,
            user["openid"],
            alliance_id,
            clan_tag=payload.clan_tag,
            category=payload.category,
            clan_name=payload.clan_name,
        )
    except FreeAllianceError as exc:
        raise _free_error(exc) from exc
    context = _context(user, alliance_id, db)
    try:
        initialization = enqueue_initialization(
            db.conn,
            alliance_id=alliance_id,
            clan_tag=clan["clan_tag"],
            actor_user_id=context.user_id,
        )
    except Exception:  # noqa: BLE001 - subscription is durable; scheduler will converge
        initialization = [
            {"resource_type": item, "accepted": False, "reason": "planner_pending"}
            for item in ("clan_profile", "clan_members", "current_war")
        ]
    return {
        "alliance": _context(user, alliance_id, db).as_dict(include_clans=False),
        "clan": clan,
        "initialization": initialization,
        "sync": subscription_status(db.conn, alliance_id, clan["clan_tag"]),
    }


@router.post("/alliances/{alliance_id}/subscription/refresh", status_code=202)
def refresh_free_subscription(
    alliance_id: int,
    payload: FreeRefreshInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    if context.plan_code != "free" or not context.clans:
        raise HTTPException(status_code=409, detail="当前免费联盟尚未订阅部落")
    clan = context.clans[0]
    try:
        results = request_manual_refresh(
            db.conn,
            user["openid"],
            alliance_id,
            clan.clan_tag,
            resource_types=payload.resource_types,
        )
    except FreeAllianceError as exc:
        raise _free_error(exc) from exc
    return {
        "alliance_id": alliance_id,
        "clan_tag": clan.clan_tag,
        "results": results,
        "sync": subscription_status(db.conn, alliance_id, clan.clan_tag),
    }


@router.delete("/alliances/{alliance_id}")
def delete_my_free_alliance(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        archive_free_alliance(db.conn, user["openid"], alliance_id)
    except FreeAllianceError as exc:
        raise _free_error(exc) from exc
    # Reconciliation is local-only.  If it races with the scheduler, the next
    # minute's planner will converge to the same target set.
    try:
        reconcile_sync_targets(db.conn)
        sync_reconcile = "complete"
    except Exception:  # noqa: BLE001 - lifecycle mutation already committed
        sync_reconcile = "pending"
    return {"success": True, "alliance_id": alliance_id, "sync_reconcile": sync_reconcile}


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


@router.post("/me/alliances/{alliance_id}/visit")
def visit_alliance(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """记录最近选择的联盟；访问记录不创建成员关系，也不授予权限。"""
    context = _context(user, alliance_id, db)
    now = _utc_now()
    with db.conn:
        db.conn.execute(
            "UPDATE alliance_visits SET is_default = 0 WHERE user_id = ?",
            (context.user_id,),
        )
        db.conn.execute(
            """INSERT INTO alliance_visits
               (alliance_id, user_id, is_default, first_visited_at, last_visited_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(alliance_id, user_id) DO UPDATE SET
                   is_default = 1,
                   last_visited_at = excluded.last_visited_at""",
            (alliance_id, context.user_id, now, now),
        )
    return {**context.as_dict(include_clans=False), "is_default": True, "last_visited_at": now}


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


@router.get("/alliances/{alliance_id}/clans/{clan_tag}")
def alliance_clan_detail(
    alliance_id: int,
    clan_tag: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    clan = _subscribed_clan(context, clan_tag)
    item = next(
        value for value in _alliance_clan_overviews(db, context)
        if value["clan_tag"] == clan.clan_tag
    )
    profile_row = db.conn.execute(
        """SELECT status, data_json, updated_at
           FROM clan_profile_cache WHERE clan_tag = ?""",
        (clan.clan_tag,),
    ).fetchone()
    profile = None
    if profile_row and profile_row["data_json"]:
        loaded = _safe_raw(profile_row["data_json"])
        profile = loaded or None
    item["profile"] = profile
    item["profile_status"] = profile_row["status"] if profile_row else "pending"
    item["profile_updated_at"] = profile_row["updated_at"] if profile_row else None
    return item


@router.get("/alliances/{alliance_id}/farm-config")
def alliance_farm_config(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """返回当前联盟中标记为 ``farm`` 的部落及其本地互刷缓存。"""
    context = _context(user, alliance_id, db)
    configured_clans = [
        {
            "tag": clan.clan_tag,
            "name": clan.clan_name,
            "category": clan.category,
            "enabled": True,
        }
        for clan in context.clans
        if clan.category == "farm"
    ]
    result = legacy_routes._farm_config_for_clans(db, configured_clans)
    result["alliance_id"] = alliance_id
    return result


@router.get("/alliances/{alliance_id}/members")
def alliance_members(
    alliance_id: int,
    page: int = 1,
    page_size: int = 100,
    membership_status: str = "member",
    clan_tag: str = "",
    clan_tags: str = "",
    search: str = "",
    sort_key: str = "town_hall_level",
    sort_order: str = "desc",
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """返回联盟订阅部落中的游戏成员，按逐部落权限白名单输出字段。"""
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page/page_size 超出允许范围")
    if membership_status not in {"all", "member", "left"}:
        raise HTTPException(status_code=422, detail="membership_status 仅支持 all/member/left")
    if sort_key not in legacy_routes._MEMBER_SORT_KEYS:
        raise HTTPException(status_code=422, detail="不支持的成员排序字段")
    if sort_order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="sort_order 仅支持 asc/desc")
    context = _context(user, alliance_id, db)
    requested_tags = [
        normalize_tag(value)
        for value in (clan_tags or clan_tag).split(",")
        if normalize_tag(value)
    ]
    for requested in requested_tags:
        _subscribed_clan(context, requested)
    selected_tags = requested_tags or [clan.clan_tag for clan in context.clans]
    clan_options = [
        {
            "tag": clan.clan_tag,
            "name": clan.clan_name,
            "category": clan.category,
            "category_label": CLAN_CATEGORY_LABELS.get(clan.category, clan.category),
        }
        for clan in context.clans
    ]
    if not selected_tags:
        return {
            "alliance_id": alliance_id, "count": 0, "page": page,
            "page_size": page_size, "total_pages": 1, "members": [],
            "updated_at": None, "clans": clan_options,
        }

    placeholders = ",".join("?" for _ in selected_tags)
    rows = db.conn.execute(
        f"""SELECT player_tag, account_name, town_hall_level, clan_tag, clan_role,
                   trophies, league_name, coc_raw, season_attack_wins,
                   last_activity_at, last_activity_reason, activity_observed_since,
                   player_name, status, history_score, membership_status, last_synced_at
            FROM accounts
            WHERE clan_tag IN ({placeholders})
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
            "membership_status": row["membership_status"],
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
            item.update(item["management"])
        items.append(item)

    keyword = search.strip().casefold()
    filtered = []
    for item in items:
        current_status = item.get("membership_status") or "member"
        if membership_status != "all" and current_status != membership_status:
            continue
        if keyword:
            searchable = (
                item.get("account_name"), item.get("player_name"), item.get("player_tag"),
                item.get("clan_tag"), item.get("clan_name"), item.get("league_name"),
            )
            if not any(keyword in str(value).casefold() for value in searchable if value):
                continue
        filtered.append(item)
    filtered = legacy_routes._sort_member_items(filtered, sort_key, sort_order)
    count = len(filtered)
    offset = (page - 1) * page_size
    return {
        "alliance_id": alliance_id,
        "count": count,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (count + page_size - 1) // page_size),
        "members": filtered[offset:offset + page_size],
        "clans": clan_options,
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
    categories = []
    seen_categories = set()
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
        if clan.category not in seen_categories:
            seen_categories.add(clan.category)
            categories.append({
                "key": clan.category,
                "label": CLAN_CATEGORY_LABELS.get(clan.category, clan.category),
            })
    return {
        "alliance_id": alliance_id,
        "updated_at": max(updated) if updated else None,
        "categories": categories,
        "clans": items,
    }


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


def _configured_context_clans(context: AllianceContext) -> list[dict]:
    return [
        {
            "tag": clan.clan_tag,
            "name": clan.clan_name,
            "category": clan.category,
            "enabled": True,
        }
        for clan in context.clans
    ]


@router.get("/alliances/{alliance_id}/wars/history")
def alliance_war_history(
    alliance_id: int,
    clan_tag: Optional[str] = None,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """返回当前联盟订阅部落的已结束普通战档案，不触发外部同步。"""
    context = _context(user, alliance_id, db)
    if clan_tag:
        _subscribed_clan(context, clan_tag)
    result = legacy_routes._war_history_for_clans(
        db, _configured_context_clans(context), clan_tag,
    )
    result["alliance_id"] = alliance_id
    return result


@router.get("/alliances/{alliance_id}/wars/history/{clan_tag}/{war_key}")
def alliance_war_history_detail(
    alliance_id: int,
    clan_tag: str,
    war_key: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """返回当前联盟订阅部落的一场已结束普通战详情。"""
    context = _context(user, alliance_id, db)
    clan = _subscribed_clan(context, clan_tag)
    configured = {
        "tag": clan.clan_tag,
        "name": clan.clan_name,
        "category": clan.category,
    }
    result = legacy_routes._war_history_detail_for_clan(db, configured, war_key)
    result["alliance_id"] = alliance_id
    return result


@router.get("/alliances/{alliance_id}/war-stats")
def alliance_war_stats(
    alliance_id: int,
    clan_tag: Optional[str] = None,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """按当前联盟的战营标签返回普通战固定窗口统计。"""
    context = _context(user, alliance_id, db)
    combat_clans = [clan for clan in context.clans if clan.category == "combat"]
    options = [
        {"clan_tag": clan.clan_tag, "clan_name": clan.clan_name}
        for clan in combat_clans
    ]
    if clan_tag:
        selected = _subscribed_clan(context, clan_tag)
        if selected.category != "combat":
            raise HTTPException(status_code=404, detail="部落不是当前联盟的战营部落")
    else:
        selected = combat_clans[0] if combat_clans else None
    if selected is None:
        return {
            "alliance_id": alliance_id,
            "clan_tag": None,
            "clan_name": None,
            "combat_clans": [],
            "stats": [],
            "updated_at": None,
            "history_coverage": {"available": 0, "target": 45, "complete": False},
        }
    result = legacy_routes._war_stats_for_clan(db, {
        "tag": selected.clan_tag,
        "name": selected.clan_name,
        "category": selected.category,
    })
    result["alliance_id"] = alliance_id
    result["combat_clans"] = options
    return result


@router.get("/alliances/{alliance_id}/league-stats")
def alliance_league_stats(
    alliance_id: int,
    period: Optional[str] = None,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """按联盟各月配置的实战队伍返回 CWL 滚动窗口统计。"""
    context = _context(user, alliance_id, db)
    if context.role not in {"admin", "leader"}:
        raise HTTPException(status_code=403, detail="联赛历史统计需要管理权限")
    selected_period = period or legacy_routes._get_current_period()
    if not legacy_routes._valid_period(selected_period):
        raise HTTPException(status_code=400, detail="period 必须为 YYYY-MM")
    windows = {
        "1m": set(legacy_routes._get_window_months(selected_period, 1)),
        "3m": set(legacy_routes._get_window_months(selected_period, 3)),
        "6m": set(legacy_routes._get_window_months(selected_period, 6)),
    }
    all_months = sorted(set().union(*windows.values()))
    placeholders = ",".join("?" for _ in all_months)
    rows = db.conn.execute(
        f"""SELECT results.player_tag, results.account_name, results.period,
                   results.attacks, results.offense_3stars,
                   results.defense_3stars, results.defense_total,
                   results.fetched_at
            FROM league_results AS results
            JOIN alliance_cwl_seasons AS seasons
              ON seasons.alliance_id = ? AND seasons.period = results.period
            JOIN alliance_cwl_teams AS teams
              ON teams.season_id = seasons.id
             AND teams.clan_tag = results.clan_tag
             AND teams.category = 'combat'
            WHERE results.period IN ({placeholders})""",
        (context.alliance_id, *all_months),
    ).fetchall()
    tags = sorted({row["player_tag"] for row in rows if row["player_tag"]})
    accounts = {}
    if tags:
        tag_placeholders = ",".join("?" for _ in tags)
        accounts = {
            row["player_tag"]: dict(row)
            for row in db.conn.execute(
                f"""SELECT player_tag, account_name, town_hall_level
                    FROM accounts WHERE player_tag IN ({tag_placeholders})""",
                tags,
            ).fetchall()
        }
    metrics: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {
            key: {"offense_3stars": 0, "attacks": 0, "defense_3stars": 0, "defense_total": 0}
            for key in windows
        }
    )
    names = {}
    updated = []
    for row in rows:
        tag = row["player_tag"]
        names.setdefault(tag, row["account_name"] or tag)
        if row["fetched_at"] and str(row["fetched_at"])[:4].isdigit():
            updated.append(row["fetched_at"])
        for key, months in windows.items():
            if row["period"] not in months:
                continue
            metrics[tag][key]["offense_3stars"] += row["offense_3stars"] or 0
            metrics[tag][key]["attacks"] += row["attacks"] or 0
            metrics[tag][key]["defense_3stars"] += row["defense_3stars"] or 0
            metrics[tag][key]["defense_total"] += row["defense_total"] or 0
    result = []
    for tag in tags:
        account = accounts.get(tag, {})
        item = {
            "player_tag": tag,
            "account_name": account.get("account_name") or names.get(tag) or tag,
            "town_hall_level": account.get("town_hall_level"),
        }
        for key in windows:
            sample = metrics[tag][key]
            item[f"offense_{key}"] = legacy_routes._calc_rate(
                sample["offense_3stars"], sample["attacks"],
            )
            item[f"defense_{key}"] = legacy_routes._calc_rate(
                sample["defense_3stars"], sample["defense_total"],
            )
            item[f"offense_{key}_sample"] = {
                "three_stars": sample["offense_3stars"], "attacks": sample["attacks"],
            }
            item[f"defense_{key}_sample"] = {
                "three_stars": sample["defense_3stars"], "attacks": sample["defense_total"],
            }
        result.append(item)
    return {
        "alliance_id": alliance_id,
        "period": selected_period,
        "stats": result,
        "updated_at": max(updated) if updated else None,
    }


def _historical_cwl_allowed(context: AllianceContext, period: str) -> None:
    if period == legacy_routes._current_cwl_live_period():
        return
    if context.role not in {"admin", "leader"}:
        raise HTTPException(status_code=403, detail="历史联赛数据需要管理权限")


def _cwl_config_error(exc: CwlConfigError) -> HTTPException:
    status = 403 if "权限" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


def _configured_cwl_teams(
    context: AllianceContext,
    db: Database,
    period: str,
) -> tuple[dict | None, list[dict]]:
    """读取已确认的联盟月度队伍，并适配既有 CWL 展示构建器。"""
    season = season_payload(db.conn, context, period, include_draft=False)
    if season is None or season["status"] == "draft":
        return season, []
    legacy_by_tag = {
        normalize_tag(item.get("clan_tag")): item
        for item in legacy_routes._cwl_live_teams(db, period)
        if normalize_tag(item.get("clan_tag"))
    }
    teams = []
    for item in season["teams"]:
        legacy = legacy_by_tag.get(item["clan_tag"], {})
        teams.append({
            "period": period,
            "team_index": item["team_index"],
            "team_alias": item["team_alias"] or item["clan_name_snapshot"] or item["clan_tag"],
            "team_name": item["clan_name_snapshot"] or legacy.get("team_name") or item["clan_tag"],
            "clan_tag": item["clan_tag"],
            "category": item["category"],
            "member_count": legacy.get("member_count", 0),
            "league_level": legacy.get("league_level"),
            "leader_name": legacy.get("leader_name", ""),
            "manager_names": legacy.get("manager_names", ""),
        })
    return season, teams


def _alliance_cwl_available_periods(
    context: AllianceContext,
    db: Database,
) -> list[dict]:
    current = legacy_routes._current_cwl_live_period()
    items = [{"period": current, "label": f"{current[:4]}年{int(current[5:])}月", "current": True}]
    for season in list_seasons(db.conn, context):
        period = season["period"]
        if period == current or season["status"] != "complete":
            continue
        items.append({
            "period": period,
            "label": f"{period[:4]}年{int(period[5:])}月",
            "current": False,
        })
    return items


@router.get("/alliances/{alliance_id}/cwl/seasons")
def alliance_cwl_seasons_list(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    seasons = list_seasons(db.conn, context)
    db.conn.commit()
    return {"alliance_id": alliance_id, "count": len(seasons), "seasons": seasons}


@router.get("/alliances/{alliance_id}/cwl/seasons/{period}")
def alliance_cwl_season_detail(
    alliance_id: int,
    period: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        season = season_payload(
            db.conn,
            context,
            period,
            include_draft=context.role in {"admin", "leader"},
        )
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc
    if season is None:
        raise HTTPException(status_code=404, detail="联赛月份配置不存在")
    db.conn.commit()
    return {"alliance_id": alliance_id, **season}


@router.post("/alliances/{alliance_id}/cwl/seasons/{period}")
def alliance_cwl_season_create(
    alliance_id: int,
    period: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        return {"alliance_id": alliance_id, **create_season(db.conn, context, period)}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


@router.post("/alliances/{alliance_id}/cwl/seasons/{period}/copy-previous")
def alliance_cwl_season_copy_previous(
    alliance_id: int,
    period: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        return {"alliance_id": alliance_id, **copy_previous(db.conn, context, period)}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


@router.post("/alliances/{alliance_id}/cwl/seasons/{period}/teams")
def alliance_cwl_team_add(
    alliance_id: int,
    period: str,
    payload: CwlTeamInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        team = add_team(
            db.conn,
            context,
            period,
            clan_tag=payload.clan_tag,
            clan_name=payload.clan_name,
            team_alias=payload.team_alias,
            category=payload.category,
        )
        return {"alliance_id": alliance_id, "period": period, "team": team}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


@router.put("/alliances/{alliance_id}/cwl/seasons/{period}/teams/{team_id}")
def alliance_cwl_team_update(
    alliance_id: int,
    period: str,
    team_id: int,
    payload: CwlTeamInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        team = update_team(
            db.conn,
            context,
            period,
            team_id,
            clan_tag=payload.clan_tag,
            clan_name=payload.clan_name,
            team_alias=payload.team_alias,
            category=payload.category,
            sort_order=payload.sort_order,
        )
        return {"alliance_id": alliance_id, "period": period, "team": team}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


@router.delete("/alliances/{alliance_id}/cwl/seasons/{period}/teams/{team_id}")
def alliance_cwl_team_delete(
    alliance_id: int,
    period: str,
    team_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        delete_team(db.conn, context, period, team_id)
        return {"alliance_id": alliance_id, "period": period, "deleted": True}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


@router.post("/alliances/{alliance_id}/cwl/seasons/{period}/teams/{team_id}/correct-tag")
def alliance_cwl_team_correct_tag(
    alliance_id: int,
    period: str,
    team_id: int,
    payload: CwlTagCorrectionInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        team = correct_frozen_tag(
            db.conn,
            context,
            period,
            team_id,
            clan_tag=payload.clan_tag,
            reason=payload.reason,
        )
        return {"alliance_id": alliance_id, "period": period, "team": team}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


@router.post("/alliances/{alliance_id}/cwl/seasons/{period}/confirm")
def alliance_cwl_season_confirm(
    alliance_id: int,
    period: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    context = _context(user, alliance_id, db)
    try:
        return {"alliance_id": alliance_id, **confirm_season(db.conn, context, period)}
    except CwlConfigError as exc:
        raise _cwl_config_error(exc) from exc


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
    season, teams = _configured_cwl_teams(context, db, selected_period)
    result = legacy_routes._build_cwl_live_summary(db, selected_period, teams=teams)
    result["alliance_id"] = alliance_id
    result["available_periods"] = _alliance_cwl_available_periods(context, db)
    result["season_status"] = season.get("status") if season else None
    result["configured_team_count"] = len(teams)
    result["empty_reason"] = "no_config" if not teams else None
    result["updated_at"] = max(
        (item.get("synced_at") for item in result["clans"] if item.get("synced_at")),
        default=None,
    )
    db.conn.commit()
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
    selected_period = period or legacy_routes._current_cwl_live_period()
    normalized = normalize_tag(clan_tag)
    if not legacy_routes._valid_period(selected_period):
        raise HTTPException(status_code=400, detail="period 必须为 YYYY-MM")
    _historical_cwl_allowed(context, selected_period)
    _season, teams = _configured_cwl_teams(context, db, selected_period)
    if normalized not in {item["clan_tag"] for item in teams}:
        raise HTTPException(status_code=404, detail="部落不在当前联盟联赛队伍范围内")
    result = legacy_routes._build_cwl_live_detail(
        db,
        normalized,
        selected_period,
        round=round,
        view=view,
        teams=teams,
    )
    result["alliance_id"] = alliance_id
    db.conn.commit()
    return result
