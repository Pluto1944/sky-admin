"""ClashKing API 客户端。

封装 ClashKing 公开 API 的 HTTP 调用 + CWL 筛选 + 玩家战绩汇总。

核心能力：
- fetch_war_log(clan_tag) — 拉取战争日志原始数据
- is_cwl_war(war) — 判断单场战斗是否为 CWL
- filter_cwl_wars(clan_tag, period) — 筛选指定月份 CWL 战斗
- aggregate_players(cwl_wars, clan_tag) — 汇总玩家战绩
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

API_BASE = "https://api.clashk.ing"


# ═══════════════════════════════════════════════════════════════════════
# HTTP 层
# ═══════════════════════════════════════════════════════════════════════

def _curl_get(url: str, timeout: int = 30) -> dict | list | None:
    """用 curl 发送 GET 请求，绕过 Cloudflare 防护。"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-H", "Accept: application/json", url],
            capture_output=True, text=True, timeout=timeout,
        )
        body = result.stdout.strip()
        if not body or body == "null":
            return None
        return json.loads(body)
    except Exception as e:
        print(f"  [ClashKing HTTP] {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════════════
# CWL 识别
# ═══════════════════════════════════════════════════════════════════════

def _normalize_tag(tag: str) -> str:
    """去除 # 并转大写。"""
    return tag.strip().lstrip("#").upper()


def is_cwl_war(war: dict) -> bool:
    """判断一场战斗是否为 CWL（非普通部落战）。

    特征：
    - teamSize 为 5/15/30（CWL 只支持这三种规格）
    - 大多数成员每人仅 1 次攻击（CWL 每人每天只能打 1 次，普通部落战每人 2 次）
    - 同时检查 clan 和 opponent 两方（目标部落可能在任一侧）
    """
    if war.get("teamSize") not in (5, 15, 30):
        return False

    # 检查两边的成员攻击次数，取成员数多的一方（更有代表性）
    for side in ("clan", "opponent"):
        members = war.get(side, {}).get("members", [])
        if not members:
            continue
        attack_counts = [len(m.get("attacks", [])) for m in members]
        one_atk_ratio = sum(1 for a in attack_counts if a == 1) / len(attack_counts)
        if one_atk_ratio >= 0.8:
            return True

    return False


# ═══════════════════════════════════════════════════════════════════════
# 核心 API
# ═══════════════════════════════════════════════════════════════════════

def fetch_war_log(clan_tag: str, limit: int = 100) -> list[dict]:
    """拉取指定部落的历史战争日志。

    返回战争列表，按 endTime 降序排列。
    """
    normalized = _normalize_tag(clan_tag)
    encoded = f"%23{normalized}"

    data = _curl_get(f"{API_BASE}/war/{encoded}/previous?limit={limit}")
    if data and "items" in data:
        return data["items"]
    return []


def filter_cwl_wars(clan_tag: str, period: str) -> list[dict]:
    """从 war log 中筛选指定月份 + 指定部落的 CWL 战斗。

    Args:
        clan_tag: 部落标签，如 "#2QQ"
        period: 月份 "YYYY-MM"，如 "2026-07"

    Returns:
        CWL 战斗列表（按 endTime 升序）
    """
    wars = fetch_war_log(clan_tag)

    normalized = _normalize_tag(clan_tag)
    period_prefix = period.replace("-", "")

    cwl_wars = []
    for w in wars:
        end_time = w.get("endTime", "")
        if not end_time or not end_time.startswith(period_prefix):
            continue

        if not is_cwl_war(w):
            continue

        # 确认这场战斗有指定部落参与（在 clan/opponent 中）
        clan = w.get("clan", {})
        opponent = w.get("opponent", {})
        clan_tag_war = _normalize_tag(clan.get("tag", ""))
        opp_tag_war = _normalize_tag(opponent.get("tag", ""))
        if normalized not in (clan_tag_war, opp_tag_war):
            continue

        cwl_wars.append(w)

    cwl_wars.sort(key=lambda w: w.get("endTime", ""))
    return cwl_wars


def aggregate_players(cwl_wars: list[dict], clan_tag: str) -> list[dict]:
    """从 CWL 战斗列表中汇总指定部落的玩家战绩。

    Args:
        cwl_wars: filter_cwl_wars() 返回的战斗列表
        clan_tag: 目标部落标签

    Returns:
        [{tag, name, total_stars, total_attacks, offense_3stars, defense_3stars, defense_total}, ...]
    """
    normalized = _normalize_tag(clan_tag)
    player_stats: dict[str, dict] = defaultdict(
        lambda: {
            "tag": "", "name": "",
            "total_stars": 0, "total_attacks": 0,
            "offense_3stars": 0, "defense_3stars": 0, "defense_total": 0,
        },
    )

    for war in cwl_wars:
        clan = war.get("clan", {})
        opponent = war.get("opponent", {})

        # 确定哪边是我们的部落
        if _normalize_tag(clan.get("tag", "")) == normalized:
            our_side = clan
            enemy_side = opponent
        elif _normalize_tag(opponent.get("tag", "")) == normalized:
            our_side = opponent
            enemy_side = clan
        else:
            continue

        # 我方成员：原始 tag → normalized tag 的映射（用于防守数据匹配）
        our_tags: dict[str, str] = {}  # normalized_tag → original_tag
        for m in our_side.get("members", []):
            our_tags[_normalize_tag(m["tag"])] = m["tag"]

        # ── 进攻数据：遍历我方成员 ──
        for m in our_side.get("members", []):
            ptag = m["tag"]
            attacks = m.get("attacks", [])
            stars = sum(a.get("stars", 0) for a in attacks)
            three_stars = sum(1 for a in attacks if a.get("stars", 0) == 3)

            rec = player_stats[ptag]
            rec["tag"] = ptag
            rec["name"] = m["name"]
            rec["total_stars"] += stars
            rec["total_attacks"] += len(attacks)
            rec["offense_3stars"] += three_stars

        # ── 防守数据：遍历对手成员，检查攻击目标是否为我方成员 ──
        for m in enemy_side.get("members", []):
            for a in m.get("attacks", []):
                defender_normalized = _normalize_tag(a.get("defenderTag", ""))
                if defender_normalized in our_tags:
                    original_tag = our_tags[defender_normalized]
                    rec = player_stats[original_tag]
                    rec["defense_total"] += 1
                    if a.get("stars", 0) == 3:
                        rec["defense_3stars"] += 1

    return [
        {
            "tag": rec["tag"],
            "name": rec["name"],
            "total_stars": rec["total_stars"],
            "total_attacks": rec["total_attacks"],
            "offense_3stars": rec["offense_3stars"],
            "defense_3stars": rec["defense_3stars"],
            "defense_total": rec["defense_total"],
        }
        for rec in player_stats.values()
    ]


def aggregate_regular_war_players(regular_wars: list[dict], clan_tag: str) -> list[dict]:
    """从普通部落战列表中汇总指定部落的玩家战绩（只统计满星前的数据）。

    与 aggregate_players() 的关键区别：
    - 按 order 字段全局排序所有攻击，只统计满星前的攻击/防守数据
    - 进攻与防守独立判断：我方满星后不再计入进攻，对手满星后不再计入防守
    - 满星 = teamSize * 3
    - 返回每场每人的独立记录（而非跨场汇总）

    Args:
        regular_wars: 非 CWL 的战争列表
        clan_tag: 目标部落标签

    Returns:
        [{tag, name, total_stars, total_attacks, offense_3stars, defense_3stars, defense_total,
          end_time, town_hall_level}, ...]
        每条记录对应一场战争中的一个玩家
    """
    normalized = _normalize_tag(clan_tag)
    all_records: list[dict] = []

    for war in regular_wars:
        team_size = war.get("teamSize", 0)
        if team_size == 0:
            continue
        max_stars = team_size * 3

        clan = war.get("clan", {})
        opponent = war.get("opponent", {})

        # 确定哪边是我们的部落
        if _normalize_tag(clan.get("tag", "")) == normalized:
            our_side = clan
            enemy_side = opponent
        elif _normalize_tag(opponent.get("tag", "")) == normalized:
            our_side = opponent
            enemy_side = clan
        else:
            continue

        war_end_time = war.get("endTime", "")

        # 我方成员 tag 映射（用于防守数据匹配）
        our_tags: dict[str, str] = {}
        for m in our_side.get("members", []):
            our_tags[_normalize_tag(m["tag"])] = m["tag"]

        # 初始化本场所有我方玩家的统计
        war_stats: dict[str, dict] = {}
        for m in our_side.get("members", []):
            war_stats[m["tag"]] = {
                "tag": m["tag"],
                "name": m["name"],
                "town_hall_level": m.get("townHallLevel", 0),
                "total_stars": 0,
                "total_attacks": 0,
                "offense_3stars": 0,
                "defense_3stars": 0,
                "defense_total": 0,
                "end_time": war_end_time,
            }

        # ── 收集所有攻击，统一按 order 排序 ──
        all_attacks: list[dict] = []

        for m in our_side.get("members", []):
            for a in m.get("attacks", []):
                all_attacks.append({
                    "order": a.get("order", 0),
                    "side": "our",
                    "player_tag": m["tag"],
                    "stars": a.get("stars", 0),
                })

        for m in enemy_side.get("members", []):
            for a in m.get("attacks", []):
                all_attacks.append({
                    "order": a.get("order", 0),
                    "side": "enemy",
                    "defender_tag": a.get("defenderTag", ""),
                    "stars": a.get("stars", 0),
                })

        all_attacks.sort(key=lambda x: x["order"])

        # ── 按 order 遍历，只统计满星前的数据 ──
        our_stars = 0
        enemy_stars = 0

        for atk in all_attacks:
            if atk["side"] == "our":
                # 进攻：我方满星前才计入
                if our_stars < max_stars:
                    ptag = atk["player_tag"]
                    if ptag in war_stats:
                        war_stats[ptag]["total_stars"] += atk["stars"]
                        war_stats[ptag]["total_attacks"] += 1
                        if atk["stars"] == 3:
                            war_stats[ptag]["offense_3stars"] += 1
                our_stars += atk["stars"]
            else:
                # 防守：对手满星前才计入
                if enemy_stars < max_stars:
                    defender_normalized = _normalize_tag(atk["defender_tag"])
                    if defender_normalized in our_tags:
                        original_tag = our_tags[defender_normalized]
                        if original_tag in war_stats:
                            war_stats[original_tag]["defense_total"] += 1
                            if atk["stars"] == 3:
                                war_stats[original_tag]["defense_3stars"] += 1
                enemy_stars += atk["stars"]

        # 本场所有玩家记录加入总列表
        all_records.extend(war_stats.values())

    return all_records


def fetch_cwl_players(clan_tag: str, period: str) -> tuple[list[dict] | None, str]:
    """一站式接口：拉取指定部落指定月份的 CWL 玩家战绩。

    Returns:
        (players, reason): players 为玩家列表（None 表示失败），
        reason 为失败原因描述（成功时为空字符串）
    """
    try:
        cwl_wars = filter_cwl_wars(clan_tag, period)
    except Exception as e:
        return None, f"ClashKing API 请求异常: {e}"

    if not cwl_wars:
        # 进一步诊断：是 API 没返回数据，还是该月份确实没有 CWL
        try:
            all_wars = fetch_war_log(clan_tag)
        except Exception:
            all_wars = []
        if not all_wars:
            return None, f"ClashKing API 未返回任何 war log（部落 {clan_tag} 可能无记录或 API 不可达）"
        # 检查该部落有哪些月份的 CWL 数据
        # ClashKing endTime 格式: "20260709T122220.000Z"，取前6位作为 YYYYMM
        available_periods = sorted(set(
            w.get("endTime", "")[:6]
            for w in all_wars
            if w.get("endTime", "") and is_cwl_war(w)
        ))
        if available_periods:
            return None, (
                f"war log 中无 {period} 的 CWL 记录"
                f"（该部落 {clan_tag} 有 CWL 数据的月份: {', '.join(available_periods)}）"
            )
        else:
            return None, f"war log 中有 {len(all_wars)} 条记录，但无任何 CWL 战斗（可能该部落未参加 CWL）"

    return aggregate_players(cwl_wars, clan_tag), ""
