"""队伍构建器（纯函数，无 IO）。

实现设计文档 v3.0 的阶段 7~8：
  阶段 7：贪心填充队伍（先实战后壳子）
  阶段 8：白名单处理（强制插入到指定队伍开头，超员连锁后移）

输入：
  - final_list: baseline_rebuilder.build_final_list() 的输出线性名单
  - teams: TEAMS 配置
  - white_list: [(account_name, clan_tag)] 白名单

输出：
  - team_results: 各队伍分配明细列表
"""
from __future__ import annotations




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


# ---------------------------------------------------------------------------
# 阶段 8：白名单处理
# ---------------------------------------------------------------------------

def apply_whitelist(
    team_results: list[dict],
    white_list: list[tuple[str, str]],
    teams: list[dict],
) -> list[dict]:
    """处理白名单：强制插入到指定队伍开头，超员连锁后移。

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
            # clan_tag 不在配置中，跳过
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

    # 阶段 8：白名单处理
    if white_list:
        team_results = apply_whitelist(team_results, white_list, teams)

    # 阶段 9：管理员分配
    if manager_candidates:
        _assign_managers(team_results, manager_candidates)

    return team_results
