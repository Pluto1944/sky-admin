"""team_filler 纯函数测试。

覆盖场景：
- 基本填队（实战 4 队 + 壳子 4 队，人员均分）
- 阈值转壳（低于门槛的 combat → shell）
- 预留正数/负数/零
- ③a 刚好 / ③b 溢出 / ③c 缺人<5协调 / ③d 缺人>=5不协调
- 空名单 / 无队伍配置 / 总容量不足
"""
from __future__ import annotations

import pytest

from modules.cwl_registration.team_filler import (
    _effective_capacity,
    _pick_closest_by_match_value,
    _reserved_empty_slots,
    _split_by_threshold,
    fill_teams,
)
from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL


# ---------------------------------------------------------------------------
# 辅助造数据
# ---------------------------------------------------------------------------

def _make_account(name: str, league_type: str, match_value: float,
                  rank_order: int, account_type: str = "normal",
                  trophies: int = 3000, history_score: float = 50,
                  rank_score: float = None) -> dict:
    """造一条排序后的账号记录。"""
    rs = rank_score if rank_score is not None else match_value * 0.6 + history_score * 0.4
    return {
        "account_name": name,
        "player_tag": f"#{name}",
        "league_type": league_type,
        "match_value": match_value,
        "history_score": history_score,
        "rank_score": rs,
        "rank_order": rank_order,
        "account_type": account_type,
        "trophies": trophies,
        "join_combat": league_type == LEAGUE_COMBAT,
        "player_name": f"{name}_owner",
    }


def _make_team(name: str, member_count: int, category: str,
               reserved_slots: int = 0) -> dict:
    return {
        "name": name,
        "clan_tag": "#TAG",
        "leader": "",
        "member_count": member_count,
        "league_level": "",
        "manager": "admin",
        "category": category,
        "reserved_slots": reserved_slots,
    }


# ---------------------------------------------------------------------------
# _effective_capacity
# ---------------------------------------------------------------------------

class TestEffectiveCapacity:
    def test_zero_reserved(self):
        assert _effective_capacity({"member_count": 15, "reserved_slots": 0}) == 15

    def test_positive_reserved(self):
        # reserved=2 → 实际填 13 人（留 2 空位）
        assert _effective_capacity({"member_count": 15, "reserved_slots": 2}) == 13

    def test_negative_reserved(self):
        # reserved=-2 → 多招 2 备选，实际容量 17
        assert _effective_capacity({"member_count": 15, "reserved_slots": -2}) == 17

    def test_no_reserved_key(self):
        assert _effective_capacity({"member_count": 15}) == 15


# ---------------------------------------------------------------------------
# _reserved_empty_slots
# ---------------------------------------------------------------------------

class TestReservedEmptySlots:
    def test_zero(self):
        assert _reserved_empty_slots({"reserved_slots": 0}) == 0

    def test_positive(self):
        assert _reserved_empty_slots({"reserved_slots": 3}) == 3

    def test_negative(self):
        assert _reserved_empty_slots({"reserved_slots": -2}) == 0

    def test_no_key(self):
        assert _reserved_empty_slots({}) == 0


# ---------------------------------------------------------------------------
# _split_by_threshold
# ---------------------------------------------------------------------------

class TestSplitByThreshold:
    def test_below_threshold_combat_becomes_shell(self):
        ordered = [
            _make_account("A", LEAGUE_COMBAT, 900, 1),
            _make_account("B", LEAGUE_COMBAT, 600, 2),  # 低于 800
            _make_account("C", LEAGUE_SHELL, 500, 3),
            _make_account("D", LEAGUE_COMBAT, 1000, 4),
        ]
        combat, shell = _split_by_threshold(ordered, 800)
        assert [a["account_name"] for a in combat] == ["A", "D"]
        assert [a["account_name"] for a in shell] == ["B", "C"]

    def test_below_threshold_marks_force_shell(self):
        ordered = [
            _make_account("B", LEAGUE_COMBAT, 600, 1),
        ]
        _, shell = _split_by_threshold(ordered, 800)
        assert shell[0]["_force_shell"] is True

    def test_zero_threshold_disables_filter(self):
        ordered = [
            _make_account("A", LEAGUE_COMBAT, 100, 1),
            _make_account("B", LEAGUE_SHELL, 50, 2),
        ]
        combat, shell = _split_by_threshold(ordered, 0)
        assert [a["account_name"] for a in combat] == ["A"]
        assert [a["account_name"] for a in shell] == ["B"]

    def test_empty_list(self):
        combat, shell = _split_by_threshold([], 800)
        assert combat == []
        assert shell == []


