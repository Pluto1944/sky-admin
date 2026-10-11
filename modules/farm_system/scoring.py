"""互刷积分胜负纯规则。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ScoreDecision:
    winner_clan_id: int
    loser_clan_id: int
    tie_break_used: bool
    tie_break_value: str | None


def decide_match(
    clan_a_id: int,
    score_a: int,
    clan_b_id: int,
    score_b: int,
    *,
    choose_tie_winner: Callable[[tuple[int, int]], int],
) -> ScoreDecision:
    """积分低者预定获胜；同分只调用一次可注入随机源。"""
    if int(clan_a_id) == int(clan_b_id):
        raise ValueError("不能用同一个部落建立内部匹配")
    if int(score_a) < int(score_b):
        winner, loser = int(clan_a_id), int(clan_b_id)
        return ScoreDecision(winner, loser, False, None)
    if int(score_b) < int(score_a):
        winner, loser = int(clan_b_id), int(clan_a_id)
        return ScoreDecision(winner, loser, False, None)
    candidates = (int(clan_a_id), int(clan_b_id))
    winner = int(choose_tie_winner(candidates))
    if winner not in candidates:
        raise ValueError("随机源返回了不属于当前匹配的部落")
    loser = candidates[1] if winner == candidates[0] else candidates[0]
    return ScoreDecision(winner, loser, True, str(winner))
