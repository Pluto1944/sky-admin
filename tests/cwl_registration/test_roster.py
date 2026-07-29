"""集成测试：生成名单（roster，原 arrange_league 行为）。"""
from __future__ import annotations

from modules.cwl_registration.config import ARRANGEMENT_OUTPUT_HEADERS, TEAMS
from modules.cwl_registration.roster import LeagueArranger
from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL
from tests.fakes import FakeExcelIO, seed_registrations


def _seed(player_service, reg_repo):
    seed_registrations(player_service, reg_repo, "2026-07", [
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


def test_arrange_orders_combat_camp_first_then_normal_then_shell(player_service, reg_repo):
    _seed(player_service, reg_repo)
    arranger = LeagueArranger(player_service, reg_repo, FakeExcelIO())

    ordered, _team_results = arranger.arrange("2026-07", combat_min_match_value=0)

    # 战营 #B 排最前，其次普通实战 #A，最后壳子 #C
    assert [x["player_tag"] for x in ordered] == ["#B", "#A", "#C"]
    assert ordered[0]["league_type"] == LEAGUE_COMBAT
    assert ordered[1]["league_type"] == LEAGUE_COMBAT
    assert ordered[2]["league_type"] == LEAGUE_SHELL


def test_arrange_assigns_team_names(player_service, reg_repo):
    """验证每人被分配到队伍。"""
    _seed(player_service, reg_repo)
    arranger = LeagueArranger(player_service, reg_repo, FakeExcelIO())

    ordered, team_results = arranger.arrange("2026-07", combat_min_match_value=0)

    # 3 人应分配到队伍
    assert all(x.get("team_name") for x in ordered)
    combat_team = [x["team_name"] for x in ordered if x["league_type"] == LEAGUE_COMBAT]
    shell_team = [x["team_name"] for x in ordered if x["league_type"] == LEAGUE_SHELL]
    # 两个 combat 应在同一队
    assert len(set(combat_team)) == 1
    # 一个 shell 在壳子队
    assert len(shell_team) == 1
    # 返回队伍数应为已分配的非空队伍数
    assert len(team_results) == len(TEAMS)


def test_arrange_writes_back_to_repo(player_service, reg_repo):
    _seed(player_service, reg_repo)
    arranger = LeagueArranger(player_service, reg_repo, FakeExcelIO())
    arranger.arrange("2026-07", combat_min_match_value=0)

    regs = {r["player_tag"]: r for r in reg_repo.get_registrations("2026-07")}
    assert regs["#B"]["rank_order"] == 1
    assert regs["#B"]["league_type"] == LEAGUE_COMBAT
    assert regs["#B"]["team_name"] is not None
    assert regs["#C"]["league_type"] == LEAGUE_SHELL
    assert regs["#C"]["team_name"] is not None


def test_arrange_and_export_writes_sheet(player_service, reg_repo):
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = LeagueArranger(player_service, reg_repo, fake_io)

    ordered, team_results, sheet_name = arranger.arrange_and_export(
        "2026-07", "名单.xlsx", combat_min_match_value=0
    )

    assert sheet_name == "名单_2026-07"
    assert fake_io.last_written_target == "名单.xlsx"
    assert fake_io.last_written_sheet == "名单_2026-07"
    assert fake_io.last_written_headers == ARRANGEMENT_OUTPUT_HEADERS
    # 导出行应包含排序名单部分
    written_rows = fake_io.last_written_rows
    assert written_rows is not None
    # 前 3 行为排序名单
    written_tags = [r["player_tag"] for r in written_rows[:3]]
    assert written_tags == ["#B", "#A", "#C"]


def test_arrange_and_export_contains_team_sections(player_service, reg_repo):
    """导出应包含队伍分配区域。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = LeagueArranger(player_service, reg_repo, fake_io)

    arranger.arrange_and_export("2026-07", "名单.xlsx", combat_min_match_value=0)

    written_rows = fake_io.last_written_rows
    # 应有"=== 战队分配 ==="分隔行
    titles = [r["rank_order"] for r in written_rows]
    assert any("战队分配" in str(t) for t in titles if t)
