"""coc_sync 字段映射（纯函数，无 IO，便于单测）。

把 COC 官方 API 返回的原始成员/玩家 dict 映射成 player 档案的"COC 组"标准字段。
后续要新增字段：优先靠 coc_raw JSON 快照兜底（零改表），只有需要 SQL 过滤/排序的
才在此提列并同步在 accounts 表加列。
"""
from __future__ import annotations

import json
from typing import Optional

from config import MEMBERSHIP_MEMBER


def normalize_tag(tag: Optional[str]) -> Optional[str]:
    """规范化 Tag：去空白、大写、补 '#'。空值返回 None。"""
    if not tag or not str(tag).strip():
        return None
    t = str(tag).strip().upper()
    if not t.startswith("#"):
        t = "#" + t
    return t


# 向后兼容别名（历史调用点仍可用 _norm_tag）
_norm_tag = normalize_tag


def map_member(member: dict, clan_tag: str, clan_name: Optional[str] = None) -> dict:
    """把 `/clans/{tag}/members` 的一个成员 dict 映射为 player 档案 COC 组字段。

    member 至少含 tag / name / role / expLevel / trophies / townHallLevel /
    league 等（由官方 API 决定，字段缺失时对应值为 None）。
    clan_tag / clan_name 由遍历上下文注入（成员条目本身不含所属部落 tag）。
    返回的 coc_raw 为 JSON 字符串（原始成员数据 + 部落上下文），供全量快照与扩展。
    """
    league = member.get("league") or {}
    raw = dict(member)
    raw["_clan_tag"] = _norm_tag(clan_tag)
    if clan_name:
        raw["_clan_name"] = clan_name

    return {
        "player_tag": normalize_tag(member.get("tag")),
        "account_name": member.get("name"),
        "exp_level": member.get("expLevel"),
        "trophies": member.get("trophies"),
        # /clans/{tag}/members 接口已直接返回 townHallLevel，无需再调 /players/{tag} 补齐。
        "town_hall_level": member.get("townHallLevel"),
        "league_name": league.get("name"),
        "clan_tag": normalize_tag(clan_tag),
        "clan_role": member.get("role"),
        "coc_raw": json.dumps(raw, ensure_ascii=False),
        # 出现在部落成员列表 => 当前确在联盟部落内
        "membership_status": MEMBERSHIP_MEMBER,
    }
