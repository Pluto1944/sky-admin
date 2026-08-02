"""基准重建器（纯函数，无 IO）。

实现设计文档 v3.0 的阶段 0~6：
  阶段 0：前置过滤（黑名单）
  阶段 1：构建 7 个临时名单
  阶段 2：基准重建 + 升降级（仅操作名单1）
  阶段 3：删除实战缺失人员
  阶段 4：插入战营实战新增（名单6）
  阶段 5：插入普通营实战新增（名单7）
  阶段 6：追加壳子名单（名单3）

输入：
  - accounts: sort_accounts() 的输出（含 rank_score / league_type / rank_order）
  - prev_combat_regs: 上月 registrations 表中 combat 记录（含 team_info，rank_order 固定为 None）
  - star_data: {account_name: total_stars}，上月实战星数
  - teams: TEAMS 配置

输出：
  - final_list: 线性名单 [实战区] + [壳子区]
  - removed_list: 被删除的缺失人员（供 Part3 展示）
  - movements: 升降级日志

名单1 的成员来自 results 表（谁实际打了实战 + 星数），队伍归属来自
registrations 表的 team_info 字段（由上月 arrange() 回写）。按 team_index
（队伍编号）分组，避免重名队伍（如 3 支"大一"）混组。
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Any

from config import (
    ACCOUNT_TYPE_COMBAT,
    LEAGUE_COMBAT,
    LEAGUE_SHELL,
    NEW_COMBAT_INSERT_START,
    NEW_NORMAL_INSERT_START,
    PROMOTION_RELEGATION_CONFIG,
)


def _effective_capacity(team: dict) -> int:
    """计算队伍实际可容纳人数（与 team_filler._effective_capacity 一致）。"""
    base = team["member_count"]
    reserved = team.get("reserved_slots", 0)
    if reserved > 0:
        return base - reserved
    elif reserved < 0:
        return base + abs(reserved)
    return base


# ---------------------------------------------------------------------------
# 阶段 0：前置过滤
# ---------------------------------------------------------------------------

def apply_blacklist(
    accounts: list[dict],
    prev_combat_regs: list[dict],
    black_list: set[str],
) -> tuple[list[dict], list[dict], list[str]]:
    """从所有数据源中排除黑名单成员。

    返回:
        (filtered_accounts, filtered_prev_regs, black_hits)
        black_hits: 被黑名单命中的人员列表（供 Part3 展示）
    """
    if not black_list:
        return accounts, prev_combat_regs, []

    filtered_accounts = [
        a for a in accounts if a.get("account_name") not in black_list
    ]
    filtered_prev_regs = [
        r for r in prev_combat_regs if r.get("account_name") not in black_list
    ]

    # 记录黑名单命中（从上月名单和当月报名中检测）
    black_hits: list[str] = []
    for name in black_list:
        in_prev = any(r.get("account_name") == name for r in prev_combat_regs)
        in_current = any(a.get("account_name") == name for a in accounts)
        if in_prev or in_current:
            black_hits.append(name)

    return filtered_accounts, filtered_prev_regs, black_hits


# ---------------------------------------------------------------------------
# 阶段 1：构建临时名单
# ---------------------------------------------------------------------------

def build_temp_lists(
    accounts: list[dict],
    prev_combat_regs: list[dict],
    star_data: dict[str, int],
    teams: list[dict],
    prev_teams_config: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """构建 7 个临时名单。

    参数:
        accounts: 当月排序后的账号列表（sort_accounts 输出）
        prev_combat_regs: 上月 registrations combat 记录
        star_data: {account_name: total_stars}
        teams: 当月 TEAMS 配置
        prev_teams_config: 上月 TEAMS 配置（None 时用当月配置）

    返回:
        {
            "list1": 上月实战名单（按 team_index 分组，组内按星数降序）,
            "list2": 当月实战名单,
            "list3": 当月壳子名单（综合分降序）,
            "list4": 实战缺失名单,
            "list5": 实战新增名单,
            "list6": 战营实战新增名单,
            "list7": 普通营实战新增名单（综合分降序）,
        }
    """
    # --- 名单1：上月实战名单 ---
    # 成员和队伍归属都来自 results 表（prev_combat_regs 自带 team_name 和 stars）
    # 按 team_index（队伍编号）分组，组内按星数降序
    # team_index 是队伍的唯一身份标识，避免重名队伍（如 3 支"大一"）混组
    # 同时从当月 accounts 合并报名数据（match_value / rank_score 等），
    # 供后续阶段5二分插入时排序使用
    cfg = prev_teams_config if prev_teams_config is not None else teams
    prev_combat_teams = [t for t in cfg if t["category"] == LEAGUE_COMBAT]

    # 构建 {account_name: account_data} 查找表（当月报名数据）
    account_map: dict[str, dict] = {}
    for a in accounts:
        name = a.get("account_name")
        if name:
            account_map[name] = a

    # 按 team_index 分组（队伍编号 = combat 队伍在配置中的顺序索引）
    # team_index 为 None 的旧数据回退到 team_name 分组
    team_index_order: list[int | None] = [i for i in range(len(prev_combat_teams))]
    team_groups: dict[int | None, list[dict]] = {i: [] for i in team_index_order}
    team_name_fallback: dict[str, list[dict]] = {}
    team_name_fallback_order: list[str] = []

    for reg in prev_combat_regs:
        tn = reg.get("team_name")
        name = reg.get("account_name")
        if not name:
            continue
        # stars 优先取 prev_combat_regs 自带（来自 results），回退到 star_data
        stars = reg.get("stars")
        if stars is None:
            stars = star_data.get(name)
        member = {
            "account_name": name,
            "player_tag": reg.get("player_tag"),
            "team_name": tn,
            "clan_tag": reg.get("clan_tag"),
            "team_index": reg.get("team_index"),
            "stars": stars if stars is not None else -1,  # 无星数排最后
        }
        # 构建 prev_team："index name" 拼接，用于区分同名队伍
        prev_ti = reg.get("team_index")
        member["prev_team"] = f"{prev_ti} {tn}" if (prev_ti is not None and tn) else tn or ""
        # 合并当月报名数据（match_value / rank_score / history_score / trophies 等）
        # 老兵当月也报名时，补充这些字段供后续排序使用
        curr = account_map.get(name)
        if curr:
            for key in ("match_value", "rank_score", "history_score",
                        "trophies", "account_type", "player_name", "reg_id"):
                if key in curr and key not in member:
                    member[key] = curr[key]

        tidx = reg.get("team_index")
        if tidx is not None and tidx in team_groups:
            team_groups[tidx].append(member)
        elif tn is not None:
            # team_index 缺失（旧数据），回退到 team_name 分组
            if tn not in team_name_fallback:
                team_name_fallback[tn] = []
                team_name_fallback_order.append(tn)
            team_name_fallback[tn].append(member)
        else:
            # 无 team_index 也无 team_name，归入"未知"组
            unknown_key = "__unknown__"
            if unknown_key not in team_name_fallback:
                team_name_fallback[unknown_key] = []
                team_name_fallback_order.append(unknown_key)
            team_name_fallback[unknown_key].append(member)

    # 组内按星数降序排列
    list1: list[dict] = []
    for tidx in team_index_order:
        members = team_groups.get(tidx, [])
        members.sort(key=lambda m: m.get("stars", -1), reverse=True)
        list1.extend(members)
    # 追加 team_name 回退组（旧数据兼容）
    for tn in team_name_fallback_order:
        members = team_name_fallback[tn]
        members.sort(key=lambda m: m.get("stars", -1), reverse=True)
        list1.extend(members)

    # --- 名单2：当月实战名单 ---
    list2 = [a for a in accounts if a.get("league_type") == LEAGUE_COMBAT]

    # --- 名单3：当月壳子名单（综合分降序） ---
    list3 = sorted(
        [a for a in accounts if a.get("league_type") == LEAGUE_SHELL],
        key=lambda x: x.get("rank_score") or 0,
        reverse=True,
    )

    # --- 名单4：实战缺失 = 名单1 - 名单2 ---
    list2_names = {a.get("account_name") for a in list2}
    list4 = [m for m in list1 if m["account_name"] not in list2_names]

    # --- 名单5：实战新增 = 名单2 - 名单1 ---
    list1_names = {m["account_name"] for m in list1}
    list5 = [a for a in list2 if a.get("account_name") not in list1_names]

    # --- 名单6：战营实战新增 = 名单5 ∩ 当月战营账号 ---
    list6 = [
        a for a in list5 if a.get("account_type") == ACCOUNT_TYPE_COMBAT
    ]

    # --- 名单7：普通营实战新增 = 名单5 - 名单6 ---
    list6_names = {a.get("account_name") for a in list6}
    list7 = sorted(
        [a for a in list5 if a.get("account_name") not in list6_names],
        key=lambda x: x.get("rank_score") or 0,
        reverse=True,
    )

    return {
        "list1": list1,
        "list2": list2,
        "list3": list3,
        "list4": list4,
        "list5": list5,
        "list6": list6,
        "list7": list7,
    }


# ---------------------------------------------------------------------------
# 阶段 2：基准重建 + 升降级
# ---------------------------------------------------------------------------

def _split_list1_into_slots(
    list1: list[dict],
    prev_teams_config: list[dict],
) -> list[list[dict]]:
    """将名单1 按上月队伍编号切分为 prev_slots。

    名单1 内部已按 team_index 分组、组内按星数降序。这里按队伍编号切分。
    team_index 是队伍的唯一身份标识，即使 team_name 重名也能正确分成独立 slot。
    team_index 缺失的旧数据回退到 team_name 分组。
    """
    # 按 team_index 分组，保持出现顺序
    groups: list[tuple[int | None, list[dict]]] = []
    seen: dict[int | None, list[dict]] = {}
    # team_index 为 None 时回退到 team_name
    seen_fallback: dict[str, list[dict]] = {}
    groups_fallback: list[tuple[str, list[dict]]] = []

    for m in list1:
        tidx = m.get("team_index")
        if tidx is not None:
            if tidx not in seen:
                seen[tidx] = []
                groups.append((tidx, seen[tidx]))
            seen[tidx].append(m)
        else:
            tn = m.get("team_name") or "__unknown__"
            if tn not in seen_fallback:
                seen_fallback[tn] = []
                groups_fallback.append((tn, seen_fallback[tn]))
            seen_fallback[tn].append(m)

    # 每个 group 就是一支队伍
    return [members for _, members in groups] + [members for _, members in groups_fallback]


def _apply_promotion_relegation_on_slots(
    prev_slots: list[list[dict]],
    star_data: dict[str, int],
    config: dict | None = None,
) -> tuple[list[list[dict]], list[dict]]:
    """在 prev_slots 上执行配对交换升降级。

    对每对相邻 (i, i+1)：
      上队 ≤18星 → 降级到 i+1
      下队 21满星 → 升级到 i
      配对交换，每对最多换 count 人
      19-20星/无星数 → 不动

    返回 (升降级后的 prev_slots, movements日志)
    """
    cfg = {
        "count": PROMOTION_RELEGATION_CONFIG["count"],
        "promotion_min_stars": PROMOTION_RELEGATION_CONFIG["promotion_min_stars"],
        "relegation_max_stars": PROMOTION_RELEGATION_CONFIG["relegation_max_stars"],
        **(config or {}),
    }
    prom_min = cfg["promotion_min_stars"]
    rel_max = cfg["relegation_max_stars"]
    count = cfg["count"]

    movements: list[dict] = []
    moved: set[str] = set()

    slots = [list(s) for s in prev_slots]  # 深拷贝

    for k in range(len(slots) - 1):
        team_high = slots[k]
        team_low = slots[k + 1]

        # 降级候选：上队 ≤ rel_max 星
        relegation_candidates = [
            m for m in team_high
            if m["account_name"] in star_data
            and m["account_name"] not in moved
            and star_data[m["account_name"]] <= rel_max
        ]
        relegation_candidates.sort(
            key=lambda m: star_data[m["account_name"]]
        )
        relegation_candidates = relegation_candidates[:count]

        # 升级候选：下队 ≥ prom_min 星
        promotion_candidates = [
            m for m in team_low
            if m["account_name"] in star_data
            and m["account_name"] not in moved
            and star_data[m["account_name"]] >= prom_min
        ]
        promotion_candidates.sort(
            key=lambda m: star_data[m["account_name"]],
            reverse=True,
        )
        promotion_candidates = promotion_candidates[:count]

        # 配对交换
        n = min(len(relegation_candidates), len(promotion_candidates))
        for i in range(n):
            rel_member = relegation_candidates[i]
            prom_member = promotion_candidates[i]

            rel_name = rel_member["account_name"]
            prom_name = prom_member["account_name"]

            team_high.remove(rel_member)
            team_low.remove(prom_member)
            team_high.append(prom_member)        # 升级者追加到上队末尾
            team_low.insert(0, rel_member)        # 降级者插入下队队首

            moved.add(rel_name)
            moved.add(prom_name)

            movements.append({
                "account_name": rel_name,
                "player_tag": rel_member.get("player_tag"),
                "direction": "relegation",
                "total_stars": star_data[rel_name],
                "from_slot": k,
                "to_slot": k + 1,
            })
            movements.append({
                "account_name": prom_name,
                "player_tag": prom_member.get("player_tag"),
                "direction": "promotion",
                "total_stars": star_data[prom_name],
                "from_slot": k + 1,
                "to_slot": k,
            })

    return slots, movements


def rebuild_baseline(
    list1: list[dict],
    star_data: dict[str, int],
    prev_teams_config: list[dict],
    promotion_config: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """阶段 2：基准重建 + 升降级。

    将名单1 按上月队伍分组 → 配对交换升降级 → 展开为线性列表。

    返回 (final_list, movements)
    """
    if not list1:
        return [], []

    # 2a. 切分为 prev_slots
    prev_slots = _split_list1_into_slots(list1, prev_teams_config)

    # 2c. 配对交换升降级
    if star_data and len(prev_slots) > 1:
        prev_slots, movements = _apply_promotion_relegation_on_slots(
            prev_slots, star_data, promotion_config
        )
    else:
        movements = []

    # 2d. 展开为线性列表
    final_list: list[dict] = []
    for slot in prev_slots:
        final_list.extend(slot)

    return final_list, movements


# ---------------------------------------------------------------------------
# 阶段 3：删除实战缺失人员
# ---------------------------------------------------------------------------

def remove_missing(
    final_list: list[dict],
    list4: list[dict],
) -> tuple[list[dict], list[dict]]:
    """从 final_list 中删除名单4 的成员（实战缺失）。

    不使用占位符，人员前移，名单紧凑。

    返回 (清理后的 final_list, removed_list)
    """
    removed_names = {m["account_name"] for m in list4}
    removed_list = [m for m in final_list if m["account_name"] in removed_names]
    final_list = [m for m in final_list if m["account_name"] not in removed_names]
    return final_list, removed_list


# ---------------------------------------------------------------------------
# 阶段 4：插入战营实战新增
# ---------------------------------------------------------------------------

def insert_combat_new(
    final_list: list[dict],
    list6: list[dict],
    insert_start: int = NEW_COMBAT_INSERT_START,
) -> list[dict]:
    """在 final_list 编号 insert_start 处连续插入名单6 的成员。

    插入后编号重新排列。
    """
    if not list6:
        return final_list

    pos = min(insert_start, len(final_list))
    new_members = [dict(a) for a in list6]
    # 标记为新人
    for m in new_members:
        m["movement"] = "新"
    return final_list[:pos] + new_members + final_list[pos:]


# ---------------------------------------------------------------------------
# 阶段 5：插入普通营实战新增
# ---------------------------------------------------------------------------

def _sort_score(member: dict) -> float:
    """获取成员的排序分数。

    战营账号（account_type=combat）用 trophies 归一化（除以 5000），
    普通账号用 rank_score。这样战营老兵和普通营新人在同一尺度排序。
    """
    if member.get("account_type") == ACCOUNT_TYPE_COMBAT:
        trophies = member.get("trophies") or 0
        return min(trophies / 5000.0, 1.0)
    return member.get("rank_score") or 0


def insert_normal_new(
    final_list: list[dict],
    list7: list[dict],
    insert_start: int = NEW_NORMAL_INSERT_START,  # deprecated，当前逻辑中不再生效
) -> list[dict]:
    """名单7 全部追加到实战区末尾（壳子区之前）。

    不再按综合分二分插入，改为统一追加到实战队列最后。
    老人放前面，新人放后面，新成员之间不排序，保持名单7 原始顺序。
    阶段6 的 append_shell 会在其后追加壳子区，所以普通营新成员自然位于壳子之前。

    注：insert_start 参数已废弃保留，仅用于兼容旧调用。
    """
    if not list7:
        return final_list

    new_members = [dict(a) for a in list7]
    for m in new_members:
        m["movement"] = "新"
    return final_list + new_members


# ---------------------------------------------------------------------------
# 阶段 6：追加壳子名单
# ---------------------------------------------------------------------------

def append_shell(
    final_list: list[dict],
    list3: list[dict],
) -> list[dict]:
    """名单3 按综合分降序追加到 final_list 末尾。

    final_list = [实战区] + [壳子区]
    """
    shell_members = [dict(a) for a in list3]
    return final_list + shell_members


# ---------------------------------------------------------------------------
# 完整流程：阶段 0~6
# ---------------------------------------------------------------------------

def build_final_list(
    accounts: list[dict],
    prev_combat_regs: list[dict],
    star_data: dict[str, int],
    teams: list[dict],
    black_list: set[str] | None = None,
    prev_teams_config: list[dict] | None = None,
    promotion_config: dict | None = None,
    new_combat_insert_start: int | None = None,
    new_normal_insert_start: int | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """执行阶段 0~6，构建最终线性名单。

    参数:
        accounts: sort_accounts() 输出的当月排序账号
        prev_combat_regs: 上月 registrations combat 记录
        star_data: {account_name: total_stars}
        teams: 当月 TEAMS 配置
        black_list: 黑名单
        prev_teams_config: 上月 TEAMS 配置（None 时用当月配置）
        promotion_config: 升降级配置
        new_combat_insert_start: 战营新增插入点（None 用默认值）
        new_normal_insert_start: 普通营新增插入点（None 用默认值）

    返回:
        (final_list, removed_list, movements, black_hits)
        - final_list: [实战区] + [壳子区] 线性名单
        - removed_list: 被删除的缺失人员（供 Part3）
        - movements: 升降级日志
        - black_hits: 黑名单命中人员
    """
    # 阶段 0：前置过滤
    black = black_list or set()
    filtered_accounts, filtered_prev_regs, black_hits = apply_blacklist(
        accounts, prev_combat_regs, black
    )

    # 阶段 1：构建临时名单
    lists = build_temp_lists(
        filtered_accounts, filtered_prev_regs, star_data,
        teams, prev_teams_config,
    )

    # 阶段 2：基准重建 + 升降级
    final_list, movements = rebuild_baseline(
        lists["list1"], star_data,
        prev_teams_config if prev_teams_config is not None else teams,
        promotion_config,
    )

    # 阶段 3：删除实战缺失
    final_list, removed_list = remove_missing(final_list, lists["list4"])

    # 阶段 4：插入战营新增
    combat_start = new_combat_insert_start if new_combat_insert_start is not None else NEW_COMBAT_INSERT_START
    final_list = insert_combat_new(final_list, lists["list6"], combat_start)

    # 阶段 5：插入普通营新增
    normal_start = new_normal_insert_start if new_normal_insert_start is not None else NEW_NORMAL_INSERT_START
    final_list = insert_normal_new(final_list, lists["list7"], normal_start)

    # 阶段 6：追加壳子
    final_list = append_shell(final_list, lists["list3"])

    return final_list, removed_list, movements, black_hits
