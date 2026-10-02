"""成员页战斗与贡献摘要。

战争转换函数只依赖标准化 current-war 数据；数据库函数只读写本地事实与缓存，
不会在 API 请求路径访问外部服务。
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from modules.coc_sync.official.mapper import normalize_tag
from modules.coc_sync.war_history import war_history_key


BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


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


def _effective_attack_orders(item: dict) -> set[int]:
    """返回我方达到满星前（含达成满星的一刀）的全局攻击顺序。"""
    attacks = []
    for row in item.get("rows") or []:
        member = row.get("clan_member") or {}
        attacks.extend(member.get("attacks") or [])
    attacks.sort(key=lambda attack: _int(attack.get("order")) or 999999)
    max_stars = _int(item.get("team_size")) * 3
    if max_stars <= 0:
        return {_int(attack.get("order")) for attack in attacks}

    best_by_target: dict[Any, int] = {}
    total = 0
    included: set[int] = set()
    for attack in attacks:
        if total >= max_stars:
            break
        order = _int(attack.get("order"))
        included.add(order)
        target = attack.get("target_position") or attack.get("defender_tag")
        stars = _int(attack.get("stars"))
        before = best_by_target.get(target, 0)
        if stars > before:
            total += stars - before
            best_by_target[target] = stars
    return included


def materialize_war_member_facts(
    conn: sqlite3.Connection, item: dict, updated_at: str | None = None,
) -> list[str]:
    """幂等固化一场自有部落普通战的逐玩家事实，返回新增出刀的玩家。"""
    key = war_history_key(item)
    clan_tag = normalize_tag(item.get("clan_tag"))
    end_time = _iso(item.get("end_time"))
    if not key or not clan_tag or not end_time:
        return []
    if item.get("war_type") == "cwl" or _int(item.get("attacks_per_member")) == 1:
        return []

    timestamp = updated_at or item.get("synced_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    effective_orders = _effective_attack_orders(item)
    activity_tags: list[str] = []
    for row in item.get("rows") or []:
        member = row.get("clan_member") or {}
        player_tag = normalize_tag(member.get("player_tag"))
        if not player_tag:
            continue
        raw_attacks = member.get("attacks") or []
        effective = [attack for attack in raw_attacks if _int(attack.get("order")) in effective_orders]
        observed = len(raw_attacks)
        old = conn.execute(
            """SELECT observed_attacks FROM member_war_facts
               WHERE clan_tag = ? AND war_key = ? AND player_tag = ?""",
            (clan_tag, key, player_tag),
        ).fetchone()
        if old is not None and observed > _int(old["observed_attacks"]):
            activity_tags.append(player_tag)
        conn.execute(
            """INSERT INTO member_war_facts
               (clan_tag, war_key, player_tag, end_time, status, category,
                available_attacks, actual_attacks, observed_attacks, three_stars, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(clan_tag, war_key, player_tag) DO UPDATE SET
                   end_time = excluded.end_time,
                   status = excluded.status,
                   category = excluded.category,
                   available_attacks = excluded.available_attacks,
                   actual_attacks = excluded.actual_attacks,
                   observed_attacks = excluded.observed_attacks,
                   three_stars = excluded.three_stars,
                   updated_at = excluded.updated_at""",
            (
                clan_tag, key, player_tag, end_time, item.get("status") or "",
                item.get("category") or "normal", _int(item.get("attacks_per_member")),
                len(effective), observed,
                sum(1 for attack in effective if _int(attack.get("stars")) == 3),
                timestamp,
            ),
        )
    return activity_tags


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


def refresh_member_combat_stats(
    conn: sqlite3.Connection, now: datetime | None = None,
) -> int:
    """按玩家重建 90 天普通战与最近 3 个完整月 CWL 的轻量缓存。"""
    materialize_cached_war_facts(conn)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (current - timedelta(days=90)).isoformat(timespec="seconds")
    periods = previous_complete_periods(current, 3)
    player_tags = [row["player_tag"] for row in conn.execute("SELECT player_tag FROM accounts")]

    placeholders = ",".join("?" for _ in periods)
    cwl_by_player: dict[str, dict] = defaultdict(
        lambda: {"three_stars": 0, "attacks": 0, "clan_tags": set()}
    )
    if periods:
        rows = conn.execute(
            f"""SELECT lr.player_tag, lr.clan_tag, lr.offense_3stars, lr.attacks
                FROM league_results lr
                WHERE lr.period IN ({placeholders})
                  AND EXISTS (
                      SELECT 1 FROM league_teams lt
                      WHERE lt.period = lr.period AND lt.clan_tag = lr.clan_tag
                  )""",
            periods,
        ).fetchall()
        for row in rows:
            entry = cwl_by_player[row["player_tag"]]
            entry["three_stars"] += _int(row["offense_3stars"])
            entry["attacks"] += _int(row["attacks"])
            if row["clan_tag"]:
                entry["clan_tags"].add(normalize_tag(row["clan_tag"]))

    timestamp = current.isoformat(timespec="seconds")
    for player_tag in player_tags:
        wars = conn.execute(
            """SELECT clan_tag, war_key, three_stars, actual_attacks, available_attacks
               FROM member_war_facts
               WHERE player_tag = ? AND status = 'war_ended' AND end_time >= ? AND end_time <= ?
               ORDER BY end_time DESC, war_key DESC
               LIMIT 15""",
            (player_tag, cutoff, timestamp),
        ).fetchall()
        cwl = cwl_by_player[player_tag]
        conn.execute(
            """INSERT INTO member_combat_stats_cache
               (player_tag, war_window_start, war_count, war_three_stars, war_attacks,
                war_available_attacks, war_keys_json, war_clan_tags_json, cwl_periods_json,
                cwl_clan_tags_json, cwl_three_stars, cwl_attacks, status, error, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', NULL, ?)
               ON CONFLICT(player_tag) DO UPDATE SET
                   war_window_start = excluded.war_window_start,
                   war_count = excluded.war_count,
                   war_three_stars = excluded.war_three_stars,
                   war_attacks = excluded.war_attacks,
                   war_available_attacks = excluded.war_available_attacks,
                   war_keys_json = excluded.war_keys_json,
                   war_clan_tags_json = excluded.war_clan_tags_json,
                   cwl_periods_json = excluded.cwl_periods_json,
                   cwl_clan_tags_json = excluded.cwl_clan_tags_json,
                   cwl_three_stars = excluded.cwl_three_stars,
                   cwl_attacks = excluded.cwl_attacks,
                   status = 'success', error = NULL, updated_at = excluded.updated_at""",
            (
                player_tag, cutoff, len(wars),
                sum(_int(row["three_stars"]) for row in wars),
                sum(_int(row["actual_attacks"]) for row in wars),
                sum(_int(row["available_attacks"]) for row in wars),
                json.dumps([row["war_key"] for row in wars]),
                json.dumps(sorted({row["clan_tag"] for row in wars if row["clan_tag"]})),
                json.dumps(periods), json.dumps(sorted(cwl["clan_tags"])),
                cwl["three_stars"], cwl["attacks"], timestamp,
            ),
        )
    return len(player_tags)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def member_summary_map(conn: sqlite3.Connection, player_tags: list[str]) -> dict[str, dict]:
    """批量读取成员页四类摘要，避免逐成员 N+1 查询。"""
    if not player_tags:
        return {}
    result = {tag: {} for tag in player_tags}
    placeholders = ",".join("?" for _ in player_tags)

    for row in conn.execute(
        f"SELECT * FROM member_combat_stats_cache WHERE player_tag IN ({placeholders})",
        player_tags,
    ):
        war_attacks = _int(row["war_attacks"])
        war_available = _int(row["war_available_attacks"])
        cwl_attacks = _int(row["cwl_attacks"])
        result[row["player_tag"]].update({
            "war_recent_15": {
                "war_count": _int(row["war_count"]),
                "three_stars": _int(row["war_three_stars"]),
                "attacks": war_attacks,
                "available_attacks": war_available,
                "three_star_rate": _rate(_int(row["war_three_stars"]), war_attacks),
                "attack_rate": _rate(war_attacks, war_available),
            },
            "cwl_recent_3m": {
                "periods": json.loads(row["cwl_periods_json"] or "[]"),
                "three_stars": _int(row["cwl_three_stars"]),
                "attacks": cwl_attacks,
                "three_star_rate": _rate(_int(row["cwl_three_stars"]), cwl_attacks),
            },
            "combat_updated_at": row["updated_at"],
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
