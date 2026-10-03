import api_server.routes as routes
from scripts.scheduler import _archive_current_war


def _war(day: int, offense: int, defense: int):
    return {
        "clan_tag": "#OWN", "clan_name": "自有部落", "category": "combat",
        "status": "war_ended", "state": "warEnded", "war_type": "random",
        "team_size": 1, "attacks_per_member": 2,
        "preparation_start_time": f"202609{day:02d}T000000.000Z",
        "start_time": f"202609{day:02d}T230000.000Z",
        "end_time": f"202609{day + 1:02d}T230000.000Z",
        "opponent": {"tag": f"#E{day}", "name": "对手"},
        "rows": [{
            "clan_member": {"player_tag": "#P1", "name": "甲", "town_hall_level": 18,
                            "position": 1, "attacks": [
                                {"attacker_tag": "#P1", "defender_tag": "#E", "target_position": 1,
                                 "order": 1, "stars": offense},
                            ]},
            "opponent_member": {"player_tag": "#E", "name": "敌", "attacks": [
                {"attacker_tag": "#E", "defender_tag": "#P1", "target_position": 1,
                 "order": 2, "stars": defense},
            ]},
        }],
        "synced_at": "2026-10-03T00:00:00+00:00",
    }


def test_war_stats_uses_current_clan_members_and_fixed_clan_window(db, monkeypatch):
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#OWN", "name": "自有部落", "category": "combat", "enabled": True},
    ])
    db.conn.executemany(
        "INSERT INTO accounts (player_tag, account_name, clan_tag, membership_status) VALUES (?, ?, ?, 'member')",
        [("#P1", "甲", "#OWN"), ("#P2", "已转部落", "#OTHER")],
    )
    assert _archive_current_war(db, _war(1, 3, 3))
    assert _archive_current_war(db, _war(3, 2, 1))

    response = routes.war_stats("#OWN", db)

    assert response["history_coverage"] == {"available": 2, "target": 45, "complete": False}
    assert [item["player_tag"] for item in response["stats"]] == ["#P1"]
    item = response["stats"][0]
    assert item["offense_5"] == 0.5
    assert item["offense_5_sample"] == {"three_stars": 1, "attacks": 2}
    assert item["defense_5"] == 0.5
    assert item["defense_5_sample"] == {"three_stars": 1, "attacks": 2}
