import json

import pytest
from fastapi import HTTPException

import api_server.routes as routes
from modules.coc_sync.cwl_live import normalize_cwl_group, normalize_cwl_war

from .cwl_live_fixtures import league_group, league_war_one, league_war_two, team


def _seed(db):
    selected_team = team()
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category,
            member_count, league_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            selected_team["period"], selected_team["team_index"], selected_team["team_alias"],
            selected_team["team_name"], selected_team["clan_tag"], selected_team["category"],
            selected_team["member_count"], selected_team["league_level"],
        ),
    )
    group = normalize_cwl_group(league_group(), selected_team, "2026-09-03T00:00:00+00:00")
    db.conn.execute(
        """INSERT INTO cwl_live_group_cache
           (period, clan_tag, team_index, team_alias, team_name, category,
            league_level, season, state, status, data_json, error, updated_at, attempted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
        (
            "2026-09", "#AAA", 0, "冠军三", "我方", "combat", "Champion League III",
            "2026-09", "inWar", "active", json.dumps(group),
            "2026-09-03T00:00:00+00:00", "2026-09-03T00:00:00+00:00",
        ),
    )
    for war_tag, raw in (("#W1", league_war_one()), ("#W2", league_war_two())):
        war = normalize_cwl_war(raw, war_tag, "2026-09-03T00:00:00+00:00")
        db.conn.execute(
            """INSERT INTO cwl_live_war_cache
               (war_tag, season, state, status, data_json, error, updated_at, attempted_at)
               VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                war_tag, "2026-09", war["state"], war["status"], json.dumps(war),
                war["synced_at"], war["synced_at"],
            ),
        )
    db.conn.commit()


def test_cwl_live_summary_and_detail_read_cache(db):
    _seed(db)

    summary = routes.cwl_live("2026-09", db)
    assert summary["period"] == "2026-09"
    assert len(summary["clans"]) == 1
    assert summary["clans"][0]["clan_tag"] == "#AAA"
    assert summary["clans"][0]["current_round"] == 1

    detail = routes.cwl_live_detail("#aaa", "2026-09", 2, db)
    assert detail["team"]["clan_tag"] == "#AAA"
    assert len(detail["rounds"]) == 2
    assert detail["requested_round"] == 2
    assert detail["overview"]["offense"]["rows"]
    assert detail["available_teams"][0]["clan_tag"] == "#AAA"


def test_cwl_check_in_aggregates_active_teams_and_pending_attacks(db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(routes, "_current_cwl_live_period", lambda: "2026-09")

    result = routes.cwl_check_in(db)

    assert result["period"] == "2026-09"
    assert result["summary"] == {
        "team_count": 1,
        "active_team_count": 1,
        "preparation_team_count": 0,
        "pending_attack_count": 1,
    }
    assert len(result["teams"]) == 1
    team_item = result["teams"][0]
    assert team_item["status"] == "in_war"
    assert team_item["round"] == 1
    assert team_item["attacked_count"] == 1
    assert team_item["pending_members"][0]["player_tag"] == "#A2"


def test_cwl_live_detail_rejects_clan_outside_month_snapshot(db):
    _seed(db)

    with pytest.raises(HTTPException) as exc:
        routes.cwl_live_detail("#OUTSIDE", "2026-09", None, db)
    assert exc.value.status_code == 404


def test_cwl_live_summary_keeps_team_when_group_not_synced(db):
    selected_team = team()
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category,
            member_count, league_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            selected_team["period"], selected_team["team_index"], selected_team["team_alias"],
            selected_team["team_name"], selected_team["clan_tag"], "shell",
            selected_team["member_count"], selected_team["league_level"],
        ),
    )
    db.conn.commit()

    summary = routes.cwl_live("2026-09", db)
    assert summary["clans"][0]["status"] == "waiting"
    assert summary["clans"][0]["category"] == "shell"


def test_cwl_available_periods_include_current_and_only_complete_history(db, monkeypatch):
    monkeypatch.setattr(routes, "_current_cwl_live_period", lambda: "2026-10")
    _seed(db)

    incomplete = routes.cwl_live("2026-09", db)
    assert incomplete["available_periods"] == [
        {"period": "2026-10", "label": "2026年10月", "current": True},
    ]

    group = json.loads(db.conn.execute(
        "SELECT data_json FROM cwl_live_group_cache WHERE period='2026-09'"
    ).fetchone()[0])
    group["state"] = "ended"
    db.conn.execute(
        "UPDATE cwl_live_group_cache SET state='ended', status='ended', data_json=? WHERE period='2026-09'",
        (json.dumps(group),),
    )
    for war_tag in ("#W1", "#W2"):
        row = db.conn.execute(
            "SELECT data_json FROM cwl_live_war_cache WHERE war_tag=?", (war_tag,)
        ).fetchone()
        war = json.loads(row[0])
        war["state"] = "warEnded"
        war["status"] = "war_ended"
        db.conn.execute(
            "UPDATE cwl_live_war_cache SET state='warEnded', status='war_ended', data_json=? WHERE war_tag=?",
            (json.dumps(war), war_tag),
        )
    db.conn.commit()

    complete = routes.cwl_live("2026-09", db)
    assert [item["period"] for item in complete["available_periods"]] == ["2026-10", "2026-09"]
