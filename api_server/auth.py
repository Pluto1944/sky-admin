"""JWT 认证工具。

提供：
- create_token(openid, role)    生成 JWT token
- get_current_user(token)       解析 token 返回用户信息
- require_user(Depends)         FastAPI 依赖注入，保护需要登录的接口
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

security = HTTPBearer()


def _get_jwt_secret() -> str:
    """获取 JWT 签名密钥（从环境变量读取，由 app.py 中的 load_env() 预先加载）。"""
    return os.environ.get("JWT_SECRET", "sky-admin-dev-secret-change-me")


def create_token(openid: str, role: str = "member") -> str:
    """生成 JWT token，有效期 30 天。"""
    payload = {
        "openid": openid,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解析 JWT token，返回 payload。token 无效/过期时抛出异常。"""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 Token")


def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """FastAPI 依赖：从 Authorization header 解析当前用户。

    用法：
        @router.get("/api/me")
        def me(user = Depends(require_user)):
            return {"openid": user["openid"], "role": user["role"]}
    """
    return decode_token(credentials.credentials)