# ---------------------------------------------------------------------------
# _pick_closest_by_match_value
# ---------------------------------------------------------------------------

class TestPickClosest:
    def test_picks_exact_n(self):
        pool = [
            _make_account("A", LEAGUE_SHELL, 700, 1),
            _make_account("B", LEAGUE_SHELL, 710, 2),
            _make_account("C", LEAGUE_SHELL, 650, 3),
            _make_account("D", LEAGUE_SHELL, 900, 4),
        ]
        picked, remaining = _pick_closest_by_match_value(pool, 2, 700)
        assert len(picked) == 2
        assert len(remaining) == 2

    def test_picks_closest_to_ref(self):
        pool = [
            _make_account("A", LEAGUE_SHELL, 700, 1),
            _make_account("B", LEAGUE_SHELL, 710, 2),
            _make_account("C", LEAGUE_SHELL, 650, 3),  # 差 50
            _make_account("D", LEAGUE_SHELL, 900, 4),  # 差 200
        ]
        # ref=700, closest: A(0), B(10), C(50), D(200). Pick 2 → A, B
        picked, _ = _pick_closest_by_match_value(pool, 2, 700)
        names = {a["account_name"] for a in picked}
        assert names == {"A", "B"}

    def test_n_zero_returns_all_remaining(self):
        pool = [_make_account("A", LEAGUE_SHELL, 700, 1)]
        picked, remaining = _pick_closest_by_match_value(pool, 0, 700)
        assert picked == []
        assert len(remaining) == 1

    def test_n_greater_than_pool(self):
        pool = [_make_account("A", LEAGUE_SHELL, 700, 1)]
        picked, remaining = _pick_closest_by_match_value(pool, 5, 700)
        assert len(picked) == 1
        assert remaining == []

    def test_empty_pool(self):
        picked, remaining = _pick_closest_by_match_value([], 2, 700)
        assert picked == []
        assert remaining == []


# ---------------------------------------------------------------------------
# fill_teams 完整场景
# ---------------------------------------------------------------------------

def _team_names(team_results):
    return [t["team_name"] for t in team_results]


def _assigned_names(team_results):
    """取某队已分配人员的 account_name 列表。"""
    return [m["account_name"] for m in team_results["members"]]


def _ordered_names(ordered_with_team):
    return [(a["account_name"], a.get("team_name")) for a in ordered_with_team]


