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
        [{tag, name, total_stars, total_attacks}, ...]
        格式与 Supercell 官方 API 的 _fetch_team_players() 返回值完全一致
    """
    normalized = _normalize_tag(clan_tag)
    player_stats: dict[str, dict] = defaultdict(
        lambda: {"tag": "", "name": "", "total_stars": 0, "total_attacks": 0},
    )

    for war in cwl_wars:
        clan = war.get("clan", {})
        opponent = war.get("opponent", {})

        # 确定哪边是我们的部落
        if _normalize_tag(clan.get("tag", "")) == normalized:
            our_side = clan
        elif _normalize_tag(opponent.get("tag", "")) == normalized:
            our_side = opponent
        else:
            continue

        for m in our_side.get("members", []):
            ptag = m["tag"]
            stars = sum(a.get("stars", 0) for a in m.get("attacks", []))
            rec = player_stats[ptag]
            rec["tag"] = ptag
            rec["name"] = m["name"]
            rec["total_stars"] += stars
            rec["total_attacks"] += len(m.get("attacks", []))

    return [
        {
            "tag": rec["tag"],
            "name": rec["name"],
            "total_stars": rec["total_stars"],
            "total_attacks": rec["total_attacks"],
        }
        for rec in player_stats.values()
    ]


def fetch_cwl_players(clan_tag: str, period: str) -> list[dict] | None:
    """一站式接口：拉取指定部落指定月份的 CWL 玩家战绩。

    Returns:
        玩家列表（与 Supercell API _fetch_team_players() 格式一致）
        失败或无数据返回 None
    """
    try:
        cwl_wars = filter_cwl_wars(clan_tag, period)
    except Exception as e:
        print(f"  [ClashKing] 请求异常: {e}", file=sys.stderr)
        return None

    if not cwl_wars:
        return None

    return aggregate_players(cwl_wars, clan_tag)
