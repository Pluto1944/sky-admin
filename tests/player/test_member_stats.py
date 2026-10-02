import json
from datetime import datetime, timezone

import api_server.routes as routes
from modules.player.member_stats import (
    cwl_attack_counts,
    materialize_war_member_facts,
    member_summary_map,
    refresh_member_combat_stats,
)
from modules.player.repository import PlayerRepository


def _war(status="war_ended"):
    return {
        "clan_tag": "#OWN1", "clan_name": "自有一营", "category": "farm",
        "status": status, "state": "warEnded", "war_type": "random",
        "team_size": 2, "attacks_per_member": 2,
        "preparation_start_time": "20261001T000000.000Z",
        "start_time": "20261001T230000.000Z", "end_time": "20261002T230000.000Z",
        "opponent": {"tag": "#ENEMY", "name": "对手"},
        "rows": [
            {"clan_member": {"player_tag": "#P1", "attacks": [
                {"order": 1, "stars": 3, "target_position": 1},
            ]}},
            {"clan_member": {"player_tag": "#P2", "attacks": []}},
        ],
        "synced_at": "2026-10-02T12:00:00+00:00",
    }


def _seed_accounts(db):
    for tag, name in (("#P1", "甲"), ("#P2", "乙")):
        db.conn.execute(
            """INSERT INTO accounts
               (player_tag, account_name, clan_tag, membership_status,
                activity_observed_since, coc_raw)
               VALUES (?, ?, '#OWN1', 'member', '2026-10-01T00:00:00+00:00', ?)""",
            (tag, name, json.dumps({"donations": 10, "donationsReceived": 5})),
        )
    db.conn.commit()


def test_cross_clan_war_and_cwl_summary_uses_player_tag(db):
    _seed_accounts(db)
    materialize_war_member_facts(db.conn, _war())
    second = _war()
    second.update({
        "clan_tag": "#OWN2", "clan_name": "自有二营",
        "preparation_start_time": "20260925T000000.000Z",
        "start_time": "20260925T230000.000Z", "end_time": "20260926T230000.000Z",
        "opponent": {"tag": "#ENEMY2", "name": "对手二"},
    })
    materialize_war_member_facts(db.conn, second)
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, clan_tag, category, member_count)
           VALUES ('2026-09', 0, '壳队', '#CWL1', 'shell', 15)"""
    )
    db.conn.execute(
        """INSERT INTO league_results
           (period, team_index, team_alias, clan_tag, category, player_tag,
            account_name, attacks, offense_3stars)
           VALUES ('2026-09', 0, '壳队', '#CWL1', 'shell', '#P1', '甲', 7, 4)"""
    )
    refresh_member_combat_stats(db.conn, datetime(2026, 10, 3, tzinfo=timezone.utc))
    db.conn.commit()

    summaries = member_summary_map(db.conn, ["#P1", "#P2"])
    assert summaries["#P1"]["war_recent_15"] == {
        "war_count": 2, "three_stars": 2, "attacks": 2,
        "available_attacks": 4, "three_star_rate": 100.0, "attack_rate": 50.0,
    }
    assert summaries["#P2"]["war_recent_15"]["war_count"] == 2
    assert summaries["#P2"]["war_recent_15"]["attacks"] == 0
    assert summaries["#P1"]["cwl_recent_3m"]["attacks"] == 7
    assert summaries["#P1"]["cwl_recent_3m"]["three_star_rate"] == 57.1


def test_member_api_derives_public_fields_and_hides_raw(db, monkeypatch):
    _seed_accounts(db)
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#OWN1", "name": "自有一营", "category": "combat", "enabled": True},
    ])
    response = routes.list_members(PlayerRepository(db.conn), db)
    member = next(item for item in response["members"] if item["player_tag"] == "#P1")
    assert member["clan_name"] == "自有一营"
    assert member["donations"] == 10
    assert member["donations_received"] == 5
    assert "coc_raw" not in member
    assert response["clans"][0]["category_label"] == "战营"


def test_capital_and_games_summary(db):
    _seed_accounts(db)
    db.conn.execute(
        """INSERT INTO capital_raid_member_results
           (clan_tag, start_time, end_time, player_tag, attack_limit,
            bonus_attack_limit, attacks, capital_resources_looted, fetched_at)
           VALUES ('#OWN1', '20260925T070000.000Z', '20260928T070000.000Z',
                   '#P1', 5, 1, 6, 90000, '2026-09-29T00:00:00+00:00')"""
    )
    db.conn.execute(
        """INSERT INTO clan_games_member_snapshots
           (period, player_tag, cumulative_value, points, complete, fetched_at)
           VALUES ('2026-09', '#P1', 8000, 4000, 1, '2026-09-29T00:00:00+00:00')"""
    )
    db.conn.commit()
    summary = member_summary_map(db.conn, ["#P1"])["#P1"]
    assert summary["capital_recent_4w"]["looted"] == 90000
    assert summary["capital_recent_4w"]["loot_per_attack"] == 15000.0
    assert summary["clan_games"]["points"] == 4000
    assert summary["clan_games"]["average_3"] == 4000.0


def test_cwl_activity_counts_only_self_owned_sides():
    war = {
        "clan": {"tag": "#OWN", "members": [
            {"player_tag": "#P1", "attacks": [{"stars": 3}]},
        ]},
        "opponent": {"tag": "#OUT", "members": [
            {"player_tag": "#P2", "attacks": [{"stars": 3}]},
        ]},
    }
    assert cwl_attack_counts(war, {"#OWN"}) == {"#P1": 1}
