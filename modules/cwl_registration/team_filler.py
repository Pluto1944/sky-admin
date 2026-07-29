"""队伍填充算法（纯函数，无 IO）。

接收 sort_accounts() 的排序结果 + 队伍配置，按规则分配每个人到具体队伍。

规则：
1. 实战最低匹配值门槛：低于阈值的 combat 账号强制转为 shell
2. 按排序名单顺序依次填充各队伍（含预留位置处理）
3. 最后一个实战队的边界处理：
   a) 实战人数刚刚好——不做修改
   b) 实战人数溢出——多的人注入壳子池，按匹配值重新排序
   c) 实战人数缺口 <5——从壳子池协调匹配值相近的成员补入
   d) 实战人数缺口 >=5——不协调，队伍不满员继续

返回 (含 team_name 的排序名单, 队伍分配结果列表)。
"""
from __future__ import annotations

from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL


def _effective_capacity(team: dict) -> int:
    """计算队伍实际可容纳人数。

    reserved_slots 处理：
    - >0: 队伍末尾留空位，实际填 member_count - reserved_slots 人
    - <0: 多招备选，实际填 member_count + abs(reserved_slots) 人
    - =0: 标准 member_count 人
    """
    base = team["member_count"]
    reserved = team.get("reserved_slots", 0)
    if reserved > 0:
        return base - reserved
    elif reserved < 0:
        return base + abs(reserved)
    return base


def _reserved_empty_slots(team: dict) -> int:
    """返回队伍末尾的预留空位数。仅 reserved_slots > 0 时非零。"""
    return max(team.get("reserved_slots", 0), 0)


def _split_by_threshold(
    ordered: list[dict], threshold: float
) -> tuple[list[dict], list[dict]]:
    """按实战最低匹配值门槛拆分。

    - 普通实战账号（account_type != combat）中 match_value < threshold 的强制转为 shell
    - 战营账号（account_type=combat）不受阈值影响，始终留在 combat_pool
    - 返回 (combat_pool, shell_pool)
    """
    from shared.config.common import ACCOUNT_TYPE_COMBAT

    combat_pool: list[dict] = []
    shell_pool: list[dict] = []

    for item in ordered:
        if item.get("league_type") == LEAGUE_SHELL:
            shell_pool.append(dict(item))
        elif (
            threshold
            and item.get("account_type") != ACCOUNT_TYPE_COMBAT
            and (item.get("match_value") or 0) < threshold
        ):
            # 普通实战账号 但低于门槛 → 强制转为壳子
            item = dict(item)
            item["league_type"] = LEAGUE_SHELL
            item["_force_shell"] = True
            shell_pool.append(item)
        else:
            combat_pool.append(dict(item))

    return combat_pool, shell_pool


def _pick_closest_by_match_value(
    pool: list[dict], n: int, ref_value: float
) -> tuple[list[dict], list[dict]]:
    """从 pool 中选取匹配值与 ref_value 最接近的 n 人。

    返回 (被选中的人, 剩余的人)。
    保留被选中者的原有相对顺序。
    """
    if n <= 0 or not pool:
        return [], list(pool)

    indexed = [
        (abs((a.get("match_value") or 0) - ref_value), i, a)
        for i, a in enumerate(pool)
    ]
    indexed.sort(key=lambda x: x[0])
    picked_indices = {i for _, i, _ in indexed[:n]}
    picked = [a for i, a in enumerate(pool) if i in picked_indices]
    remaining = [a for i, a in enumerate(pool) if i not in picked_indices]
    return picked, remaining


def _build_team_result(team: dict, members: list[dict]) -> dict:
    """构造单支队伍的分配结果。"""
    reserved = _reserved_empty_slots(team)
    return {
        "team_name": team["name"],
        "category": team["category"],
        "clan_tag": team.get("clan_tag"),
        "leader": team.get("leader", ""),
        "league_level": team.get("league_level"),
        "manager": team.get("manager"),
        "member_count": team["member_count"],
        "filled_count": len(members),
        "reserved_empty": reserved,
        "members": members,
    }