class TestFillTeamsBasic:
    """基本填队：4实战+4壳子 各15人，全部刚好填满。"""

    def test_even_distribution(self):
        # 60 combat + 60 shell = 120 人，8 队 15 人
        ordered = []
        for i in range(60):
            ordered.append(_make_account(f"combat_{i:03d}", LEAGUE_COMBAT,
                                         900 - i, i + 1))
        for i in range(60):
            ordered.append(_make_account(f"shell_{i:03d}", LEAGUE_SHELL,
                                         800 - i, i + 61))

        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("实战三队", 15, LEAGUE_COMBAT),
            _make_team("实战四队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
            _make_team("壳子二队", 15, LEAGUE_SHELL),
            _make_team("壳子三队", 15, LEAGUE_SHELL),
            _make_team("壳子四队", 15, LEAGUE_SHELL),
        ]

        ordered_wt, team_results = fill_teams(ordered, teams)

        # 每队刚好 15 人
        assert all(t["filled_count"] == 15 for t in team_results)
        # 实战一队 = 前 15 个 combat
        assert _assigned_names(team_results[0]) == [f"combat_{i:03d}" for i in range(15)]
        # 实战四队 = 最后 15 个 combat
        assert _assigned_names(team_results[3]) == [f"combat_{i:03d}" for i in range(45, 60)]
        # 壳子一队 = 前 15 个 shell
        assert _assigned_names(team_results[4]) == [f"shell_{i:03d}" for i in range(15)]

    def test_all_get_team_name(self):
        """每人都在 ordered_with_team 中正确标注。"""
        ordered = []
        for i in range(15):
            ordered.append(_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 5, i + 1))
        for i in range(15):
            ordered.append(_make_account(f"S{i:02d}", LEAGUE_SHELL, 800 - i * 5, i + 16))

        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]

        ordered_wt, _ = fill_teams(ordered, teams)
        names = _ordered_names(ordered_wt)
        combat_names = [(n, t) for n, t in names if t == "实战一队"]
        shell_names = [(n, t) for n, t in names if t == "壳子一队"]
        assert len(combat_names) == 15
        assert len(shell_names) == 15


class TestThresholdForcing:
    """阈值转壳：低于门槛的 combat → shell。"""

    def test_low_combat_forced_to_shell(self):
        ordered = [
            _make_account("High1", LEAGUE_COMBAT, 900, 1),
            _make_account("Low1", LEAGUE_COMBAT, 500, 2),   # 低于 800
            _make_account("High2", LEAGUE_COMBAT, 850, 3),
            _make_account("Low2", LEAGUE_COMBAT, 300, 4),   # 低于 800
            _make_account("Shell1", LEAGUE_SHELL, 700, 5),
        ]
        # 只有 1 队实战 15 人 + 1 队壳子 15 人
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]

        ordered_wt, team_results = fill_teams(ordered, teams, 800)
        combat_members = _assigned_names(team_results[0])
        shell_members = _assigned_names(team_results[1])

        # 实战队只有 High1, High2
        assert combat_members == ["High1", "High2"]
        # 壳子队有 Low1, Low2（被转壳） + Shell1
        assert set(shell_members) == {"Low1", "Low2", "Shell1"}

    def test_forced_shell_people_have_correct_league_type(self):
        ordered = [
            _make_account("Low1", LEAGUE_COMBAT, 500, 1),
        ]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        ordered_wt, _ = fill_teams(ordered, teams, 800)
        # Low1 被转为壳子，league_type 应为 shell
        low1 = next(a for a in ordered_wt if a["account_name"] == "Low1")
        assert low1["team_name"] == "壳子一队"
        assert low1["league_type"] == LEAGUE_SHELL


class TestReservedSlots:
    """预留位置处理。"""

    def test_positive_reserved(self):
        """reserved=5 → 只填 10 实人，留 5 空位。"""
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 5, i + 1)
                   for i in range(10)]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT, reserved_slots=5),
        ]
        _, team_results = fill_teams(ordered, teams)
        assert team_results[0]["filled_count"] == 10
        assert team_results[0]["reserved_empty"] == 5

    def test_negative_reserved(self):
        """reserved=-2 → 多招 2 备选，容量 17。"""
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 5, i + 1)
                   for i in range(17)]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT, reserved_slots=-2),
        ]
        _, team_results = fill_teams(ordered, teams)
        assert team_results[0]["filled_count"] == 17
        assert team_results[0]["reserved_empty"] == 0


