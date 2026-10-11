from __future__ import annotations

from modules.farm_system.scoring import decide_match


def test_lower_score_wins_without_random_source():
    calls = []
    result = decide_match(1, -2, 2, 3, choose_tie_winner=lambda pair: calls.append(pair))
    assert result.winner_clan_id == 1
    assert result.loser_clan_id == 2
    assert not result.tie_break_used
    assert calls == []


def test_equal_score_uses_injected_choice_once():
    calls = []

    def choose(pair):
        calls.append(pair)
        return pair[1]

    result = decide_match(1, 0, 2, 0, choose_tie_winner=choose)
    assert result.winner_clan_id == 2
    assert result.tie_break_used
    assert result.tie_break_value == "2"
    assert calls == [(1, 2)]
