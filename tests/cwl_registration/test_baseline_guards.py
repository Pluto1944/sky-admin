"""升降级边界保护与稳定重排测试。"""
from __future__ import annotations

from modules.cwl_registration.baseline_rebuilder import (
    _apply_promotion_relegation_on_slots,
    build_final_list,
    build_temp_lists,
    insert_combat_new,
    insert_normal_new,
    remove_missing,
)
from modules.cwl_registration.team_builder import build_teams


def _member(name: str, **extra) -> dict:
    item = {"account_name": name}
    item.update(extra)
    return item


def _combat_teams(*capacities: int) -> list[dict]:
    return [
        {
            "name": f"T{i}",
            "category": "combat",
            "member_count": capacity,
            "reserved_slots": 0,
            "clan_tag": f"#T{i}",
        }
        for i, capacity in enumerate(capacities)
    ]


def test_promotion_relegation_uses_team_round_percentage():
    slots = [
        [_member("A", attacks=5), _member("B", attacks=5)],
        [_member("C", attacks=7), _member("D", attacks=7)],
    ]
    stars = {"A": 12, "B": 13, "C": 21, "D": 20}

    result, movements = _apply_promotion_relegation_on_slots(
        slots, stars, {"count": 1}
    )

    assert [m["account_name"] for m in movements] == ["A", "C"]
    assert movements[0]["max_stars"] == 15
    assert movements[0]["performance_rate"] == 12 / 15
    assert "C" in [m["account_name"] for m in result[0]]
    assert "B" in [m["account_name"] for m in result[0]]


def test_promotion_relegation_falls_back_to_absolute_stars_without_attacks():
    slots = [[_member("A")], [_member("B")]]
    result, movements = _apply_promotion_relegation_on_slots(
        slots, {"A": 18, "B": 21}, {"count": 1}
    )

    assert [m["account_name"] for m in movements] == ["A", "B"]
    assert movements[0]["max_stars"] is None
    assert [m["account_name"] for m in result[0]] == ["B"]


def test_promotion_rate_uses_team_rounds_not_personal_attacks():
    slots = [
        [_member("A", attacks=7)],
        [_member("B", attacks=5), _member("C", attacks=4)],
    ]

    _result, movements = _apply_promotion_relegation_on_slots(
        slots, {"A": 18, "B": 15, "C": 12}, {"count": 1}
    )

    assert [m["account_name"] for m in movements] == ["A", "B"]
    assert movements[1]["max_stars"] == 15
    assert movements[1]["performance_rate"] == 1.0


def test_equal_performance_preserves_previous_team_order():
    slots = [
        [_member("A-first", attacks=5), _member("A-second", attacks=5)],
        [_member("B-first", attacks=5), _member("B-second", attacks=5)],
    ]

    _result, movements = _apply_promotion_relegation_on_slots(
        slots,
        {"A-first": 10, "A-second": 10, "B-first": 15, "B-second": 15},
        {"count": 2},
    )

    assert [m["account_name"] for m in movements] == [
        "A-first",
        "B-first",
        "A-second",
        "B-second",
    ]


def test_temp_list_uses_previous_rank_order_as_star_tiebreaker():
    teams = _combat_teams(2)
    previous = [
        {
            "account_name": "second",
            "team_name": "T0",
            "team_index": 0,
            "stars": 15,
            "attacks": 5,
            "rank_order": 2,
        },
        {
            "account_name": "first",
            "team_name": "T0",
            "team_index": 0,
            "stars": 15,
            "attacks": 5,
            "rank_order": 1,
        },
    ]

    lists = build_temp_lists([], previous, {}, teams, teams)

    assert [m["account_name"] for m in lists["list1"]] == ["first", "second"]


def test_missing_promotion_candidate_still_consumes_exchange():
    teams = _combat_teams(1, 1)
    current = [_member("A", league_type="combat")]
    previous = [
        _member("A", team_name="T0", team_index=0, stars=10, attacks=5),
        _member("B", team_name="T1", team_index=1, stars=15, attacks=5),
    ]

    final_list, removed, movements, _black_hits = build_final_list(
        current,
        previous,
        {"A": 10, "B": 15},
        teams,
        prev_teams_config=teams,
    )

    assert [m["account_name"] for m in movements] == ["A", "B"]
    assert [m["account_name"] for m in removed] == ["B"]
    assert [m["account_name"] for m in final_list] == ["A"]
    assert final_list[0]["_relegation_target_team_index"] == 1


