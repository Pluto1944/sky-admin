"""升降级算法（纯函数，无 IO）。

在 fill_teams() 完成基础队伍分配后，根据上月实战星数在相邻实战队伍之间
执行人员交换：
- 上队星数低的 → 降级到下队
- 下队满星的 → 升级到上队

设计原则：
1. 只在相邻实战队伍间交换，每对最多换 config["count"] 人
2. 升级门槛严格（满星 21/21），降级门槛宽松（≤18）
3. 每人每月最多跳 1 级（moved 集合阻止同轮重复移动）
4. 新人和上月没打实战的人原地不动（不在 star_data 中）
"""
from __future__ import annotations

from typing import Any

# 默认配置（未传 config 时使用）
_DEFAULT_CONFIG: dict[str, Any] = {
    "count": 2,                  # 每对相邻队伍最多交换人数
    "promotion_min_stars": 21,   # 升级门槛：≥ 此值才可升级
    "relegation_max_stars": 18,  # 降级门槛：≤ 此值触发降级
}


def apply_promotion_relegation(
    team_results: list[dict],
    star_data: dict[str, int],
    config: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """在相邻实战队伍之间执行升降级交换。

    参数:
        team_results: fill_teams() 的输出，每队含 team_name / category / members。
                      members 中每个 dict 须含 account_name 字段。
        star_data: {account_name: total_stars}，上月实战星数（满分 21）。
        config: 升降级配置，None 时使用默认值。支持键：
                - count (int): 每对相邻队伍最多交换人数，默认 2
                - promotion_min_stars (int): 升级门槛，默认 21
                - relegation_max_stars (int): 降级门槛，默认 18

    返回:
        (调整后的 team_results, 升降级日志列表)
        team_results 原地修改并返回（成员在队伍间移动）。
        每条日志格式:
        {
            "account_name": str,
            "from_team": str,
            "to_team": str,
            "direction": "promotion" | "relegation",
            "total_stars": int,
        }
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    prom_min = cfg["promotion_min_stars"]
    rel_max = cfg["relegation_max_stars"]
    count = cfg["count"]

    logs: list[dict] = []
    moved: set[str] = set()  # 已移动账号，防止同轮重复移动

    # 筛选实战队伍（按 team_results 中的出现顺序，即配置中的优先级顺序）
    combat_indices = [
        i for i, t in enumerate(team_results) if t.get("category") == "combat"
    ]

    # 自上而下处理每对相邻实战队伍
    for k in range(len(combat_indices) - 1):
        idx_high = combat_indices[k]
        idx_low = combat_indices[k + 1]
        team_high = team_results[idx_high]
        team_low = team_results[idx_low]

        # 筛选降级候选（来自上队，星数 ≤ rel_max，排除已移动）
        relegation_candidates = [
            m for m in team_high["members"]
            if m.get("account_name") in star_data
            and m["account_name"] not in moved
            and star_data[m["account_name"]] <= rel_max
        ]
        # 星数最低的优先降级
        relegation_candidates.sort(
            key=lambda m: star_data[m["account_name"]]
        )
        relegation_candidates = relegation_candidates[:count]

        # 筛选升级候选（来自下队，星数 ≥ prom_min，排除已移动）
        promotion_candidates = [
            m for m in team_low["members"]
            if m.get("account_name") in star_data
            and m["account_name"] not in moved
            and star_data[m["account_name"]] >= prom_min
        ]
        # 星数最高的优先升级
        promotion_candidates.sort(
            key=lambda m: star_data[m["account_name"]],
            reverse=True,
        )
        promotion_candidates = promotion_candidates[:count]

        # 配对交换：取两侧较少者
        n = min(len(relegation_candidates), len(promotion_candidates))
        for i in range(n):
            rel_member = relegation_candidates[i]
            prom_member = promotion_candidates[i]

            rel_name = rel_member["account_name"]
            prom_name = prom_member["account_name"]

            # 执行交换：从原队伍移除，加入对方队伍
            team_high["members"].remove(rel_member)
            team_low["members"].remove(prom_member)
            team_high["members"].append(prom_member)
            team_low["members"].append(rel_member)

            moved.add(rel_name)
            moved.add(prom_name)

            logs.append({
                "account_name": rel_name,
                "from_team": team_high["team_name"],
                "to_team": team_low["team_name"],
                "direction": "relegation",
                "total_stars": star_data[rel_name],
            })
            logs.append({
                "account_name": prom_name,
                "from_team": team_low["team_name"],
                "to_team": team_high["team_name"],
                "direction": "promotion",
                "total_stars": star_data[prom_name],
            })

    return team_results, logs


def rebuild_assignment_map(
    ordered_with_team: list[dict],
    team_results: list[dict],
) -> None:
    """升降级交换后，根据 team_results 重建 ordered_with_team 的 team_name 映射。

    fill_teams() 产出 ordered_with_team 时已写入 team_name，但升降级交换后
    部分成员的所属队伍变了，需重新回写。原地修改 ordered_with_team。

    只更新出现在 team_results 中的 account_name，其余保持不变。
    """
    assignment: dict[str, str] = {}
    for tr in team_results:
        tn = tr["team_name"]
        for m in tr["members"]:
            name = m.get("account_name")
            if name:
                assignment[name] = tn

    for item in ordered_with_team:
        name = item.get("account_name")
        if name and name in assignment:
            item["team_name"] = assignment[name]
