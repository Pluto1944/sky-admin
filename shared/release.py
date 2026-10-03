"""发布版本读取与校验。"""
from __future__ import annotations

import re
from pathlib import Path


VERSION_PATTERN = re.compile(r"^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"


def validate_release_version(value: str) -> str:
    """校验并返回标准的 Git Tag 版本号，例如 ``v1.1.1``。"""
    version = value.strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"无效发布版本号: {value!r}，应为 v主版本.次版本.修订版本")
    return version


def read_release_version(version_file: Path = VERSION_FILE) -> str:
    """读取仓库内与发布 Tag 对应的运行时版本。"""
    return validate_release_version(version_file.read_text(encoding="utf-8"))
