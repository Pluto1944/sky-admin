"""普通部落战历史归档的纯转换函数。"""
from __future__ import annotations

import hashlib

from modules.coc_sync.current_war import current_war_summary
from modules.coc_sync.official.mapper import normalize_tag


ARCHIVABLE_STATUSES = {"war_ended"}


def war_history_key(item: dict) -> str | None:
    """为同一自有部落的一场普通战争生成稳定、URL 安全的标识。"""
    clan_tag = normalize_tag(item.get("clan_tag"))
    anchor = (
        item.get("preparation_start_time")
        or item.get("start_time")
        or item.get("end_time")
    )
    opponent_tag = normalize_tag((item.get("opponent") or {}).get("tag"))
    if not clan_tag or not anchor or not opponent_tag:
        return None
    raw = f"{clan_tag}|{anchor}|{opponent_tag}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def is_archivable_war(item: dict) -> bool:
    """仅归档已结束且带完整身份的普通战争；CWL、进行中、空状态和错误不得进入历史。"""
    return (
        item.get("status") in ARCHIVABLE_STATUSES
        and item.get("war_type") != "cwl"
        and int(item.get("attacks_per_member") or 0) != 1
        and war_history_key(item) is not None
    )


def war_history_record(item: dict) -> dict:
    """从当前战争标准模型生成数据库归档记录。"""
    key = war_history_key(item)
    if not key or not is_archivable_war(item):
        raise ValueError("当前数据不是可归档的普通部落战")
    opponent = item.get("opponent") or {}
    return {
        "clan_tag": normalize_tag(item.get("clan_tag")),
        "war_key": key,
        "clan_name": item.get("clan_name") or item.get("clan_tag"),
        "category": item.get("category") or "normal",
        "opponent_tag": normalize_tag(opponent.get("tag")),
        "opponent_name": opponent.get("name") or opponent.get("tag") or "-",
        "status": item.get("status"),
        "result": item.get("result") or "pending",
        "preparation_start_time": item.get("preparation_start_time"),
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
        "source": item.get("history_source") or "official_currentwar",
        "finalized_at": item.get("synced_at"),
        "payload_version": int(item.get("payload_version") or 1),
        "updated_at": item.get("synced_at"),
        "data": item,
    }


def war_history_summary(item: dict, war_key: str) -> dict:
    """生成历史列表的轻量摘要，不返回成员宽表。"""
    return {**current_war_summary(item), "war_key": war_key}
