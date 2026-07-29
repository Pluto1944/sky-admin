"""集成测试：生成名单（roster，原 arrange_league 行为）。"""
from __future__ import annotations

from modules.cwl_registration.config import ARRANGEMENT_OUTPUT_HEADERS
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

    ordered = arranger.arrange("2026-07")

    # 战营 #B 排最前，其次普通实战 #A，最后壳子 #C
    assert [x["player_tag"] for x in ordered] == ["#B", "#A", "#C"]
    assert ordered[0]["league_type"] == LEAGUE_COMBAT
    assert ordered[1]["league_type"] == LEAGUE_COMBAT
    assert ordered[2]["league_type"] == LEAGUE_SHELL


def test_arrange_writes_back_to_repo(player_service, reg_repo):
    _seed(player_service, reg_repo)
    arranger = LeagueArranger(player_service, reg_repo, FakeExcelIO())
    arranger.arrange("2026-07")

    regs = {r["player_tag"]: r for r in reg_repo.get_registrations("2026-07")}
    assert regs["#B"]["rank_order"] == 1
    assert regs["#B"]["league_type"] == LEAGUE_COMBAT
    assert regs["#C"]["league_type"] == LEAGUE_SHELL


def test_arrange_and_export_writes_sheet(player_service, reg_repo):
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = LeagueArranger(player_service, reg_repo, fake_io)

    ordered, sheet_name = arranger.arrange_and_export("2026-07", "名单.xlsx")

    assert sheet_name == "名单_2026-07"
    assert fake_io.last_written_target == "名单.xlsx"
    assert fake_io.last_written_sheet == "名单_2026-07"
    assert fake_io.last_written_headers == ARRANGEMENT_OUTPUT_HEADERS
    written_tags = [r["player_tag"] for r in fake_io.last_written_rows]
    assert written_tags == ["#B", "#A", "#C"]
