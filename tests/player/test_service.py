"""PlayerService 测试：昵称反查真实 Tag / COC 更新不覆盖战绩组。"""
from __future__ import annotations


def test_resolve_finds_coc_account(player_service):
    player_service.update_from_coc({"player_tag": "#A", "account_name": "甲"})
    assert player_service.resolve_tag_by_name("甲") == "#A"


def test_resolve_fallback_to_tag_equals_name(player_service):
    # 账号 account_name 与查询名不同，但 tag 恰等于查询名（兼容老/测试数据）
    player_service.update_from_coc({"player_tag": "甲号", "account_name": "别名"})
    assert player_service.resolve_tag_by_name("甲号") == "甲号"


def test_resolve_none_when_absent(player_service):
    # "报名有 / COC 无"的新人本就没有账号，返回 None 属正常
    assert player_service.resolve_tag_by_name("查无此人") is None
    assert player_service.resolve_tag_by_name("") is None


def test_resolve_multiple_real_warns_and_takes_first(player_service, capsys):
    player_service.update_from_coc({"player_tag": "#A", "account_name": "重名"})
    player_service.update_from_coc({"player_tag": "#B", "account_name": "重名"})
    tag = player_service.resolve_tag_by_name("重名")
    assert tag in {"#A", "#B"}
    assert "多个 COC 账号" in capsys.readouterr().err


def test_update_from_coc_does_not_touch_score_group(player_service):
    # 先有战绩组（history_score）
    player_service.update_from_coc({"player_tag": "#A", "account_name": "甲"})
    player_service.update_history_score("#A", 42.0)
    # COC 更新只写 COC 组，不覆盖历史分（COALESCE 分组语义）
    player_service.update_from_coc({"player_tag": "#A", "account_name": "甲", "trophies": 5000})

    acc = player_service.get("#A")
    assert acc["trophies"] == 5000
    assert acc["history_score"] == 42.0          # 战绩组保留
