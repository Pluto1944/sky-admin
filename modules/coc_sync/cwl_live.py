"""CWL 实时联赛组、战斗日和总览统计的纯转换层。

本模块不访问网络、不读写数据库。调用方负责取得 leaguegroup / league war 原始
响应并传入，模块只负责规范化、方向校正和派生统计。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from modules.coc_sync.official.mapper import normalize_tag


ACTIVE_WAR_STATES = {"preparation", "inWar", "warEnded"}
PLACEHOLDER_WAR_TAGS = {None, "", "#0", "0"}
WIN_BONUS_STARS = 10


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


def _town_hall(member: dict) -> int:
    return _int(member.get("townhallLevel", member.get("townHallLevel")))


def _war_tag(value: Any) -> str | None:
    tag = _tag(value)
    return None if tag in PLACEHOLDER_WAR_TAGS else tag


def normalize_cwl_season(value: Any) -> str | None:
    """把官方 ``YYYY-MM-DD`` 或历史 ``YYYY-MM`` 赛季统一为月份。"""
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return text or None


def normalize_cwl_group(raw: dict, team: dict, synced_at: str | None = None) -> dict:
    """规范化官方 leaguegroup 响应，同时保留月度队伍身份。"""
    clans = []
    for clan in raw.get("clans") or []:
        members = [
            {
                "player_tag": _tag(member.get("tag")),
                "name": member.get("name") or "-",
                "town_hall_level": _town_hall(member),
            }
            for member in (clan.get("members") or [])
        ]
        clans.append({
            "tag": _tag(clan.get("tag")),
            "name": clan.get("name") or clan.get("tag") or "-",
            "clan_level": _int(clan.get("clanLevel")),
            "badge_urls": clan.get("badgeUrls") or {},
            "members": members,
        })

    rounds = []
    for index, item in enumerate(raw.get("rounds") or [], start=1):
        rounds.append({
            "round": index,
            "war_tags": [tag for tag in (_war_tag(v) for v in (item.get("warTags") or [])) if tag],
        })

    clan_tag = _tag(team.get("clan_tag") or team.get("tag"))
    return {
        "period": team.get("period"),
        "team_index": _int(team.get("team_index")),
        "team_alias": team.get("team_alias") or team.get("name") or "-",
        "team_name": team.get("team_name") or team.get("team_alias") or clan_tag,
        "clan_tag": clan_tag,
        "category": team.get("category") or "combat",
        "member_count": _int(team.get("member_count")),
        "league_level": team.get("league_level") or "-",
        "season": normalize_cwl_season(raw.get("season")),
        "state": raw.get("state") or "unknown",
        "clans": clans,
        "rounds": rounds,
        "synced_at": synced_at or _now_iso(),
    }


def _normalize_attack(attack: dict) -> dict:
    return {
        "attacker_tag": _tag(attack.get("attackerTag")),
        "defender_tag": _tag(attack.get("defenderTag")),
        "stars": _int(attack.get("stars")),
        "destruction_percentage": _float(attack.get("destructionPercentage")),
        "order": _int(attack.get("order"), 999999),
        "duration": _int(attack.get("duration")),
    }


def _normalize_side(side: dict, team_size: int) -> dict:
    members = []
    for member in side.get("members") or []:
        attacks = sorted(
            (_normalize_attack(attack) for attack in (member.get("attacks") or [])),
            key=lambda item: item["order"],
        )
        members.append({
            "player_tag": _tag(member.get("tag")),
            "name": member.get("name") or "-",
            "town_hall_level": _town_hall(member),
            "position": _int(member.get("mapPosition")),
            "opponent_attacks": _int(member.get("opponentAttacks")),
            "attacks": attacks,
        })
    computed_attacks = sum(len(member["attacks"]) for member in members)
    return {
        "tag": _tag(side.get("tag")),
        "name": side.get("name") or side.get("tag") or "-",
        "clan_level": _int(side.get("clanLevel")),
        "attacks": _int(side.get("attacks"), computed_attacks),
        "total_attacks": team_size,
        "stars": _int(side.get("stars")),
        "destruction_percentage": _float(side.get("destructionPercentage")),
        "members": members,
    }


def normalize_cwl_war(raw: dict, war_tag: str, synced_at: str | None = None) -> dict:
    """规范化一场 CWL 战争，不预设哪一方是自有部落。"""
    state = raw.get("state") or "notInWar"
    team_size = _int(raw.get("teamSize"))
    return {
        "war_tag": _war_tag(war_tag),
        "state": state,
        "status": {
            "preparation": "preparation",
            "inWar": "in_war",
            "warEnded": "war_ended",
            "notInWar": "not_started",
        }.get(state, "unknown"),
        "team_size": team_size,
        "attacks_per_member": _int(raw.get("attacksPerMember"), 1),
        "preparation_start_time": raw.get("preparationStartTime"),
        "start_time": raw.get("startTime"),
        "end_time": raw.get("endTime"),
        "clan": _normalize_side(raw.get("clan") or {}, team_size),
        "opponent": _normalize_side(raw.get("opponent") or {}, team_size),
        "synced_at": synced_at or _now_iso(),
    }


def group_war_tags(group: dict | None) -> list[str]:
    """按轮次顺序返回去重后的有效 warTag。"""
    seen = set()
    result = []
    for item in (group or {}).get("rounds") or []:
        for value in item.get("war_tags") or []:
            tag = _war_tag(value)
            if tag and tag not in seen:
                seen.add(tag)
                result.append(tag)
    return result


def _result(state: str, own: dict, opponent: dict) -> str:
    if state in {"preparation", "notInWar"}:
        return "pending"
    left = (own.get("stars", 0), own.get("destruction_percentage", 0))
    right = (opponent.get("stars", 0), opponent.get("destruction_percentage", 0))
    if left == right:
        return "tied"
    won = left > right
    if state == "warEnded":
        return "victory" if won else "defeat"
    return "leading" if won else "losing"


def _best_attack(attacks: list[dict]) -> dict | None:
    return max(
        attacks,
        key=lambda attack: (
            _int(attack.get("stars")),
            _float(attack.get("destruction_percentage")),
            -_int(attack.get("order"), 999999),
        ),
        default=None,
    )


def orient_cwl_war(war: dict, clan_tag: str) -> dict | None:
    """把战争方向校正到指定自有部落，并生成战斗日对位行。"""
    normalized_tag = _tag(clan_tag)
    first = war.get("clan") or {}
    second = war.get("opponent") or {}
    if first.get("tag") == normalized_tag:
        own, opponent = first, second
    elif second.get("tag") == normalized_tag:
        own, opponent = second, first
    else:
        return None

    own_members = {member.get("position"): member for member in own.get("members") or []}
    opponent_members = {member.get("position"): member for member in opponent.get("members") or []}
    own_positions = {member.get("player_tag"): member.get("position") for member in own.get("members") or []}
    opponent_positions = {
        member.get("player_tag"): member.get("position") for member in opponent.get("members") or []
    }
    own_attacks = [attack for member in own.get("members") or [] for attack in member.get("attacks") or []]
    opponent_attacks = [
        attack for member in opponent.get("members") or [] for attack in member.get("attacks") or []
    ]

    def member_view(member: dict | None, targets: dict, incoming: list[dict], attackers: dict) -> dict | None:
        if not member:
            return None
        attacks = []
        for attack in member.get("attacks") or []:
            attacks.append({**attack, "target_position": targets.get(attack.get("defender_tag"))})
        received = [attack for attack in incoming if attack.get("defender_tag") == member.get("player_tag")]
        best = _best_attack(received)
        defense = None
        if best:
            defense = {**best, "attacker_position": attackers.get(best.get("attacker_tag"))}
        return {
            "player_tag": member.get("player_tag"),
            "name": member.get("name"),
            "town_hall_level": member.get("town_hall_level"),
            "position": member.get("position"),
            "attack": attacks[0] if attacks else None,
            "defense": defense,
        }

    row_count = max(
        _int(war.get("team_size")),
        max(own_members.keys(), default=0),
        max(opponent_members.keys(), default=0),
    )
    rows = [
        {
            "position": position,
            "clan_member": member_view(
                own_members.get(position), opponent_positions, opponent_attacks, opponent_positions
            ),
            "opponent_member": member_view(
                opponent_members.get(position), own_positions, own_attacks, own_positions
            ),
        }
        for position in range(1, row_count + 1)
    ]
    return {
        "war_tag": war.get("war_tag"),
        "state": war.get("state"),
        "status": war.get("status"),
        "team_size": war.get("team_size", 0),
        "preparation_start_time": war.get("preparation_start_time"),
        "start_time": war.get("start_time"),
        "end_time": war.get("end_time"),
        "result": _result(war.get("state"), own, opponent),
        "clan": {key: value for key, value in own.items() if key != "members"},
        "opponent": {key: value for key, value in opponent.items() if key != "members"},
        "rows": rows,
        "synced_at": war.get("synced_at"),
    }


def _find_round_war(round_item: dict, wars_by_tag: dict[str, dict], clan_tag: str) -> tuple[str | None, dict | None]:
    for war_tag in round_item.get("war_tags") or []:
        war = wars_by_tag.get(war_tag)
        if war and orient_cwl_war(war, clan_tag):
            return war_tag, war
    return None, None


def build_team_rounds(group: dict, wars_by_tag: dict[str, dict], clan_tag: str) -> list[dict]:
    """生成指定部落的逐轮战争；找不到时保留轮次占位。"""
    rounds = []
    for item in group.get("rounds") or []:
        war_tag, war = _find_round_war(item, wars_by_tag, clan_tag)
        if war:
            oriented = orient_cwl_war(war, clan_tag)
            rounds.append({"round": item["round"], **oriented})
        else:
            rounds.append({
                "round": item["round"],
                "war_tag": war_tag,
                "state": "notInWar",
                "status": "unavailable" if item.get("war_tags") else "bye",
                "result": "pending",
                "clan": None,
                "opponent": None,
                "rows": [],
                "start_time": None,
                "end_time": None,
                "synced_at": None,
            })
    return rounds


def build_cwl_attack_reminder(group: dict, wars_by_tag: dict[str, dict]) -> dict:
    """生成单支联赛队伍的当前战斗日提醒。

    只有当前实际上阵的成员才参与“未出刀”判定；准备日和已结束
    轮次不产生未出刀成员。
    """
    clan_tag = group.get("clan_tag")
    rounds = build_team_rounds(group, wars_by_tag, clan_tag)
    active = next((item for item in rounds if item.get("status") == "in_war"), None)
    preparing = next((item for item in rounds if item.get("status") == "preparation"), None)
    selected = active or preparing

    if active:
        status = "in_war"
    elif preparing:
        status = "preparation"
    elif rounds and all(item.get("status") in {"war_ended", "bye"} for item in rounds):
        status = "ended"
    elif group.get("state") == "ended":
        status = "ended"
    else:
        status = "waiting"

    members = []
    pending_members = []
    if active:
        members = [
            row.get("clan_member")
            for row in active.get("rows") or []
            if row.get("clan_member")
        ]
        pending_members = [
            {
                "player_tag": member.get("player_tag"),
                "name": member.get("name"),
                "town_hall_level": member.get("town_hall_level"),
                "position": member.get("position"),
            }
            for member in members
            if not member.get("attack")
        ]
        pending_members.sort(key=lambda member: member.get("position") or 999)

    team_size = int((selected or {}).get("team_size") or len(members) or 0)
    return {
        "period": group.get("period"),
        "team_index": group.get("team_index"),
        "team_alias": group.get("team_alias"),
        "team_name": group.get("team_name") or group.get("team_alias") or clan_tag,
        "clan_tag": clan_tag,
        "category": group.get("category"),
        "league_level": group.get("league_level"),
        "status": status,
        "round": (selected or {}).get("round"),
        "opponent": (selected or {}).get("opponent"),
        "start_time": (selected or {}).get("start_time"),
        "end_time": (selected or {}).get("end_time"),
        "team_size": team_size,
        "attacked_count": len(members) - len(pending_members) if active else 0,
        "pending_count": len(pending_members),
        "pending_members": pending_members,
        "updated_at": (selected or {}).get("synced_at") or group.get("synced_at"),
    }


def _current_round(rounds: list[dict]) -> int | None:
    for status in ("in_war", "preparation"):
        found = next((item for item in rounds if item.get("status") == status), None)
        if found:
            return found["round"]
    ended = [item["round"] for item in rounds if item.get("status") == "war_ended"]
    if ended:
        next_round = next(
            (item["round"] for item in rounds if item["round"] > max(ended) and item.get("status") != "bye"),
            None,
        )
        return next_round or max(ended)
    return rounds[0]["round"] if rounds else None


def _standings(group: dict, wars_by_tag: dict[str, dict]) -> list[dict]:
    round_count = len(group.get("rounds") or [])
    entries = {
        clan.get("tag"): {
            "clan_tag": clan.get("tag"),
            "clan_name": clan.get("name"),
            "clan_level": clan.get("clan_level", 0),
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "attack_stars": 0,
            "league_stars": 0,
            "total_destruction": 0.0,
            "rounds": [{"round": index, "status": "not_started"} for index in range(1, round_count + 1)],
        }
        for clan in group.get("clans") or []
        if clan.get("tag")
    }

    for round_item in group.get("rounds") or []:
        round_index = round_item["round"]
        for war_tag in round_item.get("war_tags") or []:
            war = wars_by_tag.get(war_tag)
            if not war or war.get("state") not in ACTIVE_WAR_STATES:
                continue
            left = war.get("clan") or {}
            right = war.get("opponent") or {}
            if left.get("tag") not in entries or right.get("tag") not in entries:
                continue
            left_result = _result(war.get("state"), left, right)
            right_result = _result(war.get("state"), right, left)
            for side, other, result in ((left, right, left_result), (right, left, right_result)):
                entry = entries[side["tag"]]
                started = war.get("state") != "preparation"
                if started:
                    entry["attack_stars"] += side.get("stars", 0)
                    entry["total_destruction"] += side.get("destruction_percentage", 0)
                if war.get("state") == "warEnded":
                    if result == "victory":
                        entry["wins"] += 1
                    elif result == "defeat":
                        entry["losses"] += 1
                    else:
                        entry["ties"] += 1
                entry["rounds"][round_index - 1] = {
                    "round": round_index,
                    "status": war.get("status"),
                    "result": result,
                    "team_size": war.get("team_size", 0),
                    "attacks": side.get("attacks", 0),
                    "stars": side.get("stars", 0),
                    "destruction_percentage": side.get("destruction_percentage", 0),
                    "opponent_tag": other.get("tag"),
                    "opponent_name": other.get("name"),
                }

    for entry in entries.values():
        entry["league_stars"] = entry["attack_stars"] + entry["wins"] * WIN_BONUS_STARS
        started = sum(
            item.get("status") in {"in_war", "war_ended"}
            for item in entry["rounds"]
        )
        entry["average_destruction"] = round(entry["total_destruction"] / started, 2) if started else 0.0

    ordered = sorted(
        entries.values(),
        key=lambda item: (-item["league_stars"], -item["total_destruction"], item["clan_tag"] or ""),
    )
    for index, entry in enumerate(ordered, start=1):
        entry["rank"] = index
    return ordered


def _town_hall_overview(group: dict) -> dict:
    levels = sorted(
        {
            member.get("town_hall_level", 0)
            for clan in group.get("clans") or []
            for member in clan.get("members") or []
            if member.get("town_hall_level")
        },
        reverse=True,
    )
    rows = []
    for clan in group.get("clans") or []:
        counts = defaultdict(int)
        for member in clan.get("members") or []:
            counts[member.get("town_hall_level", 0)] += 1
        rows.append({
            "clan_level": clan.get("clan_level", 0),
            "clan_name": clan.get("name"),
            "clan_tag": clan.get("tag"),
            "total": len(clan.get("members") or []),
            "counts": {str(level): counts[level] for level in levels},
        })
    return {"levels": levels, "rows": rows}


def _selected_side(war: dict, clan_tag: str) -> tuple[dict | None, dict | None]:
    tag = _tag(clan_tag)
    left, right = war.get("clan") or {}, war.get("opponent") or {}
    if left.get("tag") == tag:
        return left, right
    if right.get("tag") == tag:
        return right, left
    return None, None


def _member_stats(group: dict, wars_by_tag: dict[str, dict], clan_tag: str) -> tuple[list[dict], list[dict]]:
    round_count = len(group.get("rounds") or [])
    offense: dict[str, dict] = {}
    defense: dict[str, dict] = {}

    def ensure(member: dict) -> tuple[dict, dict]:
        tag = member.get("player_tag")
        if tag not in offense:
            base_rounds = [{"round": index, "status": "not_participated"} for index in range(1, round_count + 1)]
            offense[tag] = {
                "player_tag": tag,
                "name": member.get("name"),
                "town_hall_level": member.get("town_hall_level", 0),
                "total_stars": 0,
                "total_destruction": 0.0,
                "attacks": 0,
                "matchup_difference": 0,
                "appearances": 0,
                "rounds": [dict(item) for item in base_rounds],
            }
            defense[tag] = {
                "player_tag": tag,
                "name": member.get("name"),
                "town_hall_level": member.get("town_hall_level", 0),
                "last_position": member.get("position"),
                "appearances": 0,
                "saved_stars": 0,
                "saved_destruction": 0.0,
                "successful_defenses": 0,
                "rounds": [dict(item) for item in base_rounds],
            }
        return offense[tag], defense[tag]

    for round_item in group.get("rounds") or []:
        round_index = round_item["round"]
        _war_tag_value, war = _find_round_war(round_item, wars_by_tag, clan_tag)
        if not war or war.get("state") not in {"inWar", "warEnded"}:
            continue
        own, opponent = _selected_side(war, clan_tag)
        if not own or not opponent:
            continue
        opponent_positions = {
            member.get("player_tag"): member.get("position") for member in opponent.get("members") or []
        }
        incoming = [
            attack for member in opponent.get("members") or [] for attack in member.get("attacks") or []
        ]
        for member in own.get("members") or []:
            off, deff = ensure(member)
            off["appearances"] += 1
            deff["appearances"] += 1
            deff["last_position"] = member.get("position")

            attacks = member.get("attacks") or []
            if attacks:
                attack = attacks[0]
                target = opponent_positions.get(attack.get("defender_tag"))
                difference = (member.get("position") or 0) - (target or member.get("position") or 0)
                off["total_stars"] += attack.get("stars", 0)
                off["total_destruction"] += attack.get("destruction_percentage", 0)
                off["attacks"] += 1
                off["matchup_difference"] += difference
                off["rounds"][round_index - 1] = {
                    "round": round_index,
                    "status": "attacked",
                    "stars": attack.get("stars", 0),
                    "destruction_percentage": attack.get("destruction_percentage", 0),
                    "target_position": target,
                    "matchup_difference": difference,
                }
            else:
                off["rounds"][round_index - 1] = {"round": round_index, "status": "not_attacked"}

            received = [attack for attack in incoming if attack.get("defender_tag") == member.get("player_tag")]
            best = _best_attack(received)
            if best:
                deff["saved_stars"] += 3 - best.get("stars", 0)
                deff["saved_destruction"] += 100 - best.get("destruction_percentage", 0)
                if best.get("stars", 0) < 3:
                    deff["successful_defenses"] += 1
                deff["rounds"][round_index - 1] = {
                    "round": round_index,
                    "status": "defended",
                    "stars": best.get("stars", 0),
                    "destruction_percentage": best.get("destruction_percentage", 0),
                }
            else:
                deff["saved_stars"] += 3
                deff["saved_destruction"] += 100
                deff["rounds"][round_index - 1] = {"round": round_index, "status": "unattacked"}

    offense_rows = sorted(
        offense.values(),
        key=lambda item: (-item["total_stars"], -item["total_destruction"], item["player_tag"] or ""),
    )
    defense_rows = sorted(
        defense.values(),
        key=lambda item: (-item["saved_stars"], -item["saved_destruction"], item["player_tag"] or ""),
    )
    for index, item in enumerate(offense_rows, start=1):
        item["rank"] = index
        item["total_destruction"] = round(item["total_destruction"], 2)
    for index, item in enumerate(defense_rows, start=1):
        item["rank"] = index
        item["saved_destruction"] = round(item["saved_destruction"], 2)
    return offense_rows, defense_rows


def build_cwl_dashboard(group: dict, wars_by_tag: dict[str, dict]) -> dict:
    """为 group 中的自有部落生成完整详情和四类总览统计。"""
    clan_tag = group.get("clan_tag")
    rounds = build_team_rounds(group, wars_by_tag, clan_tag)
    standings = _standings(group, wars_by_tag)
    own_standing = next((item for item in standings if item.get("clan_tag") == clan_tag), None)
    offense, defense = _member_stats(group, wars_by_tag, clan_tag)
    current_round = _current_round(rounds)
    timestamps = [group.get("synced_at")]
    timestamps.extend(item.get("synced_at") for item in rounds)
    updated_at = max((value for value in timestamps if value), default=None)

    active = next((item for item in rounds if item.get("status") == "in_war"), None)
    preparing = next((item for item in rounds if item.get("status") == "preparation"), None)
    if active:
        status = "active"
    elif preparing:
        status = "preparation"
    elif rounds and all(item.get("status") in {"war_ended", "bye"} for item in rounds):
        status = "ended"
    elif group.get("state") == "ended":
        status = "ended"
    else:
        status = "waiting"

    summary = {
        "period": group.get("period"),
        "team_index": group.get("team_index"),
        "team_alias": group.get("team_alias"),
        "team_name": group.get("team_name"),
        "clan_tag": clan_tag,
        "category": group.get("category"),
        "member_count": group.get("member_count"),
        "league_level": group.get("league_level"),
        "season": group.get("season"),
        "status": status,
        "current_round": current_round,
        "current_result": active.get("result") if active else None,
        "rank": own_standing.get("rank") if own_standing else None,
        "wins": own_standing.get("wins", 0) if own_standing else 0,
        "losses": own_standing.get("losses", 0) if own_standing else 0,
        "ties": own_standing.get("ties", 0) if own_standing else 0,
        "attack_stars": own_standing.get("attack_stars", 0) if own_standing else 0,
        "league_stars": own_standing.get("league_stars", 0) if own_standing else 0,
        "average_destruction": own_standing.get("average_destruction", 0) if own_standing else 0,
        "synced_at": updated_at,
    }
    return {
        "period": group.get("period"),
        "team": {
            "team_index": group.get("team_index"),
            "team_alias": group.get("team_alias"),
            "team_name": group.get("team_name"),
            "clan_tag": clan_tag,
            "category": group.get("category"),
            "member_count": group.get("member_count"),
            "league_level": group.get("league_level"),
        },
        "season": group.get("season"),
        "group_state": group.get("state"),
        "status": status,
        "current_round": current_round,
        "summary": summary,
        "rounds": rounds,
        "overview": {
            "town_halls": _town_hall_overview(group),
            "standings": {"round_count": len(group.get("rounds") or []), "rows": standings},
            "offense": {"round_count": len(group.get("rounds") or []), "rows": offense},
            "defense": {"round_count": len(group.get("rounds") or []), "rows": defense},
        },
        "updated_at": updated_at,
        "error": None,
    }
