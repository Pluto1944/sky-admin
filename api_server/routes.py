"""API 路由定义。

当前提供：
- GET /api/ping            健康检查
- GET /api/members          成员列表（读取 accounts 表）
- GET /api/clan/league-stats  联赛战绩统计（滚动窗口三星率）
- POST /api/wechat/login    微信登录
- GET /api/wechat/me        当前用户信息
- POST /api/wechat/bind     绑定游戏账号
"""
from __future__ import annotations

import os
import requests
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from modules.player.repository import PlayerRepository
from .deps import get_repo, get_db
from .auth import create_token, require_user
from shared.db.connection import Database
from config import DB_PATH, LEAGUE_COMBAT, get_farm_clans

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
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {e}")


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
