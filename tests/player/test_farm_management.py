from __future__ import annotations

import pytest

import api_server.routes as routes
from modules.player.farm_management import (
    farm_management_by_clan,
    parse_fill_account_rows,
    upsert_fill_accounts,
)


def _source_row(number: str, tag: str, name: str = "填坑号") -> dict:
    return {
        "账号编号": number,
        "账号名字": name,
        "大本等级": "18本",
        "所在部落名字+标签": "互刷一营 #FARM",
        "玩家标签": tag,
        "最后查询时间": "2026-10-04 10:06（查询失败）",
    }


def _records(rows: list[dict]) -> list[dict]:
    return parse_fill_account_rows(
        rows,
        source_doc_id="DOC",
        source_sheet_id="SHEET",
        source_sheet_title="账号查询",
        imported_at="2026-10-04T02:00:00+00:00",
    )


def test_fill_import_preserves_multiple_account_numbers_for_one_player(db):
    records = _records([
        _source_row("001", "#P1"),
        _source_row("002", "#P1"),
    ])
    assert upsert_fill_accounts(db.conn, records) == 2
    db.conn.commit()

    rows = db.conn.execute(
        "SELECT account_number, player_tag FROM farm_fill_accounts ORDER BY account_number"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("001", "#P1"), ("002", "#P1")]


def test_fill_import_rejects_duplicate_account_number():
    with pytest.raises(ValueError, match="账号编号重复"):
        _records([_source_row("001", "#P1"), _source_row("001", "#P2")])


def test_farm_management_uses_current_clan_and_excludes_fill_and_leader(db):
    db.conn.executemany(
        """INSERT INTO accounts
           (player_tag, account_name, town_hall_level, clan_tag, clan_role,
            membership_status, last_activity_at, activity_observed_since,
            last_synced_at)
           VALUES (?, ?, 18, ?, ?, 'member', ?, ?, '2026-10-04T01:00:00+00:00')""",
        [
            ("#P1", "填坑成员", "#FARM", "member", None, "2026-01-01T00:00:00+00:00"),
            ("#P2", "首领", "#FARM", "leader", None, "2025-01-01T00:00:00+00:00"),
            ("#P3", "未检测活动", "#FARM", "member", None, "2026-02-01T00:00:00+00:00"),
            ("#P4", "较早活动", "#FARM", "admin", "2026-03-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            ("#P5", "较新活动", "#FARM", "coLeader", "2026-04-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            ("#P6", "其他部落", "#OTHER", "member", None, "2025-01-01T00:00:00+00:00"),
        ],
    )
    upsert_fill_accounts(db.conn, _records([
        _source_row("001", "#P1"),
        _source_row("002", "#P1"),
    ]))
    db.conn.commit()

    result = farm_management_by_clan(db.conn, ["#FARM"])["#FARM"]

    assert len(result["fill_accounts"]) == 1
    assert result["fill_accounts"][0]["player_tag"] == "#P1"
    assert result["fill_accounts"][0]["account_numbers"] == ["001", "002"]
    assert [row["player_tag"] for row in result["inactive_members"]] == [
        "#P3", "#P4", "#P5",
    ]
    assert result["inactive_members"][0]["never_observed_activity"] is True


def test_farm_config_returns_management_lists_without_war_cache(db, monkeypatch):
    monkeypatch.setattr(routes, "get_farm_clans", lambda: [
        {"tag": "#FARM", "name": "互刷一营", "category": "farm", "enabled": True},
    ])
    db.conn.execute(
        """INSERT INTO accounts
           (player_tag, account_name, town_hall_level, clan_tag, clan_role,
            membership_status, activity_observed_since, last_synced_at)
           VALUES ('#P1', '填坑成员', 18, '#FARM', 'member', 'member',
                   '2026-01-01T00:00:00+00:00', '2026-10-04T01:00:00+00:00')"""
    )
    upsert_fill_accounts(db.conn, _records([_source_row("001", "#P1")]))
    db.conn.commit()

    response = routes.farm_config(db)

    assert response["updated_at"] is None
    assert response["member_updated_at"] == "2026-10-04T02:00:00+00:00"
    assert len(response["clans"]) == 1
    clan = response["clans"][0]
    assert clan["clan_tag"] == "#FARM"
    assert clan["despeed"]["has_war"] is False
    assert clan["fill_accounts"][0]["account_numbers"] == ["001"]
    assert clan["inactive_members"] == []
