"""PlayerExporter 测试：筛选 / 排序 / 中文表头映射 / 写出参数。"""
from __future__ import annotations

from modules.player.config import PLAYER_EXPORT_COLUMNS, PLAYER_EXPORT_SHEET
from modules.player.exporter import PlayerExporter
from shared.config.common import MEMBERSHIP_LEFT, MEMBERSHIP_MEMBER
from tests.fakes import FakeExcelIO


def _seed(player_service, reg_repo):
    """三个账号：不同历史分 / 状态 / 部落身份，覆盖排序与筛选。

    账号均由 COC 权威建档；A/B 本月报名（供 last_reg_period 派生 + active 状态），
    丙有账号但未报名（历史分默认 0、无报名月份）。
    """
    player_service.update_from_coc({"player_tag": "#A", "account_name": "甲"})
    reg_repo.add_registration({"account_name": "甲", "period": "2026-07"})
    player_service.update_from_coc({"player_tag": "#B", "account_name": "乙"})
    reg_repo.add_registration({"account_name": "乙", "period": "2026-07"})
    player_service.update_from_coc({"player_tag": "丙", "account_name": "丙"})  # 未报名
    player_service.update_history_score("#A", 10.0)
    player_service.update_history_score("#B", 30.0)
    # membership：B 退部，A 默认 member
    player_service.mark_left_alliance("#B", new_clan_tag="#OUT")
    # 报名维度状态：甲/乙 本月报名 -> active；丙未报名
    player_service.refresh_status("2026-07", {"甲", "乙"})


def test_export_default_sort_desc_by_history_score(player_service, reg_repo):
    _seed(player_service, reg_repo)
    io = FakeExcelIO()
    exporter = PlayerExporter(player_service, io)
    n, sheet = exporter.export("out.xlsx")

    assert n == 3
    assert sheet == PLAYER_EXPORT_SHEET
    # 表头为中文、顺序与配置一致
    assert io.last_written_headers == list(PLAYER_EXPORT_COLUMNS.values())
    # 历史分降序：B(30) > A(10) > 丙(None 排末尾)
    tags = [r["玩家Tag"] for r in io.last_written_rows]
    assert tags == ["#B", "#A", "丙"]
    # 写出开启自动筛选 + 冻结首行
    assert io.last_written_auto_filter is True
    assert io.last_written_freeze_header is True


def test_export_ascending(player_service, reg_repo):
    _seed(player_service, reg_repo)
    io = FakeExcelIO()
    rows, _ = PlayerExporter(player_service, io).build_rows(descending=False)
    tags = [r["玩家Tag"] for r in rows]
    # 升序：丙(0，未报名账号历史分默认 0) < A(10) < B(30)
    assert tags == ["丙", "#A", "#B"]


def test_sort_by_nullable_field_puts_none_last(player_service, reg_repo):
    _seed(player_service, reg_repo)
    io = FakeExcelIO()
    exporter = PlayerExporter(player_service, io)
    # 按 last_reg_period 排序：丙未报名该字段为 None，升/降序都排末尾
    asc = [r["玩家Tag"] for r in exporter.build_rows(
        sort_by="last_reg_period", descending=False)[0]]
    desc = [r["玩家Tag"] for r in exporter.build_rows(
        sort_by="last_reg_period", descending=True)[0]]
    assert asc[-1] == "丙"
    assert desc[-1] == "丙"


def test_export_filter_by_status(player_service, reg_repo):
    _seed(player_service, reg_repo)
    io = FakeExcelIO()
    # 只有本月报名的 A/B 是 active；丙未报名
    rows, _ = PlayerExporter(player_service, io).build_rows(status="active")
    assert {r["玩家Tag"] for r in rows} == {"#A", "#B"}


def test_export_filter_by_membership(player_service, reg_repo):
    _seed(player_service, reg_repo)
    io = FakeExcelIO()
    exporter = PlayerExporter(player_service, io)

    members = exporter.build_rows(membership_status=MEMBERSHIP_MEMBER)[0]
    left = exporter.build_rows(membership_status=MEMBERSHIP_LEFT)[0]
    # A/丙 默认 member，B 已退部
    assert {r["玩家Tag"] for r in members} == {"#A", "丙"}
    assert {r["玩家Tag"] for r in left} == {"#B"}


def test_export_maps_fields_to_chinese_headers(player_service, reg_repo):
    _seed(player_service, reg_repo)
    io = FakeExcelIO()
    rows, _ = PlayerExporter(player_service, io).build_rows()
    top = rows[0]  # #B
    assert top["游戏昵称"] == "乙"
    assert top["历史分"] == 30.0
    assert top["部落身份"] == MEMBERSHIP_LEFT
    # 行的 key 只包含配置的中文表头
    assert set(top.keys()) == set(PLAYER_EXPORT_COLUMNS.values())
