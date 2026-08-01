"""自动加载项目根 .env 文件到 os.environ。

安全设计（与 load_env.sh 一致）：
- 逐行解析 KEY=VALUE，不使用 source（防注入）
- 跳过空行与 # 注释
- 已在 os.environ 中的同名变量优先（不覆盖）
- 兼容 CRLF 行尾
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def load_env() -> None:
    """加载项目根 .env 到 os.environ。"""
    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.is_file():
        return  # 静默跳过，允许无 .env 环境运行

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        # 去首尾空白及成对引号
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        # 环境变量已有值时优先保留，不覆盖
        if key not in os.environ:
            os.environ[key] = val
