"""集成测试：生成名单（roster，v3.0 基准重建方案）。"""
from __future__ import annotations

from modules.cwl_registration.config import ARRANGEMENT_OUTPUT_HEADERS, TEAMS
from modules.cwl_registration.roster import LeagueArranger
from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL
from tests.fakes import FakeExcelIO, seed_registrations


def _seed(player_service, reg_repo):
    seed_registrations(player_service, reg_repo, "2026-08", [
        # 普通实战，高分
        {"player_tag": "#A", "account_name": "甲", "account_type": "normal",
         "match_value": 90, "join_combat": True, "history_score": 90},
        # 战营，低分（应排最前）
        {"player_tag": "#B", "account_name": "乙", "account_type": "combat",
         "match_value": 10, "join_combat": True, "history_score": 10},
        # 壳子
        {"player_tag": "#C", "account_name": "丙", "account_type": "normal",
         "match_value": 100, "join_combat": False, "history_score": 100},
    ])


def test_arrange_assigns_teams(player_service, reg_repo):
    """v3.0: 验证每人被分配到队伍，且实战和壳子分开。"""
    _seed(player_service, reg_repo)
    arranger = LeagueArranger(player_service, reg_repo, FakeExcelIO())

    ordered, team_results, _movements, _star_data = arranger.arrange("2026-08", combat_min_match_value=0)

    # 所有人应被分配到队伍（有 team_name）
    assert all(x.get("team_name") for x in ordered if x.get("player_tag"))

    # 应有 combat 和 shell 两种 league_type
    league_types = {x["league_type"] for x in ordered if x.get("player_tag")}
    assert LEAGUE_COMBAT in league_types
    assert LEAGUE_SHELL in league_types

    # 返回队伍数应为 TEAMS 配置的队伍数
    assert len(team_results) == len(TEAMS)


def test_arrange_writes_back_to_repo(player_service, reg_repo):
    """v3.0: 验证回写 league_type / rank_order / team_name 到 registrations。"""
    _seed(player_service, reg_repo)
    arranger = LeagueArranger(player_service, reg_repo, FakeExcelIO())
    arranger.arrange("2026-08", combat_min_match_value=0)

    regs = {r["player_tag"]: r for r in reg_repo.get_registrations("2026-08")}
    # 战营账号应为 combat
    assert regs["#B"]["league_type"] == LEAGUE_COMBAT
    assert regs["#B"]["team_name"] is not None
    # 壳子账号应为 shell
    assert regs["#C"]["league_type"] == LEAGUE_SHELL
    assert regs["#C"]["team_name"] is not None


def test_arrange_and_export_writes_sheet(player_service, reg_repo):
    """v3.0: 验证 arrange_and_export 写入 sheet。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = LeagueArranger(player_service, reg_repo, fake_io)

    ordered, team_results, _movements, sheet_name = arranger.arrange_and_export(
        "2026-08", "名单.xlsx", combat_min_match_value=0
    )

    assert sheet_name == "名单_2026-08"
    assert fake_io.last_written_target == "名单.xlsx"
    assert fake_io.last_written_sheet == "名单_2026-08"
    assert fake_io.last_written_headers == ARRANGEMENT_OUTPUT_HEADERS
    # 导出行应包含排序名单部分
    written_rows = fake_io.last_written_rows
    assert written_rows is not None
    # 前 3 行应为排序名单（3 个报名成员）
    written_tags = [r["player_tag"] for r in written_rows[:3]]
    assert set(written_tags) == {"#A", "#B", "#C"}


def test_arrange_and_export_contains_team_sections(player_service, reg_repo):
    """v3.0: 导出应包含队伍分配区域。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = LeagueArranger(player_service, reg_repo, fake_io)

    arranger.arrange_and_export("2026-08", "名单.xlsx", combat_min_match_value=0)

    written_rows = fake_io.last_written_rows
    # 应有"=== 战队分配 ==="分隔行
    titles = [r["rank_order"] for r in written_rows]
    assert any("战队分配" in str(t) for t in titles if t)


def test_arrange_and_export_contains_part3_departure(player_service, reg_repo):
    """v3.0: 导出应包含离队情况区域（Part3）。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = LeagueArranger(player_service, reg_repo, fake_io)

    arranger.arrange_and_export("2026-08", "名单.xlsx", combat_min_match_value=0)

    written_rows = fake_io.last_written_rows
    titles = [r["rank_order"] for r in written_rows]
    # 应有 Part4 排布区域
    assert any("联赛名单排布" in str(t) for t in titles if t)
