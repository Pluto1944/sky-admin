"""升降级算法纯函数测试。

覆盖场景：
- 基本升降级（两队各有候选）
- 升级/降级候选不足
- 无候选（无人满足条件）
- 安全区不动（19-20 星）
- 无上月数据跳过（新人）
- 同轮不重复移动（moved 集合）
- 多对相邻队伍级联
- 空队伍 / 仅壳子队伍
- rebuild_assignment_map 回写
"""
from __future__ import annotations

from modules.cwl_registration.promotion import (
    apply_promotion_relegation,
    rebuild_assignment_map,
)
from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL


# ---------------------------------------------------------------------------
# 辅助造数据
# ---------------------------------------------------------------------------

def _make_member(name: str, league_type: str = LEAGUE_COMBAT) -> dict:
    """造一个成员记录（account_name 是升降级匹配的关键字段）。"""
    return {
        "account_name": name,
        "player_tag": f"#{name}",
        "league_type": league_type,
    }


def _make_team(name: str, category: str, members: list[dict]) -> dict:
    """造一支队伍结果（fill_teams 的输出格式）。"""
    return {
        "team_name": name,
        "category": category,
        "clan_tag": "#TAG",
        "leader": "",
        "league_level": "",
        "manager": "admin",
        "member_count": 15,
        "filled_count": len(members),
        "reserved_empty": 0,
        "members": members,
    }


# ---------------------------------------------------------------------------
# 基本场景
# ---------------------------------------------------------------------------

def test_basic_promotion_relegation():
    """两队各有 2 候选 → 2 升 2 降，4 条日志。"""
    team_high = _make_team("泰坦二", LEAGUE_COMBAT, [
        _make_member("甲"), _make_member("乙"), _make_member("丙"),
        _make_member("丁"), _make_member("戊"),
    ])
    team_low = _make_team("冠一", LEAGUE_COMBAT, [
        _make_member("己"), _make_member("庚"), _make_member("辛"),
        _make_member("壬"), _make_member("癸"),
    ])
    star_data = {
        "甲": 15, "乙": 17,   # 降级候选（≤18）
        "丙": 19, "丁": 20,   # 安全区
        "戊": 21,             # 满星但已在最高队，不动
        "己": 21, "庚": 21,   # 升级候选（≥21）
        "辛": 19, "壬": 20,   # 不达升级门槛
        "癸": 18,             # 不达升级门槛
    }

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    # 4 条日志（2 降 + 2 升）
    assert len(logs) == 4

    # 降级：甲(15)、乙(17) 移到冠一
    relegations = [l for l in logs if l["direction"] == "relegation"]
    assert {l["account_name"] for l in relegations} == {"甲", "乙"}
    assert all(l["from_team"] == "泰坦二" and l["to_team"] == "冠一" for l in relegations)

    # 升级：己(21)、庚(21) 移到泰坦二
    promotions = [l for l in logs if l["direction"] == "promotion"]
    assert {l["account_name"] for l in promotions} == {"己", "庚"}
    assert all(l["from_team"] == "冠一" and l["to_team"] == "泰坦二" for l in promotions)

    # 验证成员实际移动
    high_names = {m["account_name"] for m in results[0]["members"]}
    low_names = {m["account_name"] for m in results[1]["members"]}
    assert "己" in high_names and "庚" in high_names
    assert "甲" in low_names and "乙" in low_names
    # 安全区的人不动
    assert "丙" in high_names and "丁" in high_names


def test_promotion_candidate_insufficient():
    """下队只有 1 人满星 → 1 升 1 降，2 条日志。"""
    team_high = _make_team("泰坦二", LEAGUE_COMBAT, [
        _make_member("甲"), _make_member("乙"),
    ])
    team_low = _make_team("冠一", LEAGUE_COMBAT, [
        _make_member("丙"), _make_member("丁"),
    ])
    star_data = {"甲": 15, "乙": 17, "丙": 21, "丁": 19}

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    assert len(logs) == 2
    # 只换了 1 对
    high_names = {m["account_name"] for m in results[0]["members"]}
    assert "丙" in high_names  # 丙升上来了
    assert "甲" not in high_names  # 甲降下去了


