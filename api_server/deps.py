"""依赖注入：数据库连接 + Repository 单例。

所有路由通过 Depends 获取数据库连接，避免每次请求重新初始化。
"""
from __future__ import annotations

import os
from pathlib import Path

from shared.db.connection import Database
from modules.player.repository import PlayerRepository

__all__ = ["get_db", "get_repo"]

# 数据库连接（模块级单例，进程内共享）
_db: Database | None = None
_repo: PlayerRepository | None = None


def _get_db_path() -> str:
    """从 config 读取 db_path，相对路径转为基于项目根目录的绝对路径。"""
    from config import DB_PATH

    if os.path.isabs(DB_PATH):
        return DB_PATH
    # 项目根目录 = config/ 的父目录
    root = Path(__file__).parent.parent
    return str(root / DB_PATH)


def get_db() -> Database:
    """获取 Database 单例。"""
    global _db
    if _db is None:
        _db = Database(_get_db_path())
        _db.init_schema()
    return _db


def get_repo() -> PlayerRepository:
    """获取 PlayerRepository 单例。"""
    global _repo
    if _repo is None:
        _repo = PlayerRepository(get_db().conn)
    return _repo
