import json

import pytest
from fastapi import HTTPException

import api_server.routes as routes
from modules.coc_sync.cwl_assembly import (
    compare_roster_members,
    normalize_roster_name,
    parse_published_roster,
    published_sheet_name,
)


def _team(index=0, tag="#AAA", category="combat", count=15):
    return {
        "period": "2026-10",
        "team_index": index,
        "team_alias": "冠三" if category == "combat" else "大一",
        "team_name": "测试部落",
        "clan_tag": tag,
        "category": category,
        "member_count": count,
    }


def test_sheet_name_and_shell_score_normalization():
    assert published_sheet_name("2026-10") == "26.10月联赛 报名结果"
    assert normalize_roster_name(" 玩家 A 123.5 ", "shell") == "玩家 A"
    assert normalize_roster_name(" 玩家 A 123.5 ", "combat") == "玩家 A 123.5"


def test_parse_published_roster_uses_part4_member_rows():
    rows = [
        {"苍穹联赛报名": "说明", "col1": "", "col2": "", "col3": "", "col4": ""},
        {"苍穹联赛报名": "实战:冠三 15/15", "col1": "#AAA", "col2": "部落名", "col3": "首领", "col4": "管理"},
        {"苍穹联赛报名": "甲", "col1": "乙", "col2": "丙", "col3": "丁", "col4": "戊"},
        {"苍穹联赛报名": "己", "col1": "庚", "col2": "辛", "col3": "壬", "col4": "癸"},
        {"苍穹联赛报名": "子", "col1": "丑", "col2": "寅", "col3": "卯", "col4": "辰"},
        {"苍穹联赛报名": "不应读取", "col1": "尾注", "col2": "", "col3": "", "col4": ""},
    ]
    roster = parse_published_roster(rows, [_team()])
    assert roster["teams"][0]["members"] == [
        "甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸", "子", "丑", "寅", "卯", "辰",
    ]


def test_parse_shell_roster_strips_scores_and_rejects_missing_heading():
    rows = [
        {"苍穹联赛报名": "壳子:大一 10/30", "col1": "#BBB", "col2": "部落", "col3": "", "col4": ""},
        {"苍穹联赛报名": "甲 123", "col1": "乙 88.5", "col2": "", "col3": "", "col4": ""},
    ]
    roster = parse_published_roster(rows, [_team(tag="#BBB", category="shell", count=5)])
    assert roster["teams"][0]["members"] == ["甲", "乙"]
    with pytest.raises(ValueError, match="抬头出现 0 次"):
        parse_published_roster(rows, [_team(tag="#AAA")])


def test_compare_roster_members_preserves_duplicate_counts():
    result = compare_roster_members(
        ["同名", "同名", "缺席"],
        [
            {"account_name": "同名", "player_tag": "#A", "clan_role": "member", "town_hall_level": 16},
            {"account_name": "额外", "player_tag": "#B", "clan_role": "admin", "town_hall_level": 17},
        ],
    )
    assert result["present_count"] == 1
    assert [item["name"] for item in result["missing_members"]] == ["同名", "缺席"]
    assert result["extra_members"][0]["name"] == "额外"
    assert result["extra_members"][0]["role"] == "admin"


def _seed_api(db):
    team = _team()
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category, member_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            team["period"], team["team_index"], team["team_alias"], team["team_name"],
            team["clan_tag"], team["category"], team["member_count"],
        ),
    )
    roster = {"teams": [{**team, "members": ["甲", "乙"]}]}
    cursor = db.conn.execute(
        """INSERT INTO cwl_roster_snapshots
           (period, revision, is_active, source_sheet, content_hash, data_json, created_at)
           VALUES ('2026-10', 1, 1, 'sheet', 'hash', ?, '2026-10-01T06:00:00+00:00')""",
        (json.dumps(roster, ensure_ascii=False),),
    )
    payload = compare_roster_members(
        ["甲", "乙"],
        [{"account_name": "甲", "player_tag": "#P1", "clan_role": "leader", "town_hall_level": 18}],
    )
    db.conn.execute(
        """INSERT INTO cwl_assembly_cache
           (period, clan_tag, roster_snapshot_id, team_index, team_alias, team_name,
            category, status, data_json, updated_at, attempted_at)
           VALUES ('2026-10', '#AAA', ?, 0, '冠三', '测试部落', 'combat',
                   'checking', ?, '2026-10-01T06:05:00+00:00', '2026-10-01T06:05:00+00:00')""",
        (cursor.lastrowid, json.dumps(payload, ensure_ascii=False)),
    )
    db.conn.commit()


def test_assembly_summary_and_detail_read_only_cache(db, monkeypatch):
    _seed_api(db)
    monkeypatch.setattr(routes, "_current_cwl_live_period", lambda: "2026-10")

    summary = routes.cwl_assembly(db)
    assert summary["status"] == "ready"
    assert summary["summary"]["missing_count"] == 1
    assert summary["teams"][0]["present_count"] == 1

    detail = routes.cwl_assembly_detail("#aaa", db)
    assert detail["snapshot_revision"] == 1
    assert detail["missing_members"][0]["name"] == "乙"
    assert detail["present_members"][0]["town_hall_level"] == 18

    with pytest.raises(HTTPException) as exc:
        routes.cwl_assembly_detail("#OUT", db)
    assert exc.value.status_code == 404


def test_assembly_summary_reports_waiting_roster(db, monkeypatch):
    team = _team()
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category, member_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        tuple(team[key] for key in (
            "period", "team_index", "team_alias", "team_name", "clan_tag", "category", "member_count",
        )),
    )
    db.conn.commit()
    monkeypatch.setattr(routes, "_current_cwl_live_period", lambda: "2026-10")
    result = routes.cwl_assembly(db)
    assert result["status"] == "waiting_roster"
    assert result["teams"][0]["status"] == "waiting_check"
