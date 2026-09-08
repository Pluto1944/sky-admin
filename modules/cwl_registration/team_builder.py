"""队伍构建器（纯函数，无 IO）。

实现设计文档 v3.1 的阶段 7~8：
  阶段 7：贪心填充队伍（先实战后壳子）
  阶段 8：白名单处理（最高优先级强制插入，超员连锁后移，冲突告警）

输入：
  - final_list: baseline_rebuilder.build_final_list() 的输出线性名单
  - teams: TEAMS 配置
  - white_list: [(account_name, clan_tag)] 白名单

输出：
  - team_results: 各队伍分配明细列表
"""
from __future__ import annotations

import sys

from modules.cwl_registration.baseline_rebuilder import _allocate_with_team_guards


def _effective_capacity(team: dict) -> int:
    """计算队伍实际可容纳人数（与 team_filler._effective_capacity 一致）。"""
    base = team["member_count"]
    reserved = team.get("reserved_slots", 0)
    if reserved > 0:
        return base - reserved
    elif reserved < 0:
        return base + abs(reserved)
    return base


def _build_team_result(team: dict, members: list[dict], team_index: int) -> dict:
    """构造单支队伍的分配结果。"""
    reserved = max(team.get("reserved_slots", 0), 0)
    return {
        "team_name": team["name"],
        "coc_name": team.get("coc_name", ""),  # COC 真实部落名称
        "leader_name": team.get("leader_name", ""),  # COC 真实首领名（arrange 阶段通过 API 注入）
        "team_index": team_index,
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


# ---------------------------------------------------------------------------
# 阶段 7：贪心填充队伍
# ---------------------------------------------------------------------------

def fill_teams_from_final_list(
    final_list: list[dict],
    teams: list[dict],
) -> list[dict]:
    """final_list 从上到下连续填充队伍。

    final_list 本身已经是按实力从上到下排好的完整线性名单
    （阶段6 追加壳子名单到末尾），直接按顺序连续填充每支队伍即可：
    第一支队填满，再填第二支，依此类推。

    返回 team_results 列表。
    """
    pool = list(final_list)  # 保持 final_list 顺序，不拆池子

    team_results: list[dict] = []
    for team_index, team in enumerate(teams):
        capacity = _effective_capacity(team)
        members = pool[:capacity]
        pool = pool[capacity:]
        # 给每个成员写入当月队伍信息（"index name" 拼接，区分同名队伍）
        cur_team = f"{team_index} {team['name']}"
        for m in members:
            m["cur_team"] = cur_team
        team_results.append(_build_team_result(team, members, team_index))

    # 如果还有剩余，追加到最后一支队伍
    if pool:
        last = team_results[-1]
        cur_team = f"{last['team_index']} {last['team_name']}"
        for m in pool:
            m["cur_team"] = cur_team
        last["members"].extend(pool)
        last["filled_count"] = len(last["members"])

    return team_results


def _rebalance_team_guards(
    team_results: list[dict],
    teams: list[dict],
) -> list[dict]:
    """Repair promotion/relegation team-boundary violations after a shift.

    ``baseline_rebuilder`` stores guard targets by combat-team ordinal, while
    ``team_results`` uses the full configuration index (combat + shell).  The
    targets are translated before applying the same stable packer used by the
    baseline stages.  The return value contains any guards that could not be
    satisfied because the configured capacities had no available slot.
    """
    if not team_results:
        return []

    combat_indices = [
        i for i, team in enumerate(teams)
        if team.get("category") == "combat"
    ]
    capacities = [_effective_capacity(team) for team in teams]
    flattened: list[dict] = []
    for tr in team_results:
        flattened.extend(tr["members"])

    # White-list placement is the highest-priority business rule.  Keep the
    # requested full team index while translating promotion/relegation targets.
    fixed_targets: dict[str, int] = {}
    for member in flattened:
        name = member.get("account_name")
        target = member.get("_whitelist_target_team_index")
        if name and target is not None:
            fixed_targets[name] = target

    translated: list[dict] = []
    for member in flattened:
        if member.get("_guard_targets_global"):
            # All guard and minimum-team metadata are already expressed in
            # the full configuration index after the first pass.
            translated.append(member)
            continue
        promotion_target = member.get("_promotion_target_team_index")
        relegation_target = member.get("_relegation_target_team_index")
        minimum_team = member.get("_minimum_team_index")
        if (
            promotion_target is None
            and relegation_target is None
            and minimum_team is None
        ):
            translated.append(member)
            continue
        copy = dict(member)
        if promotion_target is not None and 0 <= promotion_target < len(combat_indices):
            copy["_promotion_target_team_index"] = combat_indices[promotion_target]
        if relegation_target is not None and 0 <= relegation_target < len(combat_indices):
            copy["_relegation_target_team_index"] = combat_indices[relegation_target]
        if minimum_team is not None and 0 <= minimum_team < len(combat_indices):
            copy["_minimum_team_index"] = combat_indices[minimum_team]
        copy["_guard_targets_global"] = True
        translated.append(copy)

    guarded_groups, overflow = _allocate_with_team_guards(
        translated,
        capacities,
        protect_relegation=True,
        protect_promotion=True,
        fixed_targets=fixed_targets,
    )

    for team_index, tr in enumerate(team_results):
        members = guarded_groups[team_index]
        if team_index == len(team_results) - 1:
            # Preserve the existing overflow policy: only the last configured
            # team absorbs members beyond the configured total capacity.
            members = members + overflow
        tr["members"] = members
        tr["filled_count"] = len(members)
        cur_team = f"{team_index} {tr['team_name']}"
        for member in members:
            member["cur_team"] = cur_team

    # Validate against the full team indices after packing.  A conflict is
    # returned for the caller to report; ordinary overflow remains compatible
    # with the existing last-team behavior.
    warnings: list[dict] = []
    for team_index, tr in enumerate(team_results):
        for member in tr["members"]:
            name = member.get("account_name")
            promotion_target = member.get("_promotion_target_team_index")
            relegation_target = member.get("_relegation_target_team_index")
            if promotion_target is not None and team_index > promotion_target:
                warnings.append({
                    "account_name": name,
                    "kind": "promotion_guard",
                    "target_team_index": promotion_target,
                    "actual_team_index": team_index,
                })
            if relegation_target is not None and team_index < relegation_target:
                warnings.append({
                    "account_name": name,
                    "kind": "relegation_guard",
                    "target_team_index": relegation_target,
                    "actual_team_index": team_index,
                })
            fixed_target = fixed_targets.get(name)
            if fixed_target is not None and team_index != fixed_target:
                warnings.append({
                    "account_name": name,
                    "kind": "whitelist_target",
                    "target_team_index": fixed_target,
                    "actual_team_index": team_index,
                })
    return warnings


# ---------------------------------------------------------------------------
# 阶段 8：白名单处理
# ---------------------------------------------------------------------------

def apply_whitelist(
    team_results: list[dict],
    white_list: list[tuple[str, str]],
    teams: list[dict],
) -> list[dict]:
    """处理白名单：强制插入到指定队伍开头，超员连锁后移。

    白名单是最高优先级。插入完成后由 ``build_teams`` 复用升降级
    边界保护；如果目标容量不足以同时满足白名单和升降级约束，保留
    白名单目标并打印告警。

    对白名单中每一项 (account_name, clan_tag)：
      1. 找到 clan_tag 对应的队伍
      2. 如果 account_name 已在队伍中 → 移到该队伍开头
      3. 如果 account_name 不在最终名单中 → 强制插入到该队伍开头
      4. 该队伍其他成员后移
      5. 队伍超员 → 末尾溢出到下一支队伍开头，连锁后移

    参数:
        team_results: fill_teams_from_final_list() 的输出
        white_list: [(account_name, clan_tag)]
        teams: TEAMS 配置（用于查找 clan_tag 对应队伍）

    返回调整后的 team_results。
    """
    if not white_list:
        return team_results

    # 构建 clan_tag → team_index 映射
    clan_tag_to_idx: dict[str, int] = {}
    for i, team in enumerate(teams):
        ct = team.get("clan_tag")
        if ct:
            clan_tag_to_idx[ct] = i

    # 构建 account_name → team_index 映射（当前所在队伍）
    name_to_team_idx: dict[str, int] = {}
    for idx, tr in enumerate(team_results):
        for m in tr["members"]:
            name = m.get("account_name")
            if name:
                name_to_team_idx[name] = idx

    for account_name, clan_tag in white_list:
        target_idx = clan_tag_to_idx.get(clan_tag)
        if target_idx is None:
            print(
                f"[WARNING] 白名单目标部落未在队伍配置中："
                f"account={account_name}, clan_tag={clan_tag}",
                file=sys.stderr,
            )
            continue

        target_team = team_results[target_idx]
        current_idx = name_to_team_idx.get(account_name)

        if current_idx == target_idx:
            # 已在目标队伍中 → 移到开头
            member = None
            for m in target_team["members"]:
                if m.get("account_name") == account_name:
                    member = m
                    break
            if member:
                member["_whitelist_target_team_index"] = target_idx
                target_team["members"].remove(member)
                target_team["members"].insert(0, member)
            continue

        if current_idx is not None:
            # 在其他队伍中 → 从原队伍移除，插入到目标队伍开头
            source_team = team_results[current_idx]
            member = None
            for m in source_team["members"]:
                if m.get("account_name") == account_name:
                    member = m
                    break
            if member:
                source_team["members"].remove(member)
                source_team["filled_count"] = len(source_team["members"])
        else:
            # 不在名单中 → 创建新成员
            member = {
                "account_name": account_name,
                "player_tag": None,
                "player_name": None,
                "movement": "白名单",
                "league_type": target_team["category"],
            }

        # 插入到目标队伍开头
        member["cur_team"] = f"{target_idx} {target_team['team_name']}"
        member["_whitelist_target_team_index"] = target_idx
        target_team["members"].insert(0, member)
        target_team["filled_count"] = len(target_team["members"])
        name_to_team_idx[account_name] = target_idx

        # 检查超员，连锁后移
        _cascade_overflow(team_results, teams, target_idx, name_to_team_idx)

    return team_results


def _cascade_overflow(
    team_results: list[dict],
    teams: list[dict],
    start_idx: int,
    name_to_team_idx: dict[str, int],
) -> None:
    """从 start_idx 开始检查超员，末尾溢出到下一支队伍开头，连锁后移。"""
    idx = start_idx
    while idx < len(team_results):
        team = team_results[idx]
        capacity = _effective_capacity(teams[idx])
        overflow_count = len(team["members"]) - capacity

        if overflow_count <= 0:
            break

        # 取末尾 overflow_count 人溢出到下一队
        overflow_members = team["members"][-overflow_count:]
        team["members"] = team["members"][:-overflow_count]
        team["filled_count"] = len(team["members"])

        if idx + 1 < len(team_results):
            # 插入到下一队开头
            next_team = team_results[idx + 1]
            next_cur_team = f"{idx + 1} {next_team['team_name']}"
            for m in reversed(overflow_members):
                m["cur_team"] = next_cur_team
                next_team["members"].insert(0, m)
                name = m.get("account_name")
                if name:
                    name_to_team_idx[name] = idx + 1
            next_team["filled_count"] = len(next_team["members"])
            idx += 1
        else:
            # 已经是最后一支队伍，超员人员保留（不再后移）
            team["members"].extend(overflow_members)
            team["filled_count"] = len(team["members"])
            break


# ---------------------------------------------------------------------------
# 完整流程：阶段 7~8
# ---------------------------------------------------------------------------

def _assign_managers(
    team_results: list[dict],
    manager_candidates: list[str],
) -> None:
    """按三级优先级为每个队伍匹配管理员。

    1. 优先：按 manager_candidates 列表顺序逐个匹配队伍成员（现有逻辑）。
    2. 其次：如果 config 没匹配到，在队伍成员中找 willing_to_manage=True 的第一个。
    3. 兜底：都没有就留空。
    """
    remaining = list(manager_candidates)
    for tr in team_results:
        member_names = {m.get("account_name", "") for m in tr["members"]}
        assigned = ""

        # 第 1 级：config 备选管理员列表匹配
        for candidate in remaining:
            if candidate in member_names:
                assigned = candidate
                remaining.remove(candidate)
                break

        # 第 2 级：config 未命中，从队伍成员中找报名意愿者
        if not assigned:
            for m in tr["members"]:
                if m.get("willing_to_manage"):
                    assigned = m.get("account_name", "")
                    break

        tr["manager"] = assigned


def build_teams(
    final_list: list[dict],
    teams: list[dict],
    white_list: list[tuple[str, str]] | None = None,
    manager_candidates: list[str] | None = None,
) -> list[dict]:
    """执行阶段 7~9：贪心填充队伍 + 白名单处理 + 管理员分配。

    返回 team_results 列表。
    """
    # 阶段 7：贪心填充
    team_results = fill_teams_from_final_list(final_list, teams)

    # 新增/缺失后的稳定重排在 baseline 阶段已经完成；这里再次按当前
    # 队伍容量校验，确保壳子补位和最终切队没有让升降级成员越过边界。
    guard_warnings = _rebalance_team_guards(team_results, teams)

    # 阶段 8：白名单处理
    if white_list:
        team_results = apply_whitelist(team_results, white_list, teams)
        # 白名单是强制操作，但仍须优先尝试维持升降级边界；无法同时
        # 满足时保留白名单结果并输出告警，便于人工处理。
        whitelist_guard_warnings = _rebalance_team_guards(team_results, teams)
        for warning in whitelist_guard_warnings:
            print(
                "[WARNING] 白名单调整与升降级保护冲突："
                f"{warning.get('account_name')} "
                f"target_team={warning.get('target_team_index')} "
                f"actual_team={warning.get('actual_team_index')} "
                f"kind={warning.get('kind')}",
                file=sys.stderr,
            )
    for warning in guard_warnings:
        print(
            "[WARNING] 升降级保护与队伍调整冲突："
            f"{warning.get('account_name')} "
            f"target_team={warning.get('target_team_index')} "
            f"actual_team={warning.get('actual_team_index')} "
            f"kind={warning.get('kind')}",
            file=sys.stderr,
        )

    # Keep the existing policy of allowing the last configured team to absorb
    # overflow, but make the conflict visible to operators.  This is also the
    # final fallback when white-list and movement constraints cannot all fit.
    for team_index, tr in enumerate(team_results):
        capacity = _effective_capacity(teams[team_index])
        if len(tr["members"]) > capacity:
            print(
                "[WARNING] 队伍容量不足，保留超员结果："
                f"team={team_index} {tr['team_name']} "
                f"filled={len(tr['members'])} capacity={capacity}",
                file=sys.stderr,
            )

    # 阶段 9：管理员分配
    if manager_candidates:
        _assign_managers(team_results, manager_candidates)

    return team_results
