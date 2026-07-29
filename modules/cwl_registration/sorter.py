"""名单编排排序（纯函数，无 IO）。

职责：分组（实战/壳子）+ 综合分/奖杯排序 + 战营优先，并回填 league_type、rank_order。
综合分算法交给 rank_score.compute_rank_score，本模块不关心其内部实现。
战营排序键与"按上月排名微调"拆成独立函数，便于后续扩展（如奖杯+战绩联合排序）。
"""
from __future__ import annotations

from modules.cwl_registration.config import SORT_WEIGHTS
from modules.cwl_registration.rank_score import compute_rank_score
from shared.config.common import (
    ACCOUNT_TYPE_COMBAT,
    LEAGUE_COMBAT,
    LEAGUE_SHELL,
)


def _extents(accounts: list[dict]) -> tuple[float, float, float, float]:
    """计算 match_value 与 history_score 的极值，用于归一化。"""
    mvs = [a.get("match_value") or 0.0 for a in accounts]
    hss = [a.get("history_score") or 0.0 for a in accounts]
    if not accounts:
        return 0.0, 0.0, 0.0, 0.0
    return min(mvs), max(mvs), min(hss), max(hss)


def _is_combat_league(account: dict) -> bool:
    """判断账号进入实战联赛：战营账号默认实战；普通账号看 join_combat。"""
    if account.get("account_type") == ACCOUNT_TYPE_COMBAT:
        return True
    return bool(account.get("join_combat"))


def camp_sort_key(account: dict) -> tuple:
    """战营账号排序键 —— 阶段一：按奖杯（trophies）降序。

    独立成函数便于后续扩展为"奖杯 + 战绩联合排序"等更复杂策略：只需在此调整
    返回的排序元组（元组各项均为"越小越靠前"，故奖杯取负）。奖杯相同时以综合分
    降序做 tie-breaker，避免同杯数随机排。
    """
    return (-(account.get("trophies") or 0), -(account.get("rank_score") or 0.0))


def adjust_camp_by_prev_rank(camp_accounts: list[dict]) -> list[dict]:
    """根据上月排名（prev_rank）对战营排序结果做微调（预留接口，阶段二实现）。

    当前为恒等操作，直接返回原排序。后续可在此依据 account["prev_rank"] 与本月
    奖杯/战绩做联合微调（例如稳定上月名次、限制单月升降幅度等）。
    """
    return camp_accounts


def sort_accounts(accounts: list[dict], weights: dict | None = None) -> list[dict]:
    """对本月报名账号编排名单。

    返回新的列表，每个元素在原字段基础上追加：
      - league_type: combat / shell
      - rank_score : 综合分（便于调试/展示）
      - rank_order : 全局位次（从 1 开始，实战在前、壳子在后）

    规则：
      - 实战名单 = 战营账号 + 普通实战账号，战营整体排前。
        战营内部按奖杯降序（camp_sort_key），再经 adjust_camp_by_prev_rank 微调；
        普通实战按综合分降序。
      - 壳子名单 = 普通且未选实战账号，按综合分降序。
    """
    if weights is None:
        weights = SORT_WEIGHTS

    m_min, m_max, h_min, h_max = _extents(accounts)

    enriched = []
    for a in accounts:
        item = dict(a)
        item["rank_score"] = compute_rank_score(a, m_min, m_max, h_min, h_max, weights)
        enriched.append(item)

    combat_camp = []   # 战营（实战第 1 梯队）
    combat_normal = []  # 普通实战（实战第 2 梯队）
    shell = []          # 壳子

    for item in enriched:
        if _is_combat_league(item):
            item["league_type"] = LEAGUE_COMBAT
            if item.get("account_type") == ACCOUNT_TYPE_COMBAT:
                combat_camp.append(item)
            else:
                combat_normal.append(item)
        else:
            item["league_type"] = LEAGUE_SHELL
            shell.append(item)

    key = lambda x: x["rank_score"]
    # 战营账号按奖杯降序（阶段一）；后续可在 camp_sort_key / adjust_camp_by_prev_rank 扩展。
    combat_camp.sort(key=camp_sort_key)
    combat_camp = adjust_camp_by_prev_rank(combat_camp)
    combat_normal.sort(key=key, reverse=True)
    shell.sort(key=key, reverse=True)

    ordered = combat_camp + combat_normal + shell
    for idx, item in enumerate(ordered, start=1):
        item["rank_order"] = idx
    return ordered