def test_missing_relegation_candidate_still_consumes_exchange():
    teams = _combat_teams(1, 1)
    current = [_member("B", league_type="combat")]
    previous = [
        _member("A", team_name="T0", team_index=0, stars=10, attacks=5),
        _member("B", team_name="T1", team_index=1, stars=15, attacks=5),
    ]

    final_list, removed, movements, _black_hits = build_final_list(
        current,
        previous,
        {"A": 10, "B": 15},
        teams,
        prev_teams_config=teams,
    )

    assert [m["account_name"] for m in movements] == ["A", "B"]
    assert [m["account_name"] for m in removed] == ["A"]
    assert [m["account_name"] for m in final_list] == ["B"]
    assert final_list[0]["_promotion_target_team_index"] == 0


def test_missing_repack_does_not_pull_relegation_back_up():
    teams = _combat_teams(6, 5, 5)
    final_list = [
        _member("A"),
        _member("B"),
        _member("C"),
        _member("E"),
        _member("D"),
        _member("G"),
        _member("F", _relegation_target_team_index=1),
        _member("H"),
        _member("I"),
        _member("J"),
        _member("L"),
        _member("K", _relegation_target_team_index=2),
        _member("M"),
        _member("N"),
        _member("O"),
        _member("P"),
    ]

    result, removed = remove_missing(final_list, [_member("E")], teams)

    assert [m["account_name"] for m in removed] == ["E"]
    assert [m["account_name"] for m in result] == [
        "A", "B", "C", "D", "G", "H", "F", "I", "J", "L", "M", "K", "N", "O", "P",
    ]


def test_combat_new_repack_restores_promotion_boundary():
    teams = _combat_teams(3, 3, 3)
    final_list = [
        _member("A"),
        _member("B"),
        _member("C"),
        _member("D"),
        _member("E"),
        _member("G", _promotion_target_team_index=0),
        _member("F", _relegation_target_team_index=1),
        _member("H"),
        _member("I"),
    ]

    result = insert_combat_new(final_list, [_member("X")], 0, teams)

    # 前 3 个是第一队，G 必须被兜底留在第一队。
    assert [m["account_name"] for m in result[:3]] == ["X", "A", "G"]


def test_team_rebalance_keeps_relegation_out_of_stronger_empty_slot():
    teams = _combat_teams(3, 3, 3)
    final_list = [
        _member("A"),
        _member("B"),
        _member("C"),
        _member("D"),
        _member("E"),
        _member("F"),
        _member("R1", _relegation_target_team_index=2),
        _member("R2", _relegation_target_team_index=2),
    ]

    results = build_teams(final_list, teams)

    # Team 1 may remain underfull; R1/R2 must wait for their target-or-weaker
    # team instead of being pulled into a stronger team's available slot.
    locations = {
        member["account_name"]: team_index
        for team_index, team in enumerate(results)
        for member in team["members"]
    }
    assert locations["R1"] >= 2
    assert locations["R2"] >= 2


def test_normal_new_repack_keeps_promotion_target_in_or_above_target():
    teams = _combat_teams(3, 3)
    final_list = [
        _member("A"),
        _member("B"),
        _member("C"),
        _member("G", _promotion_target_team_index=0),
        _member("D"),
        _member("E"),
    ]

    result = insert_normal_new(final_list, [_member("N")], teams=teams)

    assert "G" in [m["account_name"] for m in result[:3]]


def test_promotion_guard_is_not_consumed_by_a_weaker_team(capsys):
    teams = _combat_teams(1, 1, 1)
    final_list = [
        _member("G1", _promotion_target_team_index=0),
        _member("G2", _promotion_target_team_index=0),
        _member("A"),
    ]

    results = build_teams(final_list, teams)

    locations = {
        member["account_name"]: team_index
        for team_index, team in enumerate(results)
        for member in team["members"]
    }
    assert locations["G1"] == 0
    assert locations["G2"] > 0
    assert "升降级保护与队伍调整冲突" in capsys.readouterr().err


def test_whitelist_keeps_highest_priority_and_reports_guard_conflict(capsys):
    teams = _combat_teams(1, 1)
    final_list = [
        _member("G", _promotion_target_team_index=0),
        _member("A"),
    ]

    results = build_teams(
        final_list,
        teams,
        white_list=[("X", "#T0")],
    )

    assert results[0]["members"][0]["account_name"] == "X"
    assert any(
        m.get("account_name") == "G"
        for team in results
        for m in team["members"]
    )
    captured = capsys.readouterr()
    assert "白名单调整与升降级保护冲突" in captured.err
    assert "队伍容量不足" in captured.err


def test_whitelist_target_wins_over_promotion_metadata(capsys):
    teams = _combat_teams(1, 1)
    final_list = [
        _member("X", _promotion_target_team_index=0),
        _member("A"),
    ]

    results = build_teams(
        final_list,
        teams,
        white_list=[("X", "#T1")],
    )

    locations = {
        member["account_name"]: team_index
        for team_index, team in enumerate(results)
        for member in team["members"]
    }
    assert locations["X"] == 1
    assert "白名单调整与升降级保护冲突" in capsys.readouterr().err
