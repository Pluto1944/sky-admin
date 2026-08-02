"""mapper 纯函数测试：COC 原始成员 dict -> player 档案 COC 组字段。"""
from __future__ import annotations

import json

from modules.coc_sync.official.mapper import map_member
from tests.fakes import coc_member


def test_map_member_basic_fields():
    m = coc_member("#abc123", "甲号", role="coLeader", exp=210, trophies=5200, th=16, league="冠军联赛3")
    out = map_member(m, "#2QQ", clan_name="苍穹一部")

    assert out["player_tag"] == "#ABC123"        # 规范化为大写、带 '#'
    assert out["account_name"] == "甲号"
    assert out["exp_level"] == 210
    assert out["trophies"] == 5200
    assert out["town_hall_level"] == 16
    assert out["league_name"] == "冠军联赛3"
    assert out["clan_tag"] == "#2QQ"
    assert out["clan_role"] == "coLeader"


def test_map_member_tag_normalization_without_hash():
    out = map_member({"tag": "pp0", "name": "n"}, "2qq")
    assert out["player_tag"] == "#PP0"
    assert out["clan_tag"] == "#2QQ"


def test_map_member_missing_league_and_fields():
    out = map_member({"tag": "#X", "name": "n"}, "#C")
    assert out["league_name"] is None
    assert out["trophies"] is None
    assert out["town_hall_level"] is None


def test_map_member_coc_raw_is_json_with_clan_context():
    m = coc_member("#X", "n")
    out = map_member(m, "#C", clan_name="部落名")
    raw = json.loads(out["coc_raw"])
    assert raw["tag"] == "#X"
    assert raw["_clan_tag"] == "#C"
    assert raw["_clan_name"] == "部落名"