class TestLastCombatEdgeCases:
    """最后一个实战队的边界场景。"""

    def test_3a_exact_fit(self):
        """实战人数刚好 = 实战总容量。"""
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 3, i + 1)
                   for i in range(30)]  # 30 combat
        ordered += [_make_account(f"S{i:02d}", LEAGUE_SHELL, 800 - i * 3, i + 31)
                    for i in range(30)]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
            _make_team("壳子二队", 15, LEAGUE_SHELL),
        ]
        _, team_results = fill_teams(ordered, teams)
        assert team_results[0]["filled_count"] == 15
        assert team_results[1]["filled_count"] == 15

    def test_3b_overflow_injects_into_shell(self):
        """实战人数 > 实战总容量，溢出者入壳子池。"""
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 3, i + 1)
                   for i in range(35)]  # 35 combat, 容量 30
        ordered += [_make_account(f"S{i:02d}", LEAGUE_SHELL, 800 - i * 3, i + 36)
                    for i in range(10)]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        ordered_wt, team_results = fill_teams(ordered, teams)
        # 实战队满
        assert team_results[0]["filled_count"] == 15
        assert team_results[1]["filled_count"] == 15
        # 壳子队包含溢出的 5 人 + 原壳子 10 人 = 15
        assert team_results[2]["filled_count"] == 15
        # 溢出的实战人 league_type 变为 shell
        overflow_names = [f"C{i:02d}" for i in range(30, 35)]
        for name in overflow_names:
            item = next(a for a in ordered_wt if a["account_name"] == name)
            assert item["team_name"] == "壳子一队"
            assert item["league_type"] == LEAGUE_SHELL

    def test_3b_overflow_shell_resorted_by_match_value(self):
        """溢出后壳子池按匹配值降序重新排序。"""
        # 32 combat（容量 30）+ 5 壳子
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 3, i + 1)
                   for i in range(32)]
        shells = [
            # 壳子池里有一个匹配值很高的人
            _make_account("Shell_High", LEAGUE_SHELL, 750, 33),
            *[_make_account(f"S{i:02d}", LEAGUE_SHELL, 600 - i * 10, 34 + i)
              for i in range(4)],
        ]
        ordered += shells

        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        _, team_results = fill_teams(ordered, teams)
        # 壳子队有 2 个溢出 + 5 原壳子 = 7 人
        assert team_results[2]["filled_count"] == 7
        # 壳子队内已按匹配值降序排列
        shell_mv = [m["match_value"] for m in team_results[2]["members"]]
        assert shell_mv == sorted(shell_mv, reverse=True)

    def test_3c_shortage_less_than_5_coordinates_from_shell(self):
        """实战缺口 <5，从壳子协调相近匹配值成员补入。"""
        # 27 combat → 两队容量 30，缺口 3
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 3, i + 1)
                   for i in range(27)]
        # 壳子里有几个匹配值与最后实战人接近的
        ordered += [
            _make_account("S_close1", LEAGUE_SHELL, 850, 28),  # 接近
            _make_account("S_far", LEAGUE_SHELL, 300, 29),       # 远离
            _make_account("S_close2", LEAGUE_SHELL, 845, 30),   # 接近
            _make_account("S_med", LEAGUE_SHELL, 600, 31),       # 中等
            _make_account("S_close3", LEAGUE_SHELL, 840, 32),   # 接近
        ]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        ordered_wt, team_results = fill_teams(ordered, teams)
        # 实战二队（最后一队）应填满 15 人（12 剩余 + 3 协调）
        assert team_results[1]["filled_count"] == 15
        # 确认是协调了壳子池的人
        combat2_members = _assigned_names(team_results[1])
        coordinated = [n for n in combat2_members if n.startswith("S_")]
        assert len(coordinated) == 3
        # 协调来的人 league_type 变为 combat
        for name in coordinated:
            item = next(a for a in ordered_wt if a["account_name"] == name)
            assert item["league_type"] == LEAGUE_COMBAT

    def test_3d_shortage_ge_5_no_coordination(self):
        """实战缺口 >=5，不协调，队伍不满员。"""
        # 25 combat → 容量 30，缺口 5
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 3, i + 1)
                   for i in range(25)]
        ordered += [_make_account("S_extra", LEAGUE_SHELL, 800, 26)]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        _, team_results = fill_teams(ordered, teams)
        # 缺 5，不协调
        assert team_results[1]["filled_count"] == 10  # 第一队满 15，剩 10


