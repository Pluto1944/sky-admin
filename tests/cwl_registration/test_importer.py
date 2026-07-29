"""集成测试：导入报名（多账号 + 战营名单合并 + 去重）。

使用真实内存 Database 装配的 player_service / reg_repo（见 conftest），注入 FakeExcelIO。
"""
from __future__ import annotations

from modules.cwl_registration.importer import (
    RegistrationImporter,
    _fill_player_name_forward,
    parse_registration_row,
)
from shared.config.common import (
    ACCOUNT_TYPE_COMBAT,
    ACCOUNT_TYPE_NORMAL,
    STATUS_ACTIVE,
    STATUS_MAYBE_LEFT,
    STATUS_MISSED,
)
from tests.fakes import FakeExcelIO


# 真实风格表头（含关键词，供关键词映射解析）
def _reg_row(account_name, match_value, join_combat, player_name="主号A", submit_time=None):
    return {
        "提交时间（自动）": submit_time,
        "主号游戏昵称 or 微信名（必填）": player_name,
        "需要安排联赛的账号（必填）\n游戏昵称（必填）": account_name,
        "需要安排联赛的账号（必填）\n匹配值（必填）": match_value,
        "需要安排联赛的账号（必填）\n想实战？（必填）": join_combat,
    }


def _camp_row(nick):
    # 兼容保留（战营名单已改为从部落 DB 拉取，不再从 Excel sheet 读）
    return {"冲杯！！！！！！！！！！！": nick}


def _seed_camp_members(player_service, names):
    """把给定昵称预置为战营部落 #2QQ 的 COC 成员（战营名单新数据源）。"""
    from modules.cwl_registration.config import CAMP_CLAN_TAG

    for i, name in enumerate(names, start=1):
        player_service.update_from_coc(
            {"player_tag": f"#CAMP{i}", "account_name": name, "clan_tag": CAMP_CLAN_TAG}
        )


def test_parse_registration_row_keyword_mapping():
    reg = parse_registration_row(_reg_row("甲号", "88.5", "是", player_name="张三"))
    assert reg["account_name"] == "甲号"
    assert "player_tag" not in reg          # 解析阶段不再产出 tag，统一由 _save 反查回填
    assert reg["player_name"] == "张三"
    assert reg["match_value"] == 88.5
    assert reg["join_combat"] is True
    assert reg["account_type"] == ACCOUNT_TYPE_NORMAL


def test_parse_registration_row_missing_account_name_returns_none():
    assert parse_registration_row(_reg_row(None, 100, "是")) is None


# ---- 主号向前填充兜底（源表未真·合并单元格时）----

def _parsed(player_name, account_name="账号", match_value=100, join_combat="是"):
    return parse_registration_row(
        _reg_row(account_name, match_value, join_combat, player_name=player_name)
    )


def test_fill_player_name_forward_same_group():
    # 一组多账号：首行有主号，后续同组空 -> 向前填充
    recs = [
        _parsed("张三", account_name="甲"),
        _parsed(None, account_name="乙"),
        _parsed(None, account_name="丙"),
    ]
    out = _fill_player_name_forward(recs)
    assert [r["player_name"] for r in out] == ["张三", "张三", "张三"]
    assert [r["account_name"] for r in out] == ["甲", "乙", "丙"]


def test_fill_player_name_forward_multiple_groups_isolated():
    # 两组：各自首行有主号，互不串组
    recs = [
        _parsed("张三", account_name="甲"),
        _parsed(None, account_name="乙"),
        _parsed("李四", account_name="丙"),
        _parsed(None, account_name="丁"),
    ]
    out = _fill_player_name_forward(recs)
    assert [r["player_name"] for r in out] == ["张三", "张三", "李四", "李四"]


def test_fill_player_name_forward_first_row_empty_stays_empty():
    # 首行即空、前方无主号 -> 保持空（不向前跨组误并）
    recs = [
        _parsed(None, account_name="甲"),
        _parsed("张三", account_name="乙"),
    ]
    out = _fill_player_name_forward(recs)
    assert out[0]["player_name"] is None
    assert out[1]["player_name"] == "张三"


def test_fill_player_name_forward_empty_records_unchanged():
    assert _fill_player_name_forward([]) == []


def test_import_fills_player_name_for_unmerged_group(player_service, reg_repo):
    # 端到端：报名表"一对多"只视觉留空（没真合并），首行有主号、后续空
    rows = [
        _reg_row("甲", 90, "是", player_name="张三"),
        _reg_row("乙", 80, "否", player_name=None),
        _reg_row("丙", 70, "否", player_name=None),
        _reg_row("丁", 60, "是", player_name="李四"),
        _reg_row("戊", 50, "否", player_name=None),
    ]
    RegistrationImporter(
        player_service, reg_repo, FakeExcelIO(rows)
    ).import_from("d.xlsx", "2026-07")

    regs = {r["account_name"]: r for r in reg_repo.get_registrations("2026-07")}
    assert regs["甲"]["player_name"] == "张三"
    assert regs["乙"]["player_name"] == "张三"   # 向前填充命中同组
    assert regs["丙"]["player_name"] == "张三"
    assert regs["丁"]["player_name"] == "李四"
    assert regs["戊"]["player_name"] == "李四"


def test_import_normal_accounts_only(player_service, reg_repo):
    rows = [_reg_row("甲", 90, "是"), _reg_row("乙", 80, "否")]
    # 单 sheet 模式：战营名单读到同批数据但无"战营"列 -> 视为无战营
    n = RegistrationImporter(player_service, reg_repo, FakeExcelIO(rows)).import_from("d.xlsx", "2026-07")

    assert n == 2
    regs = {r["account_name"]: r for r in reg_repo.get_registrations("2026-07")}
    assert regs["甲"]["account_type"] == ACCOUNT_TYPE_NORMAL   # 账号类型落子表
    assert regs["甲"]["player_tag"] is None                    # 新人未命中账号，tag 缓存为空
    assert player_service.get("甲") is None                    # B 方案：报名不建行
    assert len(reg_repo.get_registrations("2026-07")) == 2


