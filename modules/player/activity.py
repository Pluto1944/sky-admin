"""根据公开 COC 快照估算最近数据活动（纯函数）。"""
from __future__ import annotations

import json
from typing import Any


COUNTER_FIELDS = (
    ("donations", "donations"),
    ("donationsReceived", "donations_received"),
    ("expLevel", "exp_level"),
    ("townHallLevel", "town_hall_level"),
    ("attackWins", "season_attack_wins"),
)


def parse_raw(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _stable(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def activity_reasons(old_raw: Any, new_raw: Any) -> list[str]:
    """只认明确变化；首次出现、字段清空和赛季累计值下降均忽略。"""
    old = parse_raw(old_raw)
    new = parse_raw(new_raw)
    reasons: list[str] = []
    for api_field, reason in COUNTER_FIELDS:
        before = _number(old.get(api_field))
        after = _number(new.get(api_field))
        if before is not None and after is not None and after > before:
            reasons.append(reason)

    old_name = old.get("name")
    new_name = new.get("name")
    if old_name and new_name and old_name != new_name:
        reasons.append("name")

    old_house = _stable(old.get("playerHouse"))
    new_house = _stable(new.get("playerHouse"))
    if old_house is not None and new_house is not None and old_house != new_house:
        reasons.append("player_house")
    return reasons
