"""互刷系统独立 JWT 工具和 FastAPI 鉴权依赖。"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from modules.farm_system.repository import FarmAccountRepository
from shared.db.connection import Database

from .deps import get_db


FARM_JWT_AUDIENCE = "farm-system"
FARM_JWT_ALGORITHM = "HS256"
FARM_JWT_EXPIRE_DAYS = 30
farm_security = HTTPBearer()


def _allowed_account_ids() -> set[int] | None:
    raw = os.environ.get("FARM_SYSTEM_ALLOWED_ACCOUNT_IDS")
    if raw is None or not raw.strip():
        return None
    allowed: set[int] = set()
    for value in raw.split(","):
        try:
            allowed.add(int(value.strip()))
        except ValueError:
            continue
    return allowed


def ensure_farm_account_allowed(account) -> None:
    allowed = _allowed_account_ids()
    if allowed is not None and int(account["id"]) not in allowed:
        raise HTTPException(status_code=403, detail="当前互刷账号尚未进入灰度范围")


def _get_farm_jwt_secret() -> str:
    return os.environ.get("FARM_JWT_SECRET") or os.environ.get(
        "JWT_SECRET", "sky-admin-dev-secret-change-me"
    )


def create_farm_token(account) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(account["id"]),
        "aud": FARM_JWT_AUDIENCE,
        "role": account["role"],
        "token_version": int(account["token_version"]),
        "iat": now,
        "exp": now + timedelta(days=FARM_JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, _get_farm_jwt_secret(), algorithm=FARM_JWT_ALGORITHM)


def decode_farm_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            _get_farm_jwt_secret(),
            algorithms=[FARM_JWT_ALGORITHM],
            audience=FARM_JWT_AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="互刷登录已过期，请重新登录",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的互刷登录凭证",
        ) from exc


def require_farm_account(
    credentials: HTTPAuthorizationCredentials = Depends(farm_security),
    db: Database = Depends(get_db),
) -> dict:
    payload = decode_farm_token(credentials.credentials)
    try:
        account_id = int(payload.get("sub"))
        token_version = int(payload.get("token_version"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="无效的互刷登录凭证") from exc

    row = FarmAccountRepository(db.conn).get_by_id(account_id)
    if row is None or row["status"] != "active":
        raise HTTPException(status_code=401, detail="互刷账号不存在或已停用")
    if int(row["token_version"]) != token_version:
        raise HTTPException(status_code=401, detail="互刷登录已失效，请重新登录")
    ensure_farm_account_allowed(row)
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "token_version": int(row["token_version"]),
    }