def test_relegation_candidate_insufficient():
    """上队只有 1 人 ≤18 → 1 升 1 降。"""
    team_high = _make_team("泰坦二", LEAGUE_COMBAT, [
        _make_member("甲"), _make_member("乙"),
    ])
    team_low = _make_team("冠一", LEAGUE_COMBAT, [
        _make_member("丙"), _make_member("丁"),
    ])
    star_data = {"甲": 15, "乙": 19, "丙": 21, "丁": 21}

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    assert len(logs) == 2


def test_no_candidates_no_change():
    """两队都没人满足条件 → 0 日志，队伍不变。"""
    team_high = _make_team("泰坦二", LEAGUE_COMBAT, [_make_member("甲")])
    team_low = _make_team("冠一", LEAGUE_COMBAT, [_make_member("乙")])
    star_data = {"甲": 19, "乙": 20}  # 甲安全区，乙不满星

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    assert len(logs) == 0
    assert results[0]["members"][0]["account_name"] == "甲"
    assert results[1]["members"][0]["account_name"] == "乙"


def test_safe_zone_not_moved():
    """19-20 星的人不在候选中，不动。"""
    team_high = _make_team("泰坦二", LEAGUE_COMBAT, [
        _make_member("甲"), _make_member("乙"), _make_member("丙"),
    ])
    team_low = _make_team("冠一", LEAGUE_COMBAT, [_make_member("丁")])
    star_data = {"甲": 19, "乙": 20, "丙": 18, "丁": 21}

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    # 只有丙(18)降级，丁(21)升级
    relegations = [l for l in logs if l["direction"] == "relegation"]
    assert len(relegations) == 1
    assert relegations[0]["account_name"] == "丙"

    # 甲(19)、乙(20) 仍在泰坦二
    high_names = {m["account_name"] for m in results[0]["members"]}
    assert "甲" in high_names and "乙" in high_names


def test_new_player_skipped():
    """不在 star_data 中的新人不参与升降级。"""
    team_high = _make_team("泰坦二", LEAGUE_COMBAT, [_make_member("新人")])
    team_low = _make_team("冠一", LEAGUE_COMBAT, [_make_member("满星")])
    star_data = {"满星": 21}  # 新人不在 star_data 中

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    # 新人无降级数据，满星无配对 → 不交换
    assert len(logs) == 0
    high_names = {m["account_name"] for m in results[0]["members"]}
    assert "新人" in high_names


def test_moved_set_prevents_double_move():
    """从 T3 升到 T2 的人不会被同轮再次降级到 T3。"""
    # 3 支队伍：T1 > T2 > T3
    t1 = _make_team("T1", LEAGUE_COMBAT, [_make_member("a"), _make_member("b")])
    t2 = _make_team("T2", LEAGUE_COMBAT, [_make_member("c"), _make_member("d")])
    t3 = _make_team("T3", LEAGUE_COMBAT, [_make_member("e"), _make_member("f")])
    star_data = {
        "a": 15, "b": 17,   # T1 降级候选
        "c": 21, "d": 17,   # c 升级候选, d 降级候选
        "e": 21, "f": 21,   # T3 升级候选
    }

    results, logs = apply_promotion_relegation(
        [t1, t2, t3], star_data
    )

    # 第 1 对 T1↔T2: a(15)↓ c(21)↑  → 2 条日志
    # 第 2 对 T2↔T3: d(17)↓ e(21)↑  → 2 条日志
    # c 刚从 T2 升到 T1，moved 阻止它再被操作
    # d 原在 T2，≤18 是降级候选
    assert len(logs) == 4  # 2 对 × 2 日志(1降+1升)

    # c 应在 T1（升上去了），不在 T2
    t1_names = {m["account_name"] for m in results[0]["members"]}
    t2_names = {m["account_name"] for m in results[1]["members"]}
    assert "c" in t1_names
    assert "c" not in t2_names


