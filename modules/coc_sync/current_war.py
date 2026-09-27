"""当前部落战标准化与汇总计算。

本模块只做纯数据转换，不发网络请求、不读写数据库。官方 currentwar 原始响应
由 ``CocSyncService`` 获取后传入这里，转换成 API 和小程序共同使用的稳定结构。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from modules.coc_sync.official.mapper import normalize_tag


ACTIVE_STATES = {"preparation", "inWar", "warEnded"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _tag(value: Any) -> str | None:
    return normalize_tag(value) if value else None


def _base(clan: dict, synced_at: str | None) -> dict:
    return {
        "clan_tag": _tag(clan.get("tag")),
        "clan_name": clan.get("name") or clan.get("tag"),
        "category": clan.get("category", "normal"),
        "status": "not_in_war",
        "state": "notInWar",
        "war_type": None,
        "team_size": 0,
        "attacks_per_member": 0,
        "preparation_start_time": None,
        "start_time": None,
        "end_time": None,
        "result": "pending",
        "clan": {
            "tag": _tag(clan.get("tag")),
            "name": clan.get("name") or clan.get("tag"),
            "attacks": 0,
            "total_attacks": 0,
            "stars": 0,
            "destruction_percentage": 0.0,
        },
        "opponent": None,
        "rows": [],
        "error": None,
        "synced_at": synced_at or _now_iso(),
    }


def failed_current_war(clan: dict, error: str, synced_at: str | None = None) -> dict:
    """构造单个部落同步失败结果，供调度器隔离错误。"""
    result = _base(clan, synced_at)
    result.update({"status": "error", "state": "error", "error": str(error)})
    return result


def _side_summary(side: dict, team_size: int, attacks_per_member: int) -> dict:
    members = side.get("members") or []
    computed_attacks = sum(len(member.get("attacks") or []) for member in members)
    return {
        "tag": _tag(side.get("tag")),
        "name": side.get("name") or side.get("tag") or "-",
        "attacks": _int(side.get("attacks"), computed_attacks),
        "total_attacks": team_size * attacks_per_member,
        "stars": _int(side.get("stars")),
        "destruction_percentage": _float(side.get("destructionPercentage")),
    }


def _attack_view(attack: dict, defender_positions: dict[str, int]) -> dict:
    return {
        "attacker_tag": _tag(attack.get("attackerTag")),
        "defender_tag": _tag(attack.get("defenderTag")),
        "stars": _int(attack.get("stars")),
        "destruction_percentage": _float(attack.get("destructionPercentage")),
        "order": _int(attack.get("order"), 999999),
        "target_position": defender_positions.get(_tag(attack.get("defenderTag"))),
    }


def _member_view(
    member: dict,
    defender_positions: dict[str, int],
    attacker_positions: dict[str, int],
    incoming_attacks: list[dict],
) -> dict:
    member_tag = _tag(member.get("tag"))
    attacks = sorted(
        (_attack_view(attack, defender_positions) for attack in (member.get("attacks") or [])),
        key=lambda attack: attack["order"],
    )[:2]

    incoming = [
        attack for attack in incoming_attacks
        if _tag(attack.get("defenderTag")) == member_tag
    ]
    incoming.sort(key=lambda attack: _int(attack.get("order"), 999999))
    best_raw = max(
        incoming,
        key=lambda attack: (
            _int(attack.get("stars")),
            _float(attack.get("destructionPercentage")),
            -_int(attack.get("order"), 999999),
        ),
        default=None,
    )
    best = None
    if best_raw:
        best = {
            "attacker_tag": _tag(best_raw.get("attackerTag")),
            "stars": _int(best_raw.get("stars")),
            "destruction_percentage": _float(best_raw.get("destructionPercentage")),
            "order": _int(best_raw.get("order"), 999999),
            "attacker_position": attacker_positions.get(_tag(best_raw.get("attackerTag"))),
        }

    computed_total = len(incoming)
    official_total = _int(member.get("opponentAttacks"), computed_total)
    return {
        "player_tag": member_tag,
        "name": member.get("name") or "-",
        "town_hall_level": _int(member.get("townhallLevel")),
        "position": _int(member.get("mapPosition")),
        "attacks": attacks,
        "defense": {
            "best_attack": best,
            "three_star_count": sum(1 for attack in incoming if _int(attack.get("stars")) == 3),
            "total_attacks": computed_total,
            "official_total_attacks": official_total,
            "count_mismatch": official_total != computed_total,
        },
    }


def _result(state: str, clan: dict, opponent: dict) -> str:
    if state == "preparation":
        return "pending"
    left = (clan["stars"], clan["destruction_percentage"])
    right = (opponent["stars"], opponent["destruction_percentage"])
    if left == right:
        return "tied"
    won = left > right
    if state == "warEnded":
        return "victory" if won else "defeat"
    return "leading" if won else "losing"


def normalize_current_war(raw: dict | None, clan: dict, synced_at: str | None = None) -> dict:
    """把官方 currentwar 响应转换为稳定的当前战争模型。"""
    result = _base(clan, synced_at)
    raw = raw or {}
    state = raw.get("state") or "notInWar"
    if state not in ACTIVE_STATES:
        return result

    team_size = _int(raw.get("teamSize"))
    attacks_per_member = _int(raw.get("attacksPerMember"))
    war_type = str(raw.get("type") or "").lower() or None
    result.update({
        "state": state,
        "war_type": war_type,
        "team_size": team_size,
        "attacks_per_member": attacks_per_member,
        "preparation_start_time": raw.get("preparationStartTime"),
        "start_time": raw.get("startTime"),
        "end_time": raw.get("endTime"),
    })

    if war_type == "cwl" or attacks_per_member == 1:
        result["status"] = "cwl"
        return result

    configured_tag = _tag(clan.get("tag"))
    first = raw.get("clan") or {}
    second = raw.get("opponent") or {}
    if _tag(second.get("tag")) == configured_tag and _tag(first.get("tag")) != configured_tag:
        first, second = second, first

    clan_summary = _side_summary(first, team_size, attacks_per_member)
    opponent_summary = _side_summary(second, team_size, attacks_per_member)
    result.update({
        "status": {"preparation": "preparation", "inWar": "in_war", "warEnded": "war_ended"}[state],
        "clan": clan_summary,
        "opponent": opponent_summary,
        "result": _result(state, clan_summary, opponent_summary),
    })

    clan_members = first.get("members") or []
    opponent_members = second.get("members") or []
    clan_by_position = {_int(m.get("mapPosition")): m for m in clan_members}
    opponent_by_position = {_int(m.get("mapPosition")): m for m in opponent_members}
    clan_positions = {_tag(m.get("tag")): _int(m.get("mapPosition")) for m in clan_members}
    opponent_positions = {_tag(m.get("tag")): _int(m.get("mapPosition")) for m in opponent_members}
    clan_attacks = [attack for member in clan_members for attack in (member.get("attacks") or [])]
    opponent_attacks = [attack for member in opponent_members for attack in (member.get("attacks") or [])]
    row_count = max(
        team_size,
        max(clan_by_position.keys(), default=0),
        max(opponent_by_position.keys(), default=0),
    )
    result["rows"] = [
        {
            "position": position,
            "clan_member": _member_view(
                clan_by_position[position], opponent_positions, opponent_positions, opponent_attacks
            ) if position in clan_by_position else None,
            "opponent_member": _member_view(
                opponent_by_position[position], clan_positions, clan_positions, clan_attacks
            ) if position in opponent_by_position else None,
        }
        for position in range(1, row_count + 1)
    ]
    return result


def current_war_summary(item: dict) -> dict:
    """去掉成员宽表，生成汇总页负载。"""
    return {key: value for key, value in item.items() if key != "rows"}
