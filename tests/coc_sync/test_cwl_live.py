from modules.coc_sync.cwl_live import (
    build_cwl_attack_reminder,
    build_cwl_dashboard,
    normalize_cwl_group,
    normalize_cwl_season,
    normalize_cwl_war,
    orient_cwl_war,
)

from .cwl_live_fixtures import league_group, league_war_one, league_war_two, team


def _dashboard():
    group = normalize_cwl_group(league_group(), team(), "2026-09-03T00:00:00+00:00")
    wars = {
        "#W1": normalize_cwl_war(league_war_one(), "#W1", "2026-09-03T00:00:00+00:00"),
        "#W2": normalize_cwl_war(league_war_two(), "#W2", "2026-09-05T00:00:00+00:00"),
    }
    return build_cwl_dashboard(group, wars)


def test_cwl_season_accepts_official_date_and_legacy_month_formats():
    assert normalize_cwl_season("2026-10-01") == "2026-10"
    assert normalize_cwl_season("2026-10") == "2026-10"
    assert normalize_cwl_season(None) is None

    raw = league_group()
    raw["season"] = "2026-10-01"
    selected_team = {**team(), "period": "2026-10"}
    assert normalize_cwl_group(raw, selected_team)["season"] == "2026-10"


def test_normalize_and_orient_cwl_war_keeps_single_attack_and_best_defense():
    war = normalize_cwl_war(league_war_one(), "#W1")
    oriented = orient_cwl_war(war, "#AAA")

    assert oriented["status"] == "in_war"
    assert oriented["result"] == "losing"
    assert len(oriented["rows"]) == 2
    assert oriented["rows"][0]["clan_member"]["attack"]["target_position"] == 2
    assert oriented["rows"][0]["clan_member"]["defense"]["attacker_position"] == 1


def test_dashboard_builds_rounds_standings_town_halls_and_member_stats():
    dashboard = _dashboard()

    assert dashboard["current_round"] == 1
    assert dashboard["updated_at"] == "2026-09-05T00:00:00+00:00"
    assert [item["status"] for item in dashboard["rounds"]] == ["in_war", "war_ended"]
    assert dashboard["overview"]["town_halls"]["levels"] == [18, 17]

    own = next(row for row in dashboard["overview"]["standings"]["rows"] if row["clan_tag"] == "#AAA")
    assert own["wins"] == 1
    assert own["losses"] == 0
    assert own["ties"] == 0
    assert own["attack_stars"] == 5
    assert own["league_stars"] == 15
    assert own["average_destruction"] == 47.5
    assert [item["attacks"] for item in own["rounds"]] == [1, 1]
    assert [item["result"] for item in own["rounds"]] == ["losing", "victory"]
    assert [item["opponent_tag"] for item in own["rounds"]] == ["#BBB", "#BBB"]
    assert dashboard["summary"]["current_result"] == "losing"

    opponent = next(row for row in dashboard["overview"]["standings"]["rows"] if row["clan_tag"] == "#BBB")
    assert opponent["wins"] == 0
    assert opponent["losses"] == 1
    assert opponent["league_stars"] == 6

    offense = next(row for row in dashboard["overview"]["offense"]["rows"] if row["player_tag"] == "#A1")
    assert offense["total_stars"] == 5
    assert offense["attacks"] == 2
    assert offense["matchup_difference"] == -1

    defense = next(row for row in dashboard["overview"]["defense"]["rows"] if row["player_tag"] == "#A1")
    assert defense["saved_stars"] == 3
    assert defense["saved_destruction"] == 70
    assert defense["successful_defenses"] == 2


def test_member_states_distinguish_not_attacked_and_unattacked():
    dashboard = _dashboard()
    offense = next(row for row in dashboard["overview"]["offense"]["rows"] if row["player_tag"] == "#A2")
    defense = next(row for row in dashboard["overview"]["defense"]["rows"] if row["player_tag"] == "#A2")

    assert [item["status"] for item in offense["rounds"]] == ["not_attacked", "not_attacked"]
    assert [item["status"] for item in defense["rounds"]] == ["defended", "unattacked"]
    assert defense["successful_defenses"] == 0


def test_attack_reminder_only_counts_current_lineup_members_without_attack():
    group = normalize_cwl_group(league_group(), team(), "2026-09-03T00:00:00+00:00")
    wars = {
        "#W1": normalize_cwl_war(league_war_one(), "#W1", "2026-09-03T00:00:00+00:00"),
        "#W2": normalize_cwl_war(league_war_two(), "#W2", "2026-09-05T00:00:00+00:00"),
    }

    reminder = build_cwl_attack_reminder(group, wars)

    assert reminder["status"] == "in_war"
    assert reminder["round"] == 1
    assert reminder["team_size"] == 2
    assert reminder["attacked_count"] == 1
    assert reminder["pending_count"] == 1
    assert reminder["pending_members"] == [{
        "player_tag": "#A2",
        "name": "乙",
        "town_hall_level": 17,
        "position": 2,
    }]
    assert reminder["missed_rounds"] == []


def test_attack_reminder_keeps_missed_attacks_from_earlier_ended_rounds():
    group = normalize_cwl_group(league_group(), team(), "2026-09-05T00:00:00+00:00")
    current = league_war_two()
    current["state"] = "inWar"
    wars = {
        "#W1": normalize_cwl_war(
            league_war_one(state="warEnded"), "#W1", "2026-09-04T00:00:00+00:00"
        ),
        "#W2": normalize_cwl_war(current, "#W2", "2026-09-05T00:00:00+00:00"),
    }

    reminder = build_cwl_attack_reminder(group, wars)

    assert reminder["status"] == "in_war"
    assert reminder["round"] == 2
    missed = reminder["missed_rounds"]
    assert [{key: value for key, value in item.items() if key != "opponent"} for item in missed] == [{
        "round": 1,
        "end_time": "20260904T010000.000Z",
        "missed_count": 1,
        "missed_members": [{
            "player_tag": "#A2",
            "name": "乙",
            "town_hall_level": 17,
            "position": 2,
        }],
    }]
    assert missed[0]["opponent"]["name"] == "对方"
