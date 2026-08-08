"""API 路由定义。

当前提供：
- GET /api/ping            健康检查
- GET /api/members          成员列表（读取 accounts 表）
- POST /api/wechat/login    微信登录
- GET /api/wechat/me        当前用户信息
- POST /api/wechat/bind     绑定游戏账号
"""
from __future__ import annotations

import os
import requests
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from modules.player.repository import PlayerRepository
from .deps import get_repo, get_db
from .auth import create_token, require_user
from shared.db.connection import Database

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
