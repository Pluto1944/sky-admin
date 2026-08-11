"""互刷部落统计：拉取部落成员数据 + 部落战数据，计算实时配置和去速本配置。

核心算法：
- 部落实时配置：通过 COC 官方 API 拉取全部部落成员，统计各 TH 数量
- 去速本配置：通过 COC 官方 API 拉取部落战双方成员（按排名排序），用阶段归类法消除速本影响

去速本算法：
  遍历部落战双方成员（按 mapPosition 排序），从最高排名开始。
  第一个出现的 TH 作为"阶段1"，后续遇到更低 TH 才进入下一阶段。
  速本玩家（TH 比所在阶段高）会被归类到当前阶段的高 TH。
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from modules.coc_sync.official.api_client import CocApiClient

TH_KEYS = ["18", "17", "16", "15", "14", "13", "12", "11", "10", "below_10"]


# ═══════════════════════════════════════════════════════════════════════
# 数据拉取（全部走官方 COC API）
# ═══════════════════════════════════════════════════════════════════════

def _encode_tag(tag: str) -> str:
    """将部落标签编码为 URL 安全格式。"""
    from urllib.parse import quote
    return quote(tag.strip().lstrip("#"))


def fetch_clan_members(clan_tag: str) -> list[dict]:
    """通过官方 COC API 拉取全部部落成员。

    Returns:
        [{tag, name, townHallLevel, ...}, ...]
    """
    client = CocApiClient()
    return client.get_clan_members(clan_tag)


def fetch_current_war(clan_tag: str) -> dict | None:
    """通过官方 COC API 拉取当前部落战。

    如果 state 不是 inWar 或 preparation，返回 None。
    """
    client = CocApiClient()
    try:
        encoded = _encode_tag(clan_tag)
        data = client._get(f"/clans/%23{encoded}/currentwar")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    state = data.get("state", "")
    if state not in ("inWar", "preparation"):
        # notInWar / warEnded 无有效数据，跳过
        return None
    return data


# ═══════════════════════════════════════════════════════════════════════
# 部落实时配置
# ═══════════════════════════════════════════════════════════════════════

def calc_realtime_config(members: list[dict]) -> dict:
    """从部落成员数据统计实时 TH 分布。

    Args:
        members: fetch_clan_members() 返回的成员列表

    Returns:
        {"avg_th": float, "distribution": {th_key: count}}
    """
    if not members:
        return {"avg_th": 0.0, "distribution": _empty_distribution()}

    th_list = []
    for m in members:
        th = m.get("townHallLevel", 0)
        if th and isinstance(th, int) and th > 0:
            th_list.append(th)

    distribution = _build_distribution(th_list)
    avg_th = round(sum(th_list) / len(th_list), 1) if th_list else 0.0

    return {"avg_th": avg_th, "distribution": distribution}


# ═══════════════════════════════════════════════════════════════════════
# 去速本配置
# ═══════════════════════════════════════════════════════════════════════

def calc_despeed_config(war_data: dict) -> dict:
    """从部落战数据用阶段归类法统计去速本后的 TH 分布。

    算法（部落战排名从上到下大本等级递减）：
    1. 收集双方所有成员，按 mapPosition 升序排列（从高排名到低排名）
    2. 第一个遇到的 TH 作为阶段起点（current_stage_th）
    3. 后续遍历双方成员来更新阶段：
       - 如果 TH 比当前阶段低（正常递减）→ 进入新阶段
       - 如果 TH 比当前阶段高或相等（速本插队）→ 归类到当前阶段
    4. 只在遇到本方成员时才把当前阶段 TH 记入分布

    这样用对方数据辅助判断排名阶段，但只统计本方成员。
    速本玩家会被"提升"到它实际所处排名阶段的大本等级。

    Args:
        war_data: fetch_current_war() 返回的数据

    Returns:
        {"avg_th": float, "distribution": {th_key: count}}
    """
    # 收集双方成员（双方一起判断阶段，但只统计本方）
    all_members = []
    for side_key in ("clan", "opponent"):
        side = war_data.get(side_key, {})
        is_clan = (side_key == "clan")
        for m in side.get("members", []):
            th = m.get("townhallLevel", 0)
            pos = m.get("mapPosition", 999)
            if th and isinstance(th, int) and th > 0:
                all_members.append((pos, th, is_clan))

    if not all_members:
        return {"avg_th": 0.0, "distribution": _empty_distribution()}

    # 按 mapPosition 排序
    all_members.sort(key=lambda x: x[0])

    # 阶段归类（用双方数据判断阶段，只归类本方成员）
    classified: list[int] = []
    current_stage_th: Optional[int] = None

    for _pos, th, is_clan in all_members:
        if current_stage_th is None:
            current_stage_th = th
        elif th < current_stage_th:
            current_stage_th = th
        if is_clan:
            classified.append(current_stage_th)

    distribution = _build_distribution(classified)
    avg_th = round(sum(classified) / len(classified), 1) if classified else 0.0

    return {"avg_th": avg_th, "distribution": distribution}


# ═══════════════════════════════════════════════════════════════════════
# 组合 API
# ═══════════════════════════════════════════════════════════════════════

def get_farm_clan_stats(clan_tag: str, clan_name: str) -> dict:
    """获取单个互刷部落的完整统计。

    Returns:
        {
            "clan_tag": str,
            "clan_name": str,
            "category": "farm",
            "member_count": int,
            "realtime": {avg_th, distribution},
            "despeed": {has_war, avg_th, distribution} 或 error
        }
    """
    result: dict = {
        "clan_tag": clan_tag,
        "clan_name": clan_name,
        "category": "farm",
        "member_count": 0,
        "realtime": {"avg_th": 0.0, "distribution": _empty_distribution()},
        "despeed": {"has_war": False, "avg_th": 0.0, "distribution": _empty_distribution()},
    }

    # 1. 拉取部落全部成员
    try:
        members = fetch_clan_members(clan_tag)
    except Exception as e:
        result["error"] = f"无法获取部落 {clan_name} 的成员列表: {e}"
        return result

    result["member_count"] = len(members)
    result["realtime"] = calc_realtime_config(members)

    # 2. 拉取部落战数据
    try:
        war_data = fetch_current_war(clan_tag)
    except Exception:
        war_data = None

    if war_data is None:
        return result

    result["despeed"] = {
        "has_war": True,
        **calc_despeed_config(war_data),
    }

    return result


def get_all_farm_stats(farm_clans: list[dict], delay: float = 0.5) -> list[dict]:
    """遍历所有互刷部落，串行拉取并返回统计列表。

    Args:
        farm_clans: get_farm_clans() 返回的部落列表
        delay: 每次 API 调用之间的延迟（秒），避免触发限流

    Returns:
        [{clan_tag, clan_name, ...}, ...]
    """
    results = []
    for clan in farm_clans:
        tag = clan["tag"]
        name = clan.get("name", tag)
        try:
            stats = get_farm_clan_stats(tag, name)
        except Exception as e:
            stats = {
                "clan_tag": tag,
                "clan_name": name,
                "category": "farm",
                "member_count": 0,
                "realtime": {"avg_th": 0.0, "distribution": _empty_distribution()},
                "despeed": {"has_war": False, "avg_th": 0.0, "distribution": _empty_distribution()},
                "error": f"统计失败: {e}",
            }
        results.append(stats)
        time.sleep(delay)
    return results


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

def _build_distribution(th_list: list[int]) -> dict[str, int]:
    """将 TH 等级列表转为分布字典。

    Args:
        th_list: [17, 16, 16, 14, ...]

    Returns:
        {"18": 0, "17": 1, "16": 2, "15": 0, ..., "below_10": 0}
    """
    counter: dict[int, int] = defaultdict(int)
    for th in th_list:
        counter[th] += 1

    dist = {}
    for key in TH_KEYS:
        if key == "below_10":
            dist[key] = sum(count for th, count in counter.items() if th < 10)
        else:
            dist[key] = counter.get(int(key), 0)
    return dist


def _empty_distribution() -> dict[str, int]:
    """返回全 0 的分布字典。"""
    return {k: 0 for k in TH_KEYS}
