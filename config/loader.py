"""YAML 配置加载与校验。"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml


class ConfigLoadError(Exception):
    """配置加载失败。"""


def load_settings(path: str | Path) -> dict[str, Any]:
    """加载并校验 settings.yaml。

    Raises:
        ConfigLoadError: 文件不存在或 YAML 格式错误
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigLoadError(f"配置文件不存在: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"YAML 解析失败: {e}") from e

    if not isinstance(cfg, dict):
        raise ConfigLoadError("配置文件顶层必须是字典")

    _validate(cfg)

    return cfg


def _validate(cfg: dict) -> None:
    """校验必要字段存在性。可按需扩展。"""
    required_sections = ["app", "account", "league", "coc_sync", "cwl_registration"]
    for section in required_sections:
        if section not in cfg:
            raise ConfigLoadError(f"缺少配置节: {section}")

    # 校验队伍 category 值合法
    for team in cfg.get("cwl_registration", {}).get("teams", []):
        cat = team.get("category")
        if cat not in ("combat", "shell"):
            raise ConfigLoadError(f"队伍 {team.get('name')} 的 category 值非法: {cat}")
