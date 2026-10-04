"""成员页战斗与贡献摘要。

战争转换函数只依赖标准化 current-war 数据；数据库函数只读写本地事实与缓存，
不会在 API 请求路径访问外部服务。
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from modules.coc_sync.official.mapper import normalize_tag
from modules.coc_sync.war_history import war_history_key


BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class MemberWarFactChanges:
    """一场战争物化后实际变化的成员事实。

    ``changed_player_tags`` 驱动成员战斗摘要重算；
    ``activity_player_tags`` 只表示本次观察到新增出刀，供活动时间记录使用。
    两者不能混用：首次归档时成员事实都是新增的，但不应把整场结束战争
    误判为本轮刚发生的出刀。
    """

    changed_player_tags: frozenset[str]
    activity_player_tags: frozenset[str]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z") and "T" in text and "-" not in text[:8]:
            return datetime.strptime(text, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(value: str | None) -> str | None:
    parsed = parse_coc_time(value)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds") if parsed else None


def previous_complete_periods(now: datetime, count: int = 3) -> list[str]:
    local = now.astimezone(BUSINESS_TZ)
    year, month = local.year, local.month
    result = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year -= 1
            month = 12
        result.append(f"{year:04d}-{month:02d}")
    return result


def _attack_identity(attack: dict) -> tuple:
    """为规范化攻击构造稳定身份；``order`` 为主，其他字段防御异常重复。"""
    return (
        _int(attack.get("order")) or 999999,
        normalize_tag(attack.get("attacker_tag")) or "",
        normalize_tag(attack.get("defender_tag")) or "",
        _int(attack.get("target_position")),
    )


def _effective_attack_identities(item: dict, side: str) -> set[tuple]:
    """返回指定阵营满星前（含达成满星的一刀）的攻击身份。

    满星进度按每个目标的最高星数累积，而非累加补刀的原始星数。
    """
    member_key = "clan_member" if side == "clan" else "opponent_member"
    attacks = []
    for row in item.get("rows") or []:
        member = row.get(member_key) or {}
        attacks.extend(member.get("attacks") or [])
    attacks.sort(key=lambda attack: _attack_identity(attack)[0])
    max_stars = _int(item.get("team_size")) * 3
    if max_stars <= 0:
        return {_attack_identity(attack) for attack in attacks}

    best_by_target: dict[object, int] = {}
    total = 0
    included: set[tuple] = set()
    for attack in attacks:
        if total >= max_stars:
            break
        included.add(_attack_identity(attack))
        target = attack.get("target_position") or attack.get("defender_tag")
        stars = _int(attack.get("stars"))
        before = best_by_target.get(target, 0)
        if stars > before:
            total += stars - before
            best_by_target[target] = stars
    return included


def _attacks_for_member(item: dict, side: str, player_tag: str) -> list[dict]:
    member_key = "clan_member" if side == "clan" else "opponent_member"
    normalized = normalize_tag(player_tag)
    result = []
    for row in item.get("rows") or []:
        member = row.get(member_key) or {}
        if normalize_tag(member.get("player_tag")) == normalized:
            result.extend(member.get("attacks") or [])
    return result


def _incoming_attacks(item: dict, player_tag: str) -> list[dict]:
    normalized = normalize_tag(player_tag)
    result = []
    for row in item.get("rows") or []:
        member = row.get("opponent_member") or {}
        for attack in member.get("attacks") or []:
            if normalize_tag(attack.get("defender_tag")) == normalized:
                result.append(attack)
    return result


def materialize_war_member_facts(
    conn: sqlite3.Connection, item: dict, updated_at: str | None = None,
) -> MemberWarFactChanges:
    """幂等固化一场自有部落普通战的逐玩家事实及变化集合。"""
    key = war_history_key(item)
    clan_tag = normalize_tag(item.get("clan_tag"))
    end_time = _iso(item.get("end_time"))
    if not key or not clan_tag or not end_time:
        return MemberWarFactChanges(frozenset(), frozenset())
    if item.get("war_type") == "cwl" or _int(item.get("attacks_per_member")) == 1:
        return MemberWarFactChanges(frozenset(), frozenset())

    timestamp = updated_at or item.get("synced_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    offense_effective = _effective_attack_identities(item, "clan")
    defense_effective = _effective_attack_identities(item, "opponent")
    changed_tags: set[str] = set()
    activity_tags: set[str] = set()
    for row in item.get("rows") or []:
        member = row.get("clan_member") or {}
        player_tag = normalize_tag(member.get("player_tag"))
        if not player_tag:
            continue
        raw_attacks = _attacks_for_member(item, "clan", player_tag)
        effective = [attack for attack in raw_attacks if _attack_identity(attack) in offense_effective]
        raw_defense = _incoming_attacks(item, player_tag)
        effective_defense = [
            attack for attack in raw_defense if _attack_identity(attack) in defense_effective
        ]
        available_attacks = _int(item.get("attacks_per_member"))
        actual_attacks = len(effective)
        observed_attacks = len(raw_attacks)
        three_stars = sum(1 for attack in effective if _int(attack.get("stars")) == 3)
        old = conn.execute(
            """SELECT end_time, status, category, available_attacks, actual_attacks,
                      observed_attacks, three_stars, town_hall_level_at_war, map_position,
                      offense_observed_attacks, offense_effective_attacks,
                      offense_effective_3stars, defense_observed_attacks,
                      defense_effective_attacks, defense_effective_3stars, metric_version
               FROM member_war_facts
               WHERE clan_tag = ? AND war_key = ? AND player_tag = ?""",
            (clan_tag, key, player_tag),
        ).fetchone()
        new_values = (
            end_time, item.get("status") or "", item.get("category") or "normal",
            available_attacks, actual_attacks, observed_attacks, three_stars,
            _int(member.get("town_hall_level")), _int(member.get("position")),
            observed_attacks, actual_attacks, three_stars,
            len(raw_defense), len(effective_defense),
            sum(1 for attack in effective_defense if _int(attack.get("stars")) == 3),
            2,
        )
        old_values = tuple(old) if old is not None else None
        if old_values == new_values:
            continue
        if old is not None and observed_attacks > _int(old["observed_attacks"]):
            activity_tags.add(player_tag)
        conn.execute(
            """INSERT INTO member_war_facts
               (clan_tag, war_key, player_tag, end_time, status, category,
                available_attacks, actual_attacks, observed_attacks, three_stars,
                town_hall_level_at_war, map_position,
                offense_observed_attacks, offense_effective_attacks,
                offense_effective_3stars, defense_observed_attacks,
                defense_effective_attacks, defense_effective_3stars, metric_version, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(clan_tag, war_key, player_tag) DO UPDATE SET
                   end_time = excluded.end_time,
                   status = excluded.status,
                   category = excluded.category,
                   available_attacks = excluded.available_attacks,
                   actual_attacks = excluded.actual_attacks,
                   observed_attacks = excluded.observed_attacks,
                   three_stars = excluded.three_stars,
                   town_hall_level_at_war = excluded.town_hall_level_at_war,
                   map_position = excluded.map_position,
                   offense_observed_attacks = excluded.offense_observed_attacks,
                   offense_effective_attacks = excluded.offense_effective_attacks,
                   offense_effective_3stars = excluded.offense_effective_3stars,
                   defense_observed_attacks = excluded.defense_observed_attacks,
                   defense_effective_attacks = excluded.defense_effective_attacks,
                   defense_effective_3stars = excluded.defense_effective_3stars,
                   metric_version = excluded.metric_version,
                   updated_at = excluded.updated_at""",
            (
                clan_tag, key, player_tag, end_time, item.get("status") or "",
                item.get("category") or "normal", available_attacks,
                actual_attacks, observed_attacks, three_stars,
                _int(member.get("town_hall_level")), _int(member.get("position")),
                observed_attacks, actual_attacks, three_stars,
                len(raw_defense), len(effective_defense),
                sum(1 for attack in effective_defense if _int(attack.get("stars")) == 3),
                2,
                timestamp,
            ),
        )
        changed_tags.add(player_tag)
    return MemberWarFactChanges(frozenset(changed_tags), frozenset(activity_tags))


def materialize_cached_war_facts(conn: sqlite3.Connection) -> int:
    """为升级前已有的已结束战争补齐玩家事实；已有 war_key 不重复展开。"""
    rows = conn.execute(
        """SELECT clan_tag, war_key, data_json, updated_at
           FROM war_history_cache history
           WHERE status = 'war_ended'
             AND NOT EXISTS (
                 SELECT 1 FROM member_war_facts facts
                 WHERE facts.clan_tag = history.clan_tag
                   AND facts.war_key = history.war_key
                   AND facts.metric_version >= 2
             )"""
    ).fetchall()
    count = 0
    for row in rows:
        try:
            item = json.loads(row["data_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict):
            continue
        materialize_war_member_facts(conn, item, row["updated_at"])
        count += 1
    return count


def cwl_attack_counts(war: dict | None, own_clan_tags: set[str]) -> dict[str, int]:
    """提取一场标准化 CWL 战争中自有双方的逐玩家出刀数。"""
    own = {normalize_tag(tag) for tag in own_clan_tags if tag}
    result: dict[str, int] = {}
    for side_name in ("clan", "opponent"):
        side = (war or {}).get(side_name) or {}
        if normalize_tag(side.get("tag")) not in own:
            continue
        for member in side.get("members") or []:
            player_tag = normalize_tag(member.get("player_tag"))
            if player_tag:
                result[player_tag] = len(member.get("attacks") or [])
    return result


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def member_summary_map(conn: sqlite3.Connection, player_tags: list[str]) -> dict[str, dict]:
    """批量派生成员页四类摘要；不依赖可过期的战斗摘要缓存。"""
    if not player_tags:
        return {}
    result = {tag: {} for tag in player_tags}
    placeholders = ",".join("?" for _ in player_tags)

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).isoformat(timespec="seconds")
    timestamp = now.isoformat(timespec="seconds")
    war_rows = conn.execute(
        f"""SELECT facts.player_tag, facts.war_key, facts.actual_attacks, facts.three_stars,
                   facts.available_attacks, facts.updated_at
            FROM member_war_facts facts
            JOIN war_history_cache history
              ON history.clan_tag = facts.clan_tag AND history.war_key = facts.war_key
            WHERE facts.player_tag IN ({placeholders})
              AND facts.status = 'war_ended' AND history.status = 'war_ended'
              AND facts.end_time >= ? AND facts.end_time <= ?
            ORDER BY facts.player_tag, facts.end_time DESC, facts.war_key DESC""",
        (*player_tags, cutoff, timestamp),
    ).fetchall()
    wars_by_player: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in war_rows:
        if len(wars_by_player[row["player_tag"]]) < 15:
            wars_by_player[row["player_tag"]].append(row)

    periods = previous_complete_periods(now, 3)
    cwl_by_player: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "one_stars": 0, "three_stars": 0, "attacks": 0,
            "periods": set(), "updated_at": None,
        }
    )
    if periods:
        period_placeholders = ",".join("?" for _ in periods)
        cwl_rows = conn.execute(
            f"""SELECT lr.player_tag, lr.period, lr.offense_1stars,
                       lr.offense_3stars, lr.attacks, lr.fetched_at
                FROM league_results lr
                WHERE lr.player_tag IN ({placeholders}) AND lr.period IN ({period_placeholders})
                  AND EXISTS (
                      SELECT 1 FROM league_teams teams
                      WHERE teams.period = lr.period AND teams.clan_tag = lr.clan_tag
                  )""",
            (*player_tags, *periods),
        ).fetchall()
        for row in cwl_rows:
            entry = cwl_by_player[row["player_tag"]]
            entry["one_stars"] += _int(row["offense_1stars"])
            entry["three_stars"] += _int(row["offense_3stars"])
            entry["attacks"] += _int(row["attacks"])
            entry["periods"].add(row["period"])
            if row["fetched_at"] and (entry["updated_at"] is None or row["fetched_at"] > entry["updated_at"]):
                entry["updated_at"] = row["fetched_at"]

    for player_tag in player_tags:
        wars = wars_by_player[player_tag]
        war_attacks = sum(_int(row["actual_attacks"]) for row in wars)
        war_available = sum(_int(row["available_attacks"]) for row in wars)
        war_three_stars = sum(_int(row["three_stars"]) for row in wars)
        cwl = cwl_by_player[player_tag]
        war_updated = max((row["updated_at"] for row in wars if row["updated_at"]), default=None)
        updated = max((value for value in (war_updated, cwl["updated_at"]) if value), default=None)
        result[player_tag].update({
            "war_recent_15": {
                "war_count": len(wars), "three_stars": war_three_stars,
                "attacks": war_attacks, "available_attacks": war_available,
                "three_star_rate": _rate(war_three_stars, war_attacks),
                "attack_rate": _rate(war_attacks, war_available),
            },
            "cwl_recent_3m": {
                "periods": sorted(cwl["periods"], reverse=True),
                "one_stars": cwl["one_stars"],
                "three_stars": cwl["three_stars"], "attacks": cwl["attacks"],
                "one_star_rate": _rate(cwl["one_stars"], cwl["attacks"]),
                "three_star_rate": _rate(cwl["three_stars"], cwl["attacks"]),
            },
            "combat_updated_at": updated,
        })

    capital_rows = conn.execute(
        f"""SELECT * FROM capital_raid_member_results
            WHERE player_tag IN ({placeholders})
            ORDER BY player_tag, start_time DESC""",
        player_tags,
    ).fetchall()
    capital: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {
        "attacks": 0, "available": 0, "looted": 0,
    }))
    for row in capital_rows:
        period = capital[row["player_tag"]][row["start_time"]]
        period["attacks"] += _int(row["attacks"])
        period["available"] += _int(row["attack_limit"]) + _int(row["bonus_attack_limit"])
        period["looted"] += _int(row["capital_resources_looted"])
    for tag, seasons in capital.items():
        selected = [seasons[key] for key in sorted(seasons, reverse=True)[:4]]
        attacks = sum(item["attacks"] for item in selected)
        looted = sum(item["looted"] for item in selected)
        result[tag]["capital_recent_4w"] = {
            "weeks": len(selected), "looted": looted, "attacks": attacks,
            "available_attacks": sum(item["available"] for item in selected),
            "loot_per_attack": round(looted / attacks, 1) if attacks else None,
        }

    game_rows = conn.execute(
        f"""SELECT * FROM clan_games_member_snapshots
            WHERE player_tag IN ({placeholders})
            ORDER BY player_tag, period DESC""",
        player_tags,
    ).fetchall()
    games: dict[str, list] = defaultdict(list)
    for row in game_rows:
        games[row["player_tag"]].append(row)
    for tag, rows in games.items():
        latest = rows[0]
        complete = [row for row in rows if row["complete"] and row["points"] is not None][:3]
        result[tag]["clan_games"] = {
            "period": latest["period"], "points": latest["points"],
            "complete": bool(latest["complete"]),
            "average_3": round(sum(_int(row["points"]) for row in complete) / len(complete), 1) if complete else None,
            "period_count": len(complete),
        }
    return result
