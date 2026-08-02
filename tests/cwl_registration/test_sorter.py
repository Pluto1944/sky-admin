"""sorter 纯函数测试（cwl_registration 模块）。"""
from __future__ import annotations

from modules.cwl_registration.sorter import sort_accounts
from config import LEAGUE_COMBAT, LEAGUE_SHELL


def test_combat_camp_ranks_before_normal_combat():
    accounts = [
        {"player_tag": "#A", "account_type": "normal", "join_combat": True,
         "match_value": 90, "history_score": 50},
        {"player_tag": "#B", "account_type": "combat", "join_combat": True,
         "match_value": 10, "history_score": 10},
    ]
    result = sort_accounts(accounts)
    combat = [a for a in result if a["league_type"] == LEAGUE_COMBAT]
    # 战营 #B 即使分数低也排在普通实战 #A 前面
    assert combat[0]["player_tag"] == "#B"
    assert combat[1]["player_tag"] == "#A"


def test_within_group_sorted_by_score_desc():
    accounts = [
        {"player_tag": "#L", "account_type": "normal", "join_combat": True,
         "match_value": 10, "history_score": 10},
        {"player_tag": "#H", "account_type": "normal", "join_combat": True,
         "match_value": 100, "history_score": 100},
    ]
    result = sort_accounts(accounts)
    assert [a["player_tag"] for a in result] == ["#H", "#L"]


def test_shell_group_separated():
    accounts = [
        {"player_tag": "#C", "account_type": "normal", "join_combat": False,
         "match_value": 80, "history_score": 80},
        {"player_tag": "#D", "account_type": "combat", "join_combat": True,
         "match_value": 20, "history_score": 20},
    ]
    result = sort_accounts(accounts)
    combat = [a for a in result if a["league_type"] == LEAGUE_COMBAT]
    shell = [a for a in result if a["league_type"] == LEAGUE_SHELL]
    assert [a["player_tag"] for a in combat] == ["#D"]
    assert [a["player_tag"] for a in shell] == ["#C"]
    # 实战整体排在壳子前（rank_order 更小）
    assert combat[0]["rank_order"] < shell[0]["rank_order"]


def test_rank_order_is_global_and_sequential():
    accounts = [
        {"player_tag": "#A", "account_type": "combat", "join_combat": True,
         "match_value": 50, "history_score": 50},
        {"player_tag": "#B", "account_type": "normal", "join_combat": True,
         "match_value": 40, "history_score": 40},
        {"player_tag": "#C", "account_type": "normal", "join_combat": False,
         "match_value": 30, "history_score": 30},
    ]
    result = sort_accounts(accounts)
    assert [a["rank_order"] for a in result] == [1, 2, 3]


def test_empty_list():
    assert sort_accounts([]) == []


def test_single_account():
    result = sort_accounts([
        {"player_tag": "#X", "account_type": "combat", "join_combat": True,
         "match_value": 50, "history_score": 50},
    ])
    assert len(result) == 1
    assert result[0]["rank_order"] == 1
    assert result[0]["league_type"] == LEAGUE_COMBAT


def test_all_equal_values_no_crash():
    # 所有值相同（归一化分母为 0），不应崩溃
    accounts = [
        {"player_tag": "#A", "account_type": "normal", "join_combat": True,
         "match_value": 50, "history_score": 50},
        {"player_tag": "#B", "account_type": "normal", "join_combat": True,
         "match_value": 50, "history_score": 50},
    ]
    result = sort_accounts(accounts)
    assert len(result) == 2


def test_combat_camp_ordered_by_trophies_desc():
    # 战营账号按奖杯（trophies）降序，与匹配值/综合分无关
    accounts = [
        {"player_tag": "#C2", "account_type": "combat", "join_combat": True,
         "trophies": 4000, "match_value": 1, "history_score": 1},
        {"player_tag": "#C1", "account_type": "combat", "join_combat": True,
         "trophies": 6000, "match_value": 999, "history_score": 999},
        {"player_tag": "#N", "account_type": "normal", "join_combat": True,
         "match_value": 500, "history_score": 500},
    ]
    result = sort_accounts(accounts)
    # 战营按奖杯降序：#C1(6000) -> #C2(4000)，普通实战 #N 在战营之后
    assert [a["player_tag"] for a in result] == ["#C1", "#C2", "#N"]


def test_combat_camp_trophies_tie_breaks_by_score():
    # 奖杯相同时按综合分降序做 tie-breaker
    accounts = [
        {"player_tag": "#Lo", "account_type": "combat", "join_combat": True,
         "trophies": 5000, "match_value": 10, "history_score": 10},
        {"player_tag": "#Hi", "account_type": "combat", "join_combat": True,
         "trophies": 5000, "match_value": 100, "history_score": 100},
    ]
    result = sort_accounts(accounts)
    assert [a["player_tag"] for a in result] == ["#Hi", "#Lo"]
