"""集成测试：导入战绩（war_result）。

补齐原先零覆盖的战绩导入测试（隐患 #9），并验证三个战绩相关修复：
- #1 同 (tag, period, league_type) 重复导入覆盖而非累积。
- #2 未知账号（无档案）跳过 + 告警，不因外键整批失败。
- #3 战绩表用关键词映射取 tag（游戏昵称，与报名侧一致），列名漂移也能命中。
"""
from __future__ import annotations

from modules.war_result.importer import ResultImporter, parse_result_row
from tests.fakes import FakeExcelIO


def _result_row(nick, league="实战", **metrics):
    row = {
        "游戏昵称": nick,
        "联赛类型": league,
    }
    row.update(metrics)
    return row


def _seed_account(player_service, tag, name="某号"):
    # 账号只由 COC 权威建档；此处直接建真实账号供战绩按昵称反查关联。
    player_service.update_from_coc({"player_tag": tag, "account_name": name})


def test_parse_result_row_keyword_mapping_and_tag_source():
    # #3：tag 从"游戏昵称"取，联赛类型关键词命中，其余列进 raw_metrics
    parsed = parse_result_row(_result_row("甲号", league="壳子", 星星=30, 摧毁率=95))
    assert parsed["player_tag"] == "甲号"
    assert parsed["league_type"] == "壳子"
    assert parsed["raw_metrics"] == {"星星": 30, "摧毁率": 95}


def test_parse_result_row_missing_tag_returns_none():
    assert parse_result_row({"联赛类型": "实战", "星星": 10}) is None


def test_import_updates_history_score_for_known_account(player_service, result_repo):
    _seed_account(player_service, "甲号")
    rows = [_result_row("甲号", 星星=30)]
    n = ResultImporter(player_service, result_repo, FakeExcelIO(rows)).import_from("r.xlsx", "2026-07")

    assert n == 1
    assert len(result_repo.get_results("甲号")) == 1
    # 占位历史分函数当前回写 0.0
    assert player_service.get("甲号")["history_score"] == 0.0


def test_import_skips_unknown_account_with_warning(player_service, result_repo, capsys):
    # #2：账号档案不存在 -> 跳过并告警，不抛外键错误
    rows = [_result_row("陌生号", 星星=10)]
    n = ResultImporter(player_service, result_repo, FakeExcelIO(rows)).import_from("r.xlsx", "2026-07")

    assert n == 0
    assert result_repo.get_results("陌生号") == []
    err = capsys.readouterr().err
    assert "不存在" in err


def test_reimport_same_period_type_overwrites(player_service, result_repo):
    # #1：同 (tag, period, league_type) 重复导入覆盖而非累积
    _seed_account(player_service, "甲号")
    ResultImporter(player_service, result_repo, FakeExcelIO([_result_row("甲号", league="实战", 星星=10)])).import_from("r.xlsx", "2026-07")
    ResultImporter(player_service, result_repo, FakeExcelIO([_result_row("甲号", league="实战", 星星=99)])).import_from("r.xlsx", "2026-07")

    results = result_repo.get_results("甲号")
    assert len(results) == 1
    assert results[0]["raw_metrics"]["星星"] == 99


def test_mixed_known_and_unknown_partial_import(player_service, result_repo, capsys):
    _seed_account(player_service, "甲号")
    rows = [_result_row("甲号", 星星=10), _result_row("陌生号", 星星=20)]
    n = ResultImporter(player_service, result_repo, FakeExcelIO(rows)).import_from("r.xlsx", "2026-07")

    # 已知账号导入成功，未知账号跳过
    assert n == 1
    assert len(result_repo.get_results("甲号")) == 1
    assert result_repo.get_results("陌生号") == []
