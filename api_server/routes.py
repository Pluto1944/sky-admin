"""API 路由定义。

当前提供：
- GET /api/ping    健康检查
- GET /api/members 成员列表（读取 accounts 表）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from modules.player.repository import PlayerRepository
from .deps import get_repo

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
