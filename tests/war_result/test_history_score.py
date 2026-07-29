"""history_score 纯函数测试（war_result 模块，当前为占位实现）。"""
from __future__ import annotations

from modules.war_result.history_score import compute_history_score


def test_history_score_placeholder_returns_default():
    # 占位函数当前返回 0.0（补全公式后再扩展用例）
    assert compute_history_score([], {}) == 0.0
    assert compute_history_score(
        [{"period": "2026-06", "league_type": "combat", "raw_metrics": {"star": 10}}], {}
    ) == 0.0