class TestEdgeCases:
    """边界场景。"""

    def test_empty_ordered(self):
        ordered = []
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        ordered_wt, team_results = fill_teams(ordered, teams)
        assert ordered_wt == []
        assert all(t["filled_count"] == 0 for t in team_results)

    def test_empty_teams(self):
        ordered = [_make_account("A", LEAGUE_COMBAT, 900, 1)]
        ordered_wt, team_results = fill_teams(ordered, [])
        assert team_results == []
        # 无人得到 team_name
        assert ordered_wt[0]["team_name"] is None

    def test_insufficient_capacity(self):
        """总容量不够时，超出的标记为未分配。"""
        ordered = [_make_account(f"A{i:02d}", LEAGUE_COMBAT, 900 - i, i + 1)
                   for i in range(100)]
        teams = [
            _make_team("实战一队", 5, LEAGUE_COMBAT),
        ]
        ordered_wt, team_results = fill_teams(ordered, teams)
        assert team_results[0]["filled_count"] == 5
        assigned = sum(1 for a in ordered_wt if a.get("team_name"))
        assert assigned == 5
        unassigned = sum(1 for a in ordered_wt if a.get("team_name") is None)
        assert unassigned == 95

    def test_only_shell_teams(self):
        """只有壳子队伍时，全体（含 combat）入壳子。"""
        ordered = [
            _make_account("C1", LEAGUE_COMBAT, 900, 1),
            _make_account("S1", LEAGUE_SHELL, 800, 2),
        ]
        teams = [
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        ordered_wt, team_results = fill_teams(ordered, teams)
        assert team_results[0]["filled_count"] == 2

    def test_only_combat_teams(self):
        """只有实战队伍时，壳子人员也会被合并到实战队。"""
        ordered = [
            _make_account("C1", LEAGUE_COMBAT, 900, 1),
            _make_account("S1", LEAGUE_SHELL, 800, 2),
        ]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
        ]
        _, team_results = fill_teams(ordered, teams)
        # 壳子池被合并到实战池，全部分配到实战一队
        assert team_results[0]["filled_count"] == 2
        names = _assigned_names(team_results[0])
        assert "C1" in names
        assert "S1" in names

    def test_ordered_with_team_preserves_rank_order(self):
        """ordered_with_team 保持原始 rank_order 顺序不变。"""
        ordered = [_make_account(f"A{i:02d}", LEAGUE_COMBAT, 900 - i, i + 1)
                   for i in range(20)]
        ordered += [_make_account(f"B{i:02d}", LEAGUE_SHELL, 800 - i, i + 21)
                    for i in range(20)]
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT),
            _make_team("壳子一队", 15, LEAGUE_SHELL),
        ]
        ordered_wt, _ = fill_teams(ordered, teams)
        # rank_order 严格递增
        for i, a in enumerate(ordered_wt):
            assert a["rank_order"] == i + 1

    def test_all_combat_single_team(self):
        """1 队实战，所有 combat 刚好填满。"""
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 5, i + 1)
                   for i in range(15)]
        teams = [_make_team("实战一队", 15, LEAGUE_COMBAT)]
        _, team_results = fill_teams(ordered, teams)
        assert team_results[0]["filled_count"] == 15

    def test_combat_underfill_last_team_with_reserved(self):
        """最后一队有预留且人数不足时应正常处理。"""
        ordered = [_make_account(f"C{i:02d}", LEAGUE_COMBAT, 900 - i * 3, i + 1)
                   for i in range(18)]  # 18 combat
        teams = [
            _make_team("实战一队", 15, LEAGUE_COMBAT),
            _make_team("实战二队", 15, LEAGUE_COMBAT, reserved_slots=5),  # 容量 10
        ]
        _, team_results = fill_teams(ordered, teams)
        # 第一队满 15，第二队只能填 3（剩 3 < 10）
        assert team_results[1]["filled_count"] == 3
        assert team_results[1]["reserved_empty"] == 5
