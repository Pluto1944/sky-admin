"""历史战绩综合分（纯函数，无 IO、无全局状态）。

消费一个账号的历史战绩记录（results），产出写入 player.history_score 的分数。
归属战绩模块。当前为占位实现，待补充公式。
"""
from __future__ import annotations


def compute_history_score(history_results: list[dict], config: dict | None = None) -> float:
    """根据一个账号的历史战绩记录，计算其历史战绩综合分。

    history_results: [{'period':'2026-06','league_type':'combat','raw_metrics':{...}}, ...]
    返回：一个可用于排序的浮点分数。

    TODO(由你补充)：定义指标权重、最近 N 月加权 / 累计平均、新账号默认分、
                    实战与壳子是否分开计入 等规则。
    """
    return 0.0  # 占位，待补充