def test_multiple_adjacent_pairs():
    """3 支实战队（2 对相邻关系）逐对处理。"""
    t1 = _make_team("T1", LEAGUE_COMBAT, [_make_member("a"), _make_member("b")])
    t2 = _make_team("T2", LEAGUE_COMBAT, [_make_member("c"), _make_member("d")])
    t3 = _make_team("T3", LEAGUE_COMBAT, [_make_member("e"), _make_member("f")])
    star_data = {
        "a": 15, "b": 21,  # a 降级
        "c": 21, "d": 15,  # c 升级, d 降级
        "e": 21, "f": 15,  # e 升级
    }

    results, logs = apply_promotion_relegation(
        [t1, t2, t3], star_data
    )

    assert len(logs) == 4  # 2 对 × 2 日志


def test_empty_team():
    """某队无成员 → 无异常。"""
    team_high = _make_team("T1", LEAGUE_COMBAT, [])
    team_low = _make_team("T2", LEAGUE_COMBAT, [_make_member("a")])
    star_data = {"a": 21}

    results, logs = apply_promotion_relegation(
        [team_high, team_low], star_data
    )

    assert len(logs) == 0


def test_only_shell_teams():
    """无实战队伍 → 返回原结果，日志为空。"""
    t1 = _make_team("壳子1", LEAGUE_SHELL, [_make_member("a")])
    t2 = _make_team("壳子2", LEAGUE_SHELL, [_make_member("b")])
    star_data = {"a": 21, "b": 15}

    results, logs = apply_promotion_relegation(
        [t1, t2], star_data
    )

    assert len(logs) == 0


def test_custom_config():
    """自定义配置：promotion_min=20, relegation_max=17。"""
    team_high = _make_team("T1", LEAGUE_COMBAT, [_make_member("a")])
    team_low = _make_team("T2", LEAGUE_COMBAT, [_make_member("b")])
    star_data = {"a": 18, "b": 20}

    # 默认配置下 a(18)≤18 降级，但 b(20)<21 不升级 → 无交换
    _, logs_default = apply_promotion_relegation(
        [team_high, team_low], star_data
    )
    assert len(logs_default) == 0

    # 自定义配置：prom≥20, rel≤18 → a 降级，b 升级
    team_high2 = _make_team("T1", LEAGUE_COMBAT, [_make_member("a")])
    team_low2 = _make_team("T2", LEAGUE_COMBAT, [_make_member("b")])
    _, logs_custom = apply_promotion_relegation(
        [team_high2, team_low2], star_data,
        {"count": 2, "promotion_min_stars": 20, "relegation_max_stars": 18},
    )
    assert len(logs_custom) == 2


# ---------------------------------------------------------------------------
# rebuild_assignment_map 测试
# ---------------------------------------------------------------------------

def test_rebuild_assignment_map():
    """升降级交换后 rebuild_assignment_map 正确回写 team_name。"""
    ordered = [
        {"account_name": "甲", "team_name": "泰坦二"},
        {"account_name": "乙", "team_name": "泰坦二"},
        {"account_name": "丙", "team_name": "冠一"},
    ]
    # 模拟交换后：甲在冠一，丙在泰坦二
    team_results = [
        _make_team("泰坦二", LEAGUE_COMBAT, [
            _make_member("乙"), _make_member("丙"),
        ]),
        _make_team("冠一", LEAGUE_COMBAT, [
            _make_member("甲"),
        ]),
    ]

    rebuild_assignment_map(ordered, team_results)

    assert ordered[0]["team_name"] == "冠一"   # 甲 → 冠一
    assert ordered[1]["team_name"] == "泰坦二"  # 乙 不变
    assert ordered[2]["team_name"] == "泰坦二"  # 丙 → 泰坦二
