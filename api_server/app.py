"""FastAPI 应用工厂。

创建 FastAPI 实例，挂载路由，配置 CORS（供小程序调用）。
"""
from __future__ import annotations

import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config.env_loader import load_env
from shared.runtime_identity import capture_runtime_identity
from .routes import router

# 加载 .env 到 os.environ（必须在 create_app 之前）
load_env()
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    runtime_identity = capture_runtime_identity("api")
    # 生产环境关闭自动文档，减少攻击面
    is_prod = os.environ.get("SKY_ADMIN_ENV") == "production"
    app = FastAPI(
        title="Sky Admin API",
        description="COC 联赛管理后台 API",
        version=runtime_identity.release_version,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.state.runtime_identity = runtime_identity
    logger.info(
        "API 启动身份：版本=%s 提交=%s tracked_dirty=%s",
        runtime_identity.release_version,
        runtime_identity.git_commit[:12],
        runtime_identity.tracked_dirty,
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
