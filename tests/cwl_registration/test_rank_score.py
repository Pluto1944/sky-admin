"""rank_score 纯函数测试（cwl_registration 模块）。"""
from __future__ import annotations

from modules.cwl_registration.rank_score import compute_rank_score


def test_rank_score_normalizes_and_weights():
    acc = {"match_value": 100, "history_score": 50}
    # match 归一化=1, history 归一化=0.5 -> 0.6*1 + 0.4*0.5 = 0.8
    score = compute_rank_score(acc, 0, 100, 0, 100,
                               weights={"match_value": 0.6, "history_score": 0.4})
    assert abs(score - 0.8) < 1e-9


def test_rank_score_divide_by_zero_protection():
    # 全体 match 相同、history 相同 -> 归一化分母为 0，返回 0
    acc = {"match_value": 50, "history_score": 50}
    score = compute_rank_score(acc, 50, 50, 50, 50)
    assert score == 0.0


def test_rank_score_weight_change_takes_effect():
    acc = {"match_value": 100, "history_score": 0}
    s1 = compute_rank_score(acc, 0, 100, 0, 100,
                            weights={"match_value": 1.0, "history_score": 0.0})
    s2 = compute_rank_score(acc, 0, 100, 0, 100,
                            weights={"match_value": 0.0, "history_score": 1.0})
    assert s1 == 1.0
    assert s2 == 0.0


def test_rank_score_handles_none_values():
    acc = {"match_value": None, "history_score": None}
    score = compute_rank_score(acc, 0, 100, 0, 100)
    assert score == 0.0