def test_camp_merge_priority_and_forced_combat(player_service, reg_repo):
    # 战营名单改为从部落 #2QQ 拉取：预置 战A、战C 为部落成员（战C 未报名）
    _seed_camp_members(player_service, ["战A", "战C"])
    reg_rows = [
        _reg_row("战A", 500, "否"),   # 战营成员也报名到普通部落、且填了不想实战
        _reg_row("普B", 700, "是"),
    ]
    io = FakeExcelIO(sheets={"报名": reg_rows})

    n = RegistrationImporter(player_service, reg_repo, io).import_from("d.xlsx", "2026-07", sheet="报名")

    regs = {r["account_name"]: r for r in reg_repo.get_registrations("2026-07")}
    # 战A：战营优先 -> combat、强制实战、匹配值取报名表值（均落子表）
    assert regs["战A"]["account_type"] == ACCOUNT_TYPE_COMBAT
    assert regs["战A"]["match_value"] == 500
    assert regs["战A"]["join_combat"] == 1  # 被强制实战

    # 普B：普通账号
    assert regs["普B"]["account_type"] == ACCOUNT_TYPE_NORMAL

    # 战C：未报名也纳入报名快照，combat、无匹配值
    assert regs["战C"]["account_type"] == ACCOUNT_TYPE_COMBAT
    assert regs["战C"]["match_value"] is None
    assert n == 3


def test_dedup_keeps_latest_submit(player_service, reg_repo, capsys):
    rows = [
        _reg_row("重名", 100, "是", submit_time="2026-06-01 09:00:00"),
        _reg_row("重名", 200, "否", submit_time="2026-06-20 18:00:00"),  # 更新
    ]
    n = RegistrationImporter(player_service, reg_repo, FakeExcelIO(rows)).import_from("d.xlsx", "2026-07")

    assert n == 1
    reg = [r for r in reg_repo.get_registrations("2026-07") if r["account_name"] == "重名"][0]
    assert reg["match_value"] == 200  # 取最新一条
    err = capsys.readouterr().err
    assert "重复账号名" in err  # 打印了告警


def test_reimport_same_period_no_duplicate(player_service, reg_repo):
    rows = [_reg_row("甲", 50, "否")]
    RegistrationImporter(player_service, reg_repo, FakeExcelIO(rows)).import_from("d.xlsx", "2026-07")
    RegistrationImporter(player_service, reg_repo, FakeExcelIO(rows)).import_from("d.xlsx", "2026-07")
    assert len(reg_repo.get_registrations("2026-07")) == 1


def test_import_updates_status_for_registered_coc_accounts(player_service, reg_repo):
    # 报名维度状态跟踪真实账号：先有 COC 账号 #A(甲)/#B(乙)
    player_service.update_from_coc({"player_tag": "#A", "account_name": "甲"})
    player_service.update_from_coc({"player_tag": "#B", "account_name": "乙"})

    RegistrationImporter(player_service, reg_repo, FakeExcelIO([_reg_row("甲", 50, "否"), _reg_row("乙", 50, "否")])).import_from("d.xlsx", "2026-06")
    RegistrationImporter(player_service, reg_repo, FakeExcelIO([_reg_row("甲", 50, "否")])).import_from("d.xlsx", "2026-07")

    assert player_service.get("#A")["status"] == STATUS_ACTIVE
    assert player_service.get("#B")["status"] == STATUS_MISSED  # 上次 2026-06 报名，间隔 1 月

    RegistrationImporter(player_service, reg_repo, FakeExcelIO([_reg_row("甲", 50, "否")])).import_from("d.xlsx", "2026-08")
    assert player_service.get("#B")["status"] == STATUS_MAYBE_LEFT  # 间隔达 2 月


def test_registration_resolves_to_existing_coc_account(player_service, reg_repo):
    # 已有 COC 真实账号（昵称"甲"，tag=#A）；报名按昵称解析应把真实 tag 缓存进报名行
    player_service.update_from_coc({"player_tag": "#A", "account_name": "甲", "trophies": 3000})

    n = RegistrationImporter(
        player_service, reg_repo, FakeExcelIO([_reg_row("甲", 66, "是")])
    ).import_from("d.xlsx", "2026-07")

    assert n == 1
    real = player_service.get("#A")
    assert real["trophies"] == 3000                    # COC 组保留，未被报名触碰
    regs = reg_repo.get_registrations("2026-07")
    assert [r["account_name"] for r in regs] == ["甲"]
    assert regs[0]["player_tag"] == "#A"               # 命中真实账号，tag 缓存回填
    assert regs[0]["match_value"] == 66                # 报名匹配值落子表


def test_unmatched_registration_stored_without_account(player_service, reg_repo):
    # B 方案：昵称匹配不到 COC 账号（新人）-> 照常落报名快照，但不在主表建任何行
    RegistrationImporter(
        player_service, reg_repo, FakeExcelIO([_reg_row("新人", 70, "是")])
    ).import_from("d.xlsx", "2026-07")

    assert player_service.get("新人") is None              # 未建账号（不污染主表）
    assert player_service.resolve_tag_by_name("新人") is None
    reg = [r for r in reg_repo.get_registrations("2026-07") if r["account_name"] == "新人"][0]
    assert reg["match_value"] == 70
    assert reg["player_tag"] is None                       # 未命中，tag 缓存为空
