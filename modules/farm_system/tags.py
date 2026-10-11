"""互刷系统使用的 COC 标签规范化。"""
from __future__ import annotations

from modules.coc_sync.official.mapper import normalize_tag


def coc_tag_key(value: str | None) -> str | None:
    """生成唯一比较键；COC 标签不含字母 O，历史 O 视为数字 0。"""
    normalized = normalize_tag(value)
    return normalized.replace("O", "0") if normalized else None