def fill_teams(
    ordered_accounts: list[dict],
    teams: list[dict],
    combat_min_match_value: float = 0.0,
) -> tuple[list[dict], list[dict]]:
    """将排序后的账号分配到各队伍。

    ordered_accounts: sort_accounts() 的输出，含 league_type / rank_score / rank_order
    teams: 队伍配置列表（按分配优先级排序）
    combat_min_match_value: 实战最低匹配值门槛（0=不启用）

    返回:
      ordered_with_team: 原排序名单每项追加 "team_name" 字段（league_type 同步更新为最终类别）
      team_results: 各队伍分配明细列表
    """
    combat_teams = [t for t in teams if t["category"] == LEAGUE_COMBAT]
    shell_teams = [t for t in teams if t["category"] == LEAGUE_SHELL]

    # ① 按阈值拆分
    combat_pool, shell_pool = _split_by_threshold(
        ordered_accounts, combat_min_match_value
    )

    # 当某类别无队伍时，将其人员池合并到另一类别
    if not combat_teams and combat_pool:
        for item in combat_pool:
            item["league_type"] = LEAGUE_SHELL
        shell_pool = combat_pool + shell_pool
        combat_pool = []
    if not shell_teams and shell_pool:
        for item in shell_pool:
            item["league_type"] = LEAGUE_COMBAT
        combat_pool = combat_pool + shell_pool
        shell_pool = []

    team_results: list[dict] = []

    # ② 填充非末尾实战队伍
    for team in combat_teams[:-1]:
        capacity = _effective_capacity(team)
        members = combat_pool[:capacity]
        combat_pool = combat_pool[capacity:]
        team_results.append(_build_team_result(team, members))

    # ③ 处理最后一个实战队伍
    if combat_teams:
        last_team = combat_teams[-1]
        last_cap = _effective_capacity(last_team)
        remaining = len(combat_pool)

        if remaining <= last_cap:
            # ③a / ③c / ③d：刚好或不足
            members = list(combat_pool)
            deficit = last_cap - remaining

            if 0 < deficit < 5:
                # ③c：缺口 <5，从壳子池协调相近匹配值成员补入
                ref_value = (
                    (combat_pool[-1].get("match_value") or 0)
                    if combat_pool
                    else 0
                )
                picked, shell_pool = _pick_closest_by_match_value(
                    shell_pool, deficit, ref_value
                )
                for item in picked:
                    item["league_type"] = LEAGUE_COMBAT
                    item["_coordinated"] = True
                members.extend(picked)
                # 成员按综合分（rank_score）降序排列，保持一致性
                members.sort(
                    key=lambda x: x.get("rank_score") or 0, reverse=True
                )
            # deficit == 0: ③a 刚好
            # deficit >= 5: ③d 缺口 >=5，不协调，队伍不满员
            combat_pool = []
        else:
            # ③b：实战人数溢出
            members = combat_pool[:last_cap]
            overflow = combat_pool[last_cap:]
            for item in overflow:
                item["league_type"] = LEAGUE_SHELL
                item["_overflow"] = True
            shell_pool.extend(overflow)
            # 壳子池按匹配值降序重新排序
            shell_pool.sort(
                key=lambda x: x.get("match_value") or 0, reverse=True
            )
            combat_pool = []

        team_results.append(_build_team_result(last_team, members))

    # ④ 填充壳子队伍
    for team in shell_teams:
        capacity = _effective_capacity(team)
        members = shell_pool[:capacity]
        shell_pool = shell_pool[capacity:]
        team_results.append(_build_team_result(team, members))

    # ⑤ 构造排序名单（含 team_name），league_type 更新为最终类别
    assignment_map: dict[str, tuple[str, str]] = {}
    for tr in team_results:
        tn = tr["team_name"]
        cat = tr["category"]
        for m in tr["members"]:
            key = m.get("account_name") or ""
            if key:
                assignment_map[key] = (tn, cat)

    ordered_with_team: list[dict] = []
    for item in ordered_accounts:
        item = dict(item)
        name = item.get("account_name") or ""
        if name in assignment_map:
            item["team_name"], item["league_type"] = assignment_map[name]
        else:
            item["team_name"] = None
        ordered_with_team.append(item)

    return ordered_with_team, team_results
