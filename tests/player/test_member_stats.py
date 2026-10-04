import json
from datetime import datetime, timezone

import api_server.routes as routes
from modules.player.member_stats import (
    cwl_attack_counts,
    materialize_war_member_facts,
    member_summary_map,
)
from modules.player.repository import PlayerRepository
from scripts.scheduler import _archive_current_war


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
    assert _archive_current_war(db, _war())
    second = _war()
    second.update({
        "clan_tag": "#OWN2", "clan_name": "自有二营",
        "preparation_start_time": "20260925T000000.000Z",
        "start_time": "20260925T230000.000Z", "end_time": "20260926T230000.000Z",
        "opponent": {"tag": "#ENEMY2", "name": "对手二"},
    })
    assert _archive_current_war(db, second)
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, clan_tag, category, member_count)
           VALUES ('2026-09', 0, '壳队', '#CWL1', 'shell', 15)"""
    )
    db.conn.execute(
        """INSERT INTO league_results
           (period, team_index, team_alias, clan_tag, category, player_tag,
            account_name, attacks, offense_1stars, offense_3stars)
           VALUES ('2026-09', 0, '壳队', '#CWL1', 'shell', '#P1', '甲', 7, 2, 4)"""
    )
    summaries = member_summary_map(db.conn, ["#P1", "#P2"])
    assert summaries["#P1"]["war_recent_15"] == {
        "war_count": 2, "three_stars": 2, "attacks": 2,
        "available_attacks": 4, "three_star_rate": 100.0, "attack_rate": 50.0,
    }
    assert summaries["#P2"]["war_recent_15"]["war_count"] == 2
    assert summaries["#P2"]["war_recent_15"]["attacks"] == 0
    assert summaries["#P1"]["cwl_recent_3m"]["attacks"] == 7
    assert summaries["#P1"]["cwl_recent_3m"]["one_stars"] == 2
    assert summaries["#P1"]["cwl_recent_3m"]["one_star_rate"] == 28.6
    assert summaries["#P1"]["cwl_recent_3m"]["three_star_rate"] == 57.1


def test_war_fact_changes_distinguish_first_archive_and_new_attack(db):
    _seed_accounts(db)
    first = materialize_war_member_facts(db.conn, _war())
    assert first.changed_player_tags == frozenset({"#P1", "#P2"})
    assert first.activity_player_tags == frozenset()

    unchanged = materialize_war_member_facts(db.conn, _war())
    assert unchanged.changed_player_tags == frozenset()
    assert unchanged.activity_player_tags == frozenset()

    corrected = _war()
    corrected["rows"][0]["clan_member"]["attacks"].append(
        {"order": 2, "stars": 2, "target_position": 2}
    )
    changed = materialize_war_member_facts(db.conn, corrected)
    assert changed.changed_player_tags == frozenset({"#P1"})
    assert changed.activity_player_tags == frozenset({"#P1"})


def test_war_facts_calculate_offense_and_defense_by_target_best_stars(db):
    _seed_accounts(db)
    war = _war()
    war["team_size"] = 2  # 满星为 6；同一目标补刀不能重复累计旧星。
    war["rows"] = [
        {
            "clan_member": {
                "player_tag": "#P1", "town_hall_level": 18, "position": 1,
                "attacks": [
                    {"attacker_tag": "#P1", "defender_tag": "#E1", "target_position": 1, "order": 1, "stars": 2},
                    {"attacker_tag": "#P1", "defender_tag": "#E1", "target_position": 1, "order": 3, "stars": 3},
                    {"attacker_tag": "#P1", "defender_tag": "#E2", "target_position": 2, "order": 5, "stars": 3},
                    {"attacker_tag": "#P1", "defender_tag": "#E2", "target_position": 2, "order": 7, "stars": 3},
                ],
            },
            "opponent_member": {
                "player_tag": "#E1", "attacks": [
                    {"attacker_tag": "#E1", "defender_tag": "#P1", "target_position": 1, "order": 2, "stars": 2},
                    {"attacker_tag": "#E1", "defender_tag": "#P1", "target_position": 1, "order": 4, "stars": 3},
                    {"attacker_tag": "#E1", "defender_tag": "#P2", "target_position": 2, "order": 6, "stars": 3},
                ],
            },
        },
        {"clan_member": {"player_tag": "#P2", "town_hall_level": 17, "position": 2, "attacks": []}},
    ]

    materialize_war_member_facts(db.conn, war)
    row = db.conn.execute(
        """SELECT offense_observed_attacks, offense_effective_attacks, offense_effective_3stars,
                  defense_observed_attacks, defense_effective_attacks, defense_effective_3stars,
                  metric_version
           FROM member_war_facts WHERE clan_tag = '#OWN1' AND player_tag = '#P1'"""
    ).fetchone()

    assert tuple(row) == (4, 3, 2, 2, 2, 1, 2)


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
