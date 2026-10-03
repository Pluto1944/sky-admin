"""从完整 CWL 原始档案重建月度玩家战绩投影。"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from modules.coc_sync.cwl_live import group_war_tags
from modules.coc_sync.official.mapper import normalize_tag


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def group_raw_status(group: dict | None, wars: dict[str, dict]) -> str:
    """返回分组档案完整状态，不以联赛组 ``state`` 代替逐场校验。"""
    tags = group_war_tags(group)
    if not group or not tags:
        return "incomplete" if (group or {}).get("state") == "ended" else "collecting"
    for tag in tags:
        war = wars.get(normalize_tag(tag))
        if not war:
            return "incomplete" if group.get("state") == "ended" else "collecting"
        if war.get("status") != "war_ended":
            return "incomplete" if group.get("state") == "ended" else "collecting"
    return "complete"


def build_league_result_rows(
    group: dict, wars: dict[str, dict], team: dict,
) -> list[dict]:
    """纯函数：从一个完整分组提取本队逐玩家月度聚合。"""
    if group_raw_status(group, wars) != "complete":
        raise ValueError("CWL 分组原始档案尚不完整，拒绝生成 league_results")
    clan_tag = normalize_tag(team.get("clan_tag"))
    if not clan_tag:
        raise ValueError("联赛队伍缺少 clan_tag")

    players: dict[str, dict] = {}
    for war_tag in group_war_tags(group):
        war = wars[normalize_tag(war_tag)]
        clan = war.get("clan") or {}
        opponent = war.get("opponent") or {}
        if normalize_tag(clan.get("tag")) == clan_tag:
            own, enemy = clan, opponent
        elif normalize_tag(opponent.get("tag")) == clan_tag:
            own, enemy = opponent, clan
        else:
            # 联赛组每轮含全部对阵；这支队伍只应聚合自己参加的那一场。
            continue

        incoming: dict[str, list[dict]] = defaultdict(list)
        for enemy_member in enemy.get("members") or []:
            for attack in enemy_member.get("attacks") or []:
                target = normalize_tag(attack.get("defender_tag"))
                if target:
                    incoming[target].append(attack)

        for member in own.get("members") or []:
            player_tag = normalize_tag(member.get("player_tag"))
            if not player_tag:
                continue
            row = players.setdefault(player_tag, {
                "player_tag": player_tag,
                "account_name": member.get("name") or "-",
                "total_stars": 0,
                "attacks": 0,
                "appearances": 0,
                "missed_attacks": 0,
                "offense_3stars": 0,
                "defense_3stars": 0,
                "defense_total": 0,
            })
            attacks = member.get("attacks") or []
            row["appearances"] += 1
            if not attacks:
                row["missed_attacks"] += 1
            row["total_stars"] += sum(_int(attack.get("stars")) for attack in attacks)
            row["attacks"] += len(attacks)
            row["offense_3stars"] += sum(
                1 for attack in attacks if _int(attack.get("stars")) == 3
            )
            defenses = incoming.get(player_tag, [])
            row["defense_total"] += len(defenses)
            row["defense_3stars"] += sum(
                1 for attack in defenses if _int(attack.get("stars")) == 3
            )
    return [players[tag] for tag in sorted(players)]


def rebuild_league_results(
    conn: sqlite3.Connection,
    group: dict,
    wars: dict[str, dict],
    team: dict,
    *,
    rebuilt_at: str | None = None,
) -> tuple[int, int]:
    """替换一支已完整队伍的投影，返回 ``(written, skipped_unknown)``。"""
    rows = build_league_result_rows(group, wars, team)
    period = team.get("period")
    team_index = team.get("team_index")
    if not period or team_index is None:
        raise ValueError("联赛队伍缺少 period 或 team_index")
    timestamp = rebuilt_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "DELETE FROM league_results WHERE period = ? AND team_index = ?",
        (period, team_index),
    )
    written = skipped = 0
    for row in rows:
        exists = conn.execute(
            "SELECT 1 FROM accounts WHERE player_tag = ?", (row["player_tag"],)
        ).fetchone()
        if not exists:
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO league_results
               (period, team_index, team_alias, team_name, clan_tag, category,
                player_tag, account_name, total_stars, attacks, appearances,
                missed_attacks, offense_3stars, defense_3stars, defense_total,
                fetched_at, raw_metrics)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                period, team_index, team.get("team_alias") or str(team_index),
                team.get("team_name"), normalize_tag(team.get("clan_tag")),
                team.get("category") or "combat", row["player_tag"], row["account_name"],
                row["total_stars"], row["attacks"], row["appearances"],
                row["missed_attacks"], row["offense_3stars"],
                row["defense_3stars"], row["defense_total"], timestamp,
                '{"source":"cwl_raw_projection","version":2}',
            ),
        )
        written += 1
    return written, skipped
