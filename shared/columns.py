"""表头关键词解析与单元格取值的公共工具（纯函数，无 IO）。

报名表与战绩表的真实表头都带换行/空格，且列语义随月份漂移（列位不固定），
因此统一使用"表头去空白后包含任一 include 关键词、且不含任何 exclude 关键词即命中"
的关键词映射，而非精确等值匹配。报名/战绩两个模块共用这套解析规则，保证
两侧对"游戏昵称/玩家Tag"等列的取法一致（修复 tag 体系不一致隐患的基础）。
"""
from __future__ import annotations


def norm_header(text) -> str:
    """表头归一化：转字符串并去掉所有空白（含换行），用于关键词包含匹配。"""
    if text is None:
        return ""
    return "".join(str(text).split())


def resolve_columns(headers: list[str], spec: dict) -> dict[str, str]:
    """按关键词规则把内部字段名解析到实际表头名。

    spec: {field: {"include": [...], "exclude": [...]}}
    命中规则：归一化表头包含任一 include 且不含任何 exclude；多个命中取第一个。
    返回 {field: 原始表头名}，未命中的字段不在结果中。
    """
    norm_pairs = [(h, norm_header(h).lower()) for h in headers]
    resolved: dict[str, str] = {}
    for field, rule in spec.items():
        includes = [k.lower() for k in rule.get("include", [])]
        excludes = [k.lower() for k in rule.get("exclude", [])]
        for original, norm in norm_pairs:
            if any(k in norm for k in includes) and not any(k in norm for k in excludes):
                resolved[field] = original
                break
    return resolved


def to_float(value) -> float | None:
    """把单元格值转 float；空/非法返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def clean_str(value) -> str | None:
    """去空白后的字符串；空返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()
