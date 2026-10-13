"""联盟月度 CWL 队伍配置与苍穹兼容迁移。"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from modules.coc_sync.official.mapper import normalize_tag

from .access import AllianceContext
from .migration import SKY_ALLIANCE_KEY


PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
VALID_CATEGORIES = {"combat", "shell"}
EDITABLE_STATUSES = {"draft", "active"}


class CwlConfigError(ValueError):
    """可安全返回给客户端的配置错误。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_period() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def next_period(period: str) -> str:
    year, month = (int(value) for value in period.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def validate_period(period: str) -> str:
    if not PERIOD_RE.fullmatch(period or ""):
        raise CwlConfigError("period 必须为 YYYY-MM")
    return period


def editable_period(period: str) -> bool:
    selected = validate_period(period)
    current = current_period()
    return selected in {current, next_period(current)}


def require_manager(context: AllianceContext) -> None:
    if context.role not in {"admin", "leader"}:
        raise CwlConfigError("联赛配置需要联盟管理权限")
    if context.plan_code == "paid" and context.entitlement_status in {"grace", "expired", "revoked"}:
        raise CwlConfigError("付费权益处于宽限期或已到期，联赛配置暂时只读")


def max_cwl_teams(context: AllianceContext) -> int:
    value = context.entitlements.get("max_cwl_teams")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = {"free": 1, "paid": 20, "internal": 100}.get(context.plan_code, 1)
    return max(1, parsed)


def _audit(
    conn: sqlite3.Connection,
    context: AllianceContext,
    action: str,
    entity_type: str,
    entity_id: int,
    details: dict,
    now: str,
) -> None:
    conn.execute(
        """INSERT INTO alliance_audit_events
           (alliance_id, actor_user_id, action, entity_type, entity_id,
            details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            context.alliance_id, context.user_id, action, entity_type,
            str(entity_id), json.dumps(details, ensure_ascii=False, sort_keys=True), now,
        ),
    )


def _season_row(conn: sqlite3.Connection, alliance_id: int, period: str):
    return conn.execute(
        "SELECT * FROM alliance_cwl_seasons WHERE alliance_id = ? AND period = ?",
        (alliance_id, period),
    ).fetchone()


def _refresh_status(conn: sqlite3.Connection, season_id: int) -> str:
    season = conn.execute(
        "SELECT id, period, status FROM alliance_cwl_seasons WHERE id = ?",
        (season_id,),
    ).fetchone()
    if season is None:
        raise CwlConfigError("联赛月份配置不存在")
    status = season["status"]
    if status == "draft":
        return status

    rows = conn.execute(
        """SELECT groups.raw_status
           FROM alliance_cwl_teams AS teams
           JOIN cwl_live_group_cache AS groups
             ON groups.period = ? AND groups.clan_tag = teams.clan_tag
           WHERE teams.season_id = ?""",
        (season["period"], season_id),
    ).fetchall()
    if not rows:
        target = "active"
    elif all(row["raw_status"] == "complete" for row in rows):
        target = "complete"
    else:
        target = "frozen"
    if target != status:
        conn.execute(
            "UPDATE alliance_cwl_seasons SET status = ?, updated_at = ? WHERE id = ?",
            (target, utc_now(), season_id),
        )
    return target


def refresh_season_statuses(conn: sqlite3.Connection, period: str) -> dict[str, int]:
    """根据公共分组缓存刷新指定月份的联盟配置状态。"""
    counts = {"active": 0, "frozen": 0, "complete": 0, "draft": 0}
    with conn:
        for row in conn.execute(
            "SELECT id FROM alliance_cwl_seasons WHERE period = ?", (validate_period(period),)
        ).fetchall():
            status = _refresh_status(conn, int(row["id"]))
            counts[status] = counts.get(status, 0) + 1
    return counts


def _teams(conn: sqlite3.Connection, season_id: int) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            """SELECT id, team_index, clan_tag, clan_name_snapshot, team_alias,
                      category, sort_order, source, created_at, updated_at
               FROM alliance_cwl_teams
               WHERE season_id = ?
               ORDER BY sort_order, team_index, id""",
            (season_id,),
        ).fetchall()
    ]


def season_payload(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
    *,
    include_draft: bool = False,
) -> dict | None:
    selected = validate_period(period)
    row = _season_row(conn, context.alliance_id, selected)
    if row is None:
        return None
    status = _refresh_status(conn, int(row["id"]))
    if status == "draft" and not include_draft and context.role not in {"admin", "leader"}:
        return None
    result = dict(row)
    result["status"] = status
    result["teams"] = _teams(conn, int(row["id"]))
    result["team_count"] = len(result["teams"])
    result["max_teams"] = max_cwl_teams(context)
    result["can_edit"] = (
        context.role in {"admin", "leader"}
        and not (
            context.plan_code == "paid"
            and context.entitlement_status in {"grace", "expired", "revoked"}
        )
        and editable_period(selected)
        and status in EDITABLE_STATUSES
    )
    return result


def list_seasons(conn: sqlite3.Connection, context: AllianceContext) -> list[dict]:
    periods = [
        row[0]
        for row in conn.execute(
            """SELECT period FROM alliance_cwl_seasons
               WHERE alliance_id = ? ORDER BY period DESC""",
            (context.alliance_id,),
        ).fetchall()
    ]
    return [
        payload
        for period in periods
        if (
            payload := season_payload(
                conn,
                context,
                period,
                include_draft=context.role in {"admin", "leader"},
            )
        ) is not None
    ]


def create_season(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
) -> dict:
    require_manager(context)
    selected = validate_period(period)
    if not editable_period(selected):
        raise CwlConfigError("只能配置当前月和下月联赛")
    now = utc_now()
    with conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO alliance_cwl_seasons
               (alliance_id, period, status, created_by_user_id, created_at, updated_at)
               VALUES (?, ?, 'draft', ?, ?, ?)""",
            (context.alliance_id, selected, context.user_id, now, now),
        )
        if cursor.rowcount:
            season = _season_row(conn, context.alliance_id, selected)
            _audit(
                conn, context, "cwl_season_created", "alliance_cwl_season",
                int(season["id"]), {"period": selected}, now,
            )
    return season_payload(conn, context, selected, include_draft=True) or {}


def _editable_season(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
) -> sqlite3.Row:
    require_manager(context)
    selected = validate_period(period)
    if not editable_period(selected):
        raise CwlConfigError("只能修改当前月和下月联赛")
    row = _season_row(conn, context.alliance_id, selected)
    if row is None:
        create_season(conn, context, selected)
        row = _season_row(conn, context.alliance_id, selected)
    status = _refresh_status(conn, int(row["id"]))
    if status not in EDITABLE_STATUSES:
        raise CwlConfigError("官方联赛组已发现，本月配置已冻结")
    return row


def add_team(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
    *,
    clan_tag: str,
    clan_name: str | None,
    team_alias: str | None,
    category: str,
) -> dict:
    season = _editable_season(conn, context, period)
    normalized = normalize_tag(clan_tag)
    if not normalized:
        raise CwlConfigError("请输入有效的部落标签")
    if category not in VALID_CATEGORIES:
        raise CwlConfigError("category 仅支持 combat/shell")
    count = conn.execute(
        "SELECT COUNT(*) FROM alliance_cwl_teams WHERE season_id = ?",
        (season["id"],),
    ).fetchone()[0]
    if int(count) >= max_cwl_teams(context):
        raise CwlConfigError(f"当前套餐每月最多配置 {max_cwl_teams(context)} 支联赛队伍")
    next_index = conn.execute(
        "SELECT COALESCE(MAX(team_index), -1) + 1 FROM alliance_cwl_teams WHERE season_id = ?",
        (season["id"],),
    ).fetchone()[0]
    now = utc_now()
    try:
        with conn:
            cursor = conn.execute(
                """INSERT INTO alliance_cwl_teams
                   (season_id, team_index, clan_tag, clan_name_snapshot, team_alias,
                    category, sort_order, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)""",
                (
                    season["id"], next_index, normalized, clan_name or normalized,
                    team_alias or clan_name or normalized, category, next_index, now, now,
                ),
            )
            conn.execute(
                "UPDATE alliance_cwl_seasons SET updated_at = ? WHERE id = ?",
                (now, season["id"]),
            )
            _audit(
                conn, context, "cwl_team_added", "alliance_cwl_team",
                int(cursor.lastrowid),
                {"period": period, "clan_tag": normalized, "category": category}, now,
            )
    except sqlite3.IntegrityError as exc:
        raise CwlConfigError("该部落已在本月联赛队伍中") from exc
    return dict(conn.execute("SELECT * FROM alliance_cwl_teams WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_team(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
    team_id: int,
    *,
    clan_tag: str,
    clan_name: str | None,
    team_alias: str | None,
    category: str,
    sort_order: int,
) -> dict:
    season = _editable_season(conn, context, period)
    normalized = normalize_tag(clan_tag)
    if not normalized:
        raise CwlConfigError("请输入有效的部落标签")
    if category not in VALID_CATEGORIES:
        raise CwlConfigError("category 仅支持 combat/shell")
    if sort_order < 0:
        raise CwlConfigError("sort_order 不能小于 0")
    now = utc_now()
    before = conn.execute(
        "SELECT * FROM alliance_cwl_teams WHERE id=? AND season_id=?",
        (team_id, season["id"]),
    ).fetchone()
    try:
        with conn:
            cursor = conn.execute(
                """UPDATE alliance_cwl_teams
                   SET clan_tag = ?, clan_name_snapshot = ?, team_alias = ?,
                       category = ?, sort_order = ?, updated_at = ?
                   WHERE id = ? AND season_id = ?""",
                (
                    normalized, clan_name or normalized, team_alias or clan_name or normalized,
                    category, sort_order, now, team_id, season["id"],
                ),
            )
            if cursor.rowcount != 1:
                raise CwlConfigError("联赛队伍不存在")
            conn.execute(
                "UPDATE alliance_cwl_seasons SET updated_at = ? WHERE id = ?",
                (now, season["id"]),
            )
            _audit(
                conn, context, "cwl_team_updated", "alliance_cwl_team", team_id,
                {
                    "period": period,
                    "before": dict(before) if before is not None else None,
                    "after": {
                        "clan_tag": normalized, "clan_name": clan_name or normalized,
                        "team_alias": team_alias or clan_name or normalized,
                        "category": category, "sort_order": sort_order,
                    },
                }, now,
            )
    except sqlite3.IntegrityError as exc:
        raise CwlConfigError("该部落或队伍序号与现有配置冲突") from exc
    return dict(conn.execute("SELECT * FROM alliance_cwl_teams WHERE id = ?", (team_id,)).fetchone())


def delete_team(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
    team_id: int,
) -> None:
    season = _editable_season(conn, context, period)
    team = conn.execute(
        "SELECT * FROM alliance_cwl_teams WHERE id=? AND season_id=?",
        (team_id, season["id"]),
    ).fetchone()
    with conn:
        cursor = conn.execute(
            "DELETE FROM alliance_cwl_teams WHERE id = ? AND season_id = ?",
            (team_id, season["id"]),
        )
        if cursor.rowcount != 1:
            raise CwlConfigError("联赛队伍不存在")
        now = utc_now()
        conn.execute("UPDATE alliance_cwl_seasons SET updated_at = ? WHERE id = ?", (now, season["id"]))
        _audit(
            conn, context, "cwl_team_deleted", "alliance_cwl_team", team_id,
            {"period": period, "team": dict(team) if team is not None else None}, now,
        )


def copy_previous(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
) -> dict:
    target = _editable_season(conn, context, period)
    existing = conn.execute(
        "SELECT COUNT(*) FROM alliance_cwl_teams WHERE season_id = ?", (target["id"],)
    ).fetchone()[0]
    if existing:
        raise CwlConfigError("当前月份已有队伍，不能复制上月")
    year, month = (int(value) for value in period.split("-"))
    previous = f"{year - 1:04d}-12" if month == 1 else f"{year:04d}-{month - 1:02d}"
    source = _season_row(conn, context.alliance_id, previous)
    if source is None:
        raise CwlConfigError("上月没有可复制的联赛配置")
    rows = _teams(conn, int(source["id"]))
    if len(rows) > max_cwl_teams(context):
        raise CwlConfigError("上月队伍数量超过当前套餐额度")
    now = utc_now()
    with conn:
        for row in rows:
            conn.execute(
                """INSERT INTO alliance_cwl_teams
                   (season_id, team_index, clan_tag, clan_name_snapshot, team_alias,
                    category, sort_order, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'copied', ?, ?)""",
                (
                    target["id"], row["team_index"], row["clan_tag"],
                    row["clan_name_snapshot"], row["team_alias"], row["category"],
                    row["sort_order"], now, now,
                ),
            )
        _audit(
            conn, context, "cwl_teams_copied", "alliance_cwl_season", int(target["id"]),
            {"period": period, "source_period": previous, "team_count": len(rows)}, now,
        )
    return season_payload(conn, context, period, include_draft=True) or {}


def confirm_season(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
) -> dict:
    season = _editable_season(conn, context, period)
    count = conn.execute(
        "SELECT COUNT(*) FROM alliance_cwl_teams WHERE season_id = ?", (season["id"],)
    ).fetchone()[0]
    if not count:
        raise CwlConfigError("至少添加一支联赛队伍后才能确认")
    now = utc_now()
    with conn:
        conn.execute(
            """UPDATE alliance_cwl_seasons
               SET status = 'active', confirmed_by_user_id = ?, confirmed_at = ?, updated_at = ?
               WHERE id = ?""",
            (context.user_id, now, now, season["id"]),
        )
        conn.execute(
            """INSERT INTO alliance_audit_events
               (alliance_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
               VALUES (?, ?, 'confirm_cwl_season', 'alliance_cwl_season', ?, ?, ?)""",
            (
                context.alliance_id, context.user_id, str(season["id"]),
                json.dumps({"period": period, "team_count": int(count)}, ensure_ascii=False), now,
            ),
        )
    return season_payload(conn, context, period, include_draft=True) or {}


def correct_frozen_tag(
    conn: sqlite3.Connection,
    context: AllianceContext,
    period: str,
    team_id: int,
    *,
    clan_tag: str,
    reason: str,
) -> dict:
    require_manager(context)
    season = _season_row(conn, context.alliance_id, validate_period(period))
    if season is None or _refresh_status(conn, int(season["id"])) not in {"frozen", "complete"}:
        raise CwlConfigError("仅冻结后的月份使用纠正 Tag 操作")
    if not reason.strip():
        raise CwlConfigError("纠正 Tag 必须填写原因")
    row = conn.execute(
        "SELECT * FROM alliance_cwl_teams WHERE id = ? AND season_id = ?",
        (team_id, season["id"]),
    ).fetchone()
    if row is None:
        raise CwlConfigError("联赛队伍不存在")
    normalized = normalize_tag(clan_tag)
    if not normalized:
        raise CwlConfigError("请输入有效的部落标签")
    old_tag = row["clan_tag"]
    now = utc_now()
    try:
        with conn:
            conn.execute(
                "UPDATE alliance_cwl_teams SET clan_tag = ?, source = 'corrected', updated_at = ? WHERE id = ?",
                (normalized, now, team_id),
            )
            conn.execute(
                """INSERT INTO alliance_audit_events
                   (alliance_id, actor_user_id, action, entity_type, entity_id, details_json, created_at)
                   VALUES (?, ?, 'correct_cwl_team_tag', 'alliance_cwl_team', ?, ?, ?)""",
                (
                    context.alliance_id, context.user_id, str(team_id),
                    json.dumps(
                        {"period": period, "old_tag": old_tag, "new_tag": normalized, "reason": reason.strip()},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise CwlConfigError("纠正后的部落已在本月配置中") from exc
    return dict(conn.execute("SELECT * FROM alliance_cwl_teams WHERE id = ?", (team_id,)).fetchone())


def sync_sky_league_teams(
    conn: sqlite3.Connection,
    period: str | None = None,
    *,
    source: str = "migrated",
) -> dict:
    """把苍穹 ``league_teams`` 幂等映射到联盟月度配置。

    已冻结/完成月份绝不被普通编排静默覆盖。
    """
    alliance = conn.execute(
        "SELECT id FROM alliances WHERE alliance_key = ?", (SKY_ALLIANCE_KEY,)
    ).fetchone()
    if alliance is None:
        return {"periods": 0, "teams": 0, "skipped_frozen": 0}
    params: tuple[object, ...] = ()
    where = ""
    if period is not None:
        where = "WHERE period = ?"
        params = (validate_period(period),)
    periods = [
        row[0]
        for row in conn.execute(
            f"SELECT DISTINCT period FROM league_teams {where} ORDER BY period", params
        ).fetchall()
    ]
    now = utc_now()
    team_count = 0
    skipped = 0
    with conn:
        for selected in periods:
            season = _season_row(conn, int(alliance["id"]), selected)
            if season is None:
                cursor = conn.execute(
                    """INSERT INTO alliance_cwl_seasons
                       (alliance_id, period, status, created_at, updated_at, confirmed_at)
                       VALUES (?, ?, 'active', ?, ?, ?)""",
                    (alliance["id"], selected, now, now, now),
                )
                season_id = int(cursor.lastrowid)
            else:
                season_id = int(season["id"])
                status = _refresh_status(conn, season_id)
                if status in {"frozen", "complete"}:
                    skipped += 1
                    continue
                conn.execute(
                    """UPDATE alliance_cwl_seasons
                       SET status = 'active', confirmed_at = COALESCE(confirmed_at, ?), updated_at = ?
                       WHERE id = ?""",
                    (now, now, season_id),
                )
                conn.execute("DELETE FROM alliance_cwl_teams WHERE season_id = ?", (season_id,))
            rows = conn.execute(
                """SELECT team_index, team_alias, team_name, clan_tag, category
                   FROM league_teams WHERE period = ? ORDER BY team_index""",
                (selected,),
            ).fetchall()
            for row in rows:
                tag = normalize_tag(row["clan_tag"])
                if not tag:
                    continue
                category = row["category"] if row["category"] in VALID_CATEGORIES else "shell"
                conn.execute(
                    """INSERT INTO alliance_cwl_teams
                       (season_id, team_index, clan_tag, clan_name_snapshot, team_alias,
                        category, sort_order, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        season_id, row["team_index"], tag, row["team_name"] or tag,
                        row["team_alias"] or row["team_name"] or tag, category,
                        row["team_index"], source, now, now,
                    ),
                )
                team_count += 1
            _refresh_status(conn, season_id)
    return {"periods": len(periods) - skipped, "teams": team_count, "skipped_frozen": skipped}
