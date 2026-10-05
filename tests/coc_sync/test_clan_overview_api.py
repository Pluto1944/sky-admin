import json

import pytest
from fastapi import HTTPException

import api_server.routes as routes


def _insert_member(
    db,
    tag,
    name,
    clan_tag,
    town_hall,
    role="member",
    membership_status="member",
    donations=0,
    received=0,
    trophies=0,
    synced_at="2026-09-30T01:00:00+00:00",
):
    db.conn.execute(
        """INSERT INTO accounts
           (player_tag, account_name, town_hall_level, trophies, clan_tag, clan_role,
            coc_raw, last_synced_at, membership_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tag,
            name,
            town_hall,
            trophies,
            clan_tag,
            role,
            json.dumps({"donations": donations, "donationsReceived": received}),
            synced_at,
            membership_status,
        ),
    )
    db.conn.commit()


def test_clan_overview_preserves_config_order_and_aggregates_current_members(db, monkeypatch):
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#BBB", "name": "二队", "category": "farm", "enabled": True},
        {"tag": "#AAA", "name": "一队", "category": "combat", "enabled": True},
        {"tag": "#OFF", "name": "停用", "category": "normal", "enabled": False},
    ])
    _insert_member(db, "#P1", "首领", "#AAA", 18, "leader", donations=120, received=30, trophies=5000)
    _insert_member(
        db, "#P2", "成员", "#AAA", 16, "member", donations=80, received=70,
        synced_at="2026-09-30T02:00:00+00:00", trophies=4000,
    )
    _insert_member(db, "#P3", "已离开", "#AAA", 17, membership_status="left", donations=999)
    _insert_member(db, "#P4", "外部成员", "#OUT", 18, donations=999)

    response = routes.clan_overview(db)

    assert [item["clan_tag"] for item in response["clans"]] == ["#BBB", "#AAA"]
    assert response["clans"][0]["member_count"] == 0
    assert response["clans"][0]["category_label"] == "互刷"
    assert response["clans"][1] == {
        "clan_tag": "#AAA",
        "clan_name": "一队",
        "category": "combat",
        "category_label": "战营",
        "config_order": 1,
        "member_count": 2,
        "capacity": 50,
        "leader_name": "首领",
        "average_town_hall": 17.0,
        "average_trophies": 4500,
        "total_donations": 200,
        "updated_at": "2026-09-30T02:00:00+00:00",
        "war_status": {
            "status": "sync_pending", "updated_at": None,
            "attempted_at": None, "error": None,
        },
        "capital_status": {
            "status": "sync_pending", "raid_state": None,
            "weekend_start": None, "weekend_end": None,
            "updated_at": None, "attempted_at": None, "error": None,
        },
    }
    assert response["updated_at"] == "2026-09-30T02:00:00+00:00"


def test_clan_overview_includes_cached_war_and_capital_status(db, monkeypatch):
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#AAA", "name": "一队", "category": "combat", "enabled": True},
    ])
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, error, updated_at,
            attempted_at)
           VALUES ('#AAA', '一队', 'combat', 'preparation', '{}', NULL, ?, ?)""",
        ("2026-10-02T08:00:00+00:00", "2026-10-02T08:00:00+00:00"),
    )
    db.conn.execute(
        """INSERT INTO capital_raid_status_cache
           (clan_tag, clan_name, status, raid_state, weekend_start, weekend_end,
            error, updated_at, attempted_at)
           VALUES ('#AAA', '一队', 'not_started', NULL, ?, ?, NULL, ?, ?)""",
        (
            "2026-10-02T07:00:00+00:00", "2026-10-05T07:00:00+00:00",
            "2026-10-02T08:00:00+00:00", "2026-10-02T08:00:00+00:00",
        ),
    )
    db.conn.commit()

    clan = routes.clan_overview(db)["clans"][0]

    assert clan["war_status"]["status"] == "preparation"
    assert clan["capital_status"]["status"] == "not_started"
    assert clan["capital_status"]["weekend_end"] == "2026-10-05T07:00:00+00:00"


def test_clan_overview_detail_returns_distributions_and_rejects_external_clan(db, monkeypatch):
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#AAA", "name": "一队", "category": "normal", "enabled": True},
    ])
    _insert_member(db, "#P1", "首领", "#AAA", 18, "leader", donations=100, received=40)
    _insert_member(db, "#P2", "副首领", "#AAA", 18, "coLeader", donations=50, received=20)
    _insert_member(db, "#P3", "成员", "#AAA", 17, "member", donations=0, received=10)
    profile = {
        "clan_tag": "#AAA", "name": "一队", "clan_level": 25,
        "official_member_count": 3, "join_type": "inviteOnly",
        "war_wins": 131, "badge_urls": {"medium": "https://example.com/badge.png"},
        "labels": [{"id": 1, "name": "Clan Wars", "icon_urls": {}}],
        "synced_at": "2026-09-30T03:00:00+00:00",
    }
    db.conn.execute(
        """INSERT INTO clan_profile_cache
           (clan_tag, clan_name, category, status, data_json, updated_at, attempted_at)
           VALUES (?, ?, ?, 'success', ?, ?, ?)""",
        ("#AAA", "一队", "normal", json.dumps(profile), profile["synced_at"], profile["synced_at"]),
    )
    db.conn.commit()

    detail = routes.clan_overview_detail("#aaa", db)

    assert detail["town_hall_distribution"] == [
        {"level": 18, "count": 2},
        {"level": 17, "count": 1},
    ]
    assert detail["role_distribution"] == {"leader": 1, "coLeader": 1, "member": 1}
    assert detail["total_donations"] == 150
    assert detail["total_donations_received"] == 70
    assert detail["average_donations"] == 50.0
    assert detail["profile"]["clan_level"] == 25
    assert detail["profile"]["join_type"] == "inviteOnly"
    assert detail["profile_status"] == "success"
    assert detail["profile_updated_at"] == "2026-09-30T03:00:00+00:00"

    with pytest.raises(HTTPException) as exc:
        routes.clan_overview_detail("#OUTSIDE", db)
    assert exc.value.status_code == 404
