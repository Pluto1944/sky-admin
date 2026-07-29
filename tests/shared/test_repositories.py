"""数据访问层测试：PlayerRepository / RegistrationRepository / ResultRepository
（基于共享内存 Database，验证外键与唯一约束）。"""
from __future__ import annotations


def _acc(tag, **kw):
    base = {
        "player_tag": tag,
        "account_name": "n",
        "player_name": "p",
        "status": "active",
    }
    base.update(kw)
    return base


def test_insert_and_get_account(player_repo):
    player_repo.upsert(_acc("#A"))
    acc = player_repo.get("#A")
    assert acc is not None
    assert acc["player_tag"] == "#A"
    assert acc["status"] == "active"


def test_upsert_updates_existing(player_repo):
    player_repo.upsert(_acc("#A", account_name="old"))
    player_repo.upsert(_acc("#A", account_name="new"))
    assert player_repo.get("#A")["account_name"] == "new"
    assert len(player_repo.list_all()) == 1


def test_registration_unique_constraint_prevents_duplicates(reg_repo):
    # B 方案：registrations 以 (account_name, period) 唯一，无需 accounts 存在（无 FK）
    reg_repo.add_registration({"account_name": "甲", "period": "2026-07", "match_value": 10, "join_combat": True})
    # 重复导入同 (account_name, period) 应更新而非新增
    reg_repo.add_registration({"account_name": "甲", "period": "2026-07", "match_value": 99, "join_combat": False})
    regs = reg_repo.get_registrations("2026-07")
    assert len(regs) == 1
    assert regs[0]["match_value"] == 99


def test_update_history_score(player_repo):
    player_repo.upsert(_acc("#A"))
    player_repo.update_history_score("#A", 42.5)
    assert player_repo.get("#A")["history_score"] == 42.5


def test_upsert_does_not_reset_history_score(player_repo):
    player_repo.upsert(_acc("#A"))
    player_repo.update_history_score("#A", 88.0)
    # 再次报名导入（upsert）不应把历史分清零
    player_repo.upsert(_acc("#A", account_name="changed"))
    assert player_repo.get("#A")["history_score"] == 88.0


def test_results_roundtrip_json(player_repo, result_repo):
    player_repo.upsert(_acc("#A"))
    result_repo.add_result({"player_tag": "#A", "period": "2026-07",
                            "league_type": "combat", "raw_metrics": {"star": 12, "win": 5}})
    results = result_repo.get_results("#A")
    assert len(results) == 1
    assert results[0]["raw_metrics"] == {"star": 12, "win": 5}


def test_results_unique_constraint_upserts(player_repo, result_repo):
    # 修复 #1：同 (tag, period, league_type) 重复导入覆盖而非累积
    player_repo.upsert(_acc("#A"))
    result_repo.add_result({"player_tag": "#A", "period": "2026-07",
                            "league_type": "combat", "raw_metrics": {"star": 10}})
    result_repo.add_result({"player_tag": "#A", "period": "2026-07",
                            "league_type": "combat", "raw_metrics": {"star": 20}})
    results = result_repo.get_results("#A")
    assert len(results) == 1
    assert results[0]["raw_metrics"] == {"star": 20}


def test_update_registration_arrangement(reg_repo):
    rid = reg_repo.add_registration({"account_name": "甲", "period": "2026-07", "match_value": 10, "join_combat": True})
    reg_repo.update_arrangement(rid, "combat", 1)
    reg = reg_repo.get_registrations("2026-07")[0]
    assert reg["league_type"] == "combat"
    assert reg["rank_order"] == 1


# --- 字段分组 upsert（COALESCE）：COC 组与账号级报名字段互不覆盖 -------------

def test_partial_upsert_does_not_null_other_fields(player_repo):
    # 先写账号级报名字段（status）
    player_repo.upsert({"player_tag": "#A", "account_name": "n",
                        "status": "active", "player_name": "p"})
    # 再只写 COC 组（不传报名字段）：报名字段应保持原样，不被清空
    player_repo.upsert({"player_tag": "#A", "trophies": 3000, "clan_tag": "#C", "exp_level": 200})
    acc = player_repo.get("#A")
    assert acc["trophies"] == 3000
    assert acc["clan_tag"] == "#C"
    assert acc["status"] == "active"     # 报名组未被清空
    assert acc["player_name"] == "p"


def test_find_by_name(player_repo):
    player_repo.upsert({"player_tag": "#A", "account_name": "同名"})
    player_repo.upsert({"player_tag": "#B", "account_name": "同名"})
    player_repo.upsert({"player_tag": "#C", "account_name": "唯一"})
    assert {a["player_tag"] for a in player_repo.find_by_name("同名")} == {"#A", "#B"}
    assert len(player_repo.find_by_name("唯一")) == 1
    assert player_repo.find_by_name("不存在") == []
