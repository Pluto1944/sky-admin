"""FastAPI 应用工厂。

创建 FastAPI 实例，挂载路由，配置 CORS（供小程序调用）。
"""
from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config.env_loader import load_env
from .routes import router

# 加载 .env 到 os.environ（必须在 create_app 之前）
load_env()


def create_app() -> FastAPI:
    # 生产环境关闭自动文档，减少攻击面
    is_prod = os.environ.get("SKY_ADMIN_ENV") == "production"
    app = FastAPI(
        title="Sky Admin API",
        description="COC 联赛管理后台 API",
        version="0.1.0",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    # CORS：允许小程序及本地调试
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()
