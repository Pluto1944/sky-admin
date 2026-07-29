"""名单排序综合分（纯函数，无 IO、无全局状态）。

消费 player 的 match_value 与 history_score，产出用于名单排序的综合分。
归属报名模块——它服务于"生成名单"。可后续替换为更复杂的算法。
"""
from __future__ import annotations

from modules.cwl_registration.config import SORT_WEIGHTS


def _normalize(value: float, lo: float, hi: float) -> float:
    """归一化到 [0,1]，含除零保护（hi<=lo 时返回 0）。"""
    if value is None:
        return 0.0
    if hi <= lo:
        return 0.0
    return (value - lo) / (hi - lo)


def compute_rank_score(
    account: dict,
    match_min: float,
    match_max: float,
    hist_min: float,
    hist_max: float,
    weights: dict | None = None,
) -> float:
    """计算单个账号用于名单排序的综合分。

    account   : 至少包含 match_value、history_score。
    *_min/max : 本月全体账号极值，用于归一化。
    weights   : {'match_value':.., 'history_score':..}，默认取 SORT_WEIGHTS。

    当前默认实现：归一化匹配值与历史战绩后加权求和（含除零保护）。
    后续可自行替换为更复杂的算法（非线性 / 分段 / 引入更多因子）。
    """
    if weights is None:
        weights = SORT_WEIGHTS

    nm = _normalize(account.get("match_value"), match_min, match_max)
    nh = _normalize(account.get("history_score"), hist_min, hist_max)
    return weights["match_value"] * nm + weights["history_score"] * nh
