from modules.coc_sync.cwl_projection import (
    build_league_result_rows,
    group_raw_status,
    rebuild_league_results,
)


def _group():
    return {
        "period": "2026-10", "clan_tag": "#OWN",
        "rounds": [{"round": 1, "war_tags": ["#WAR1"]}],
    }


def _war(status="war_ended"):
    return {
        "war_tag": "#WAR1", "status": status,
        "clan": {
            "tag": "#OWN", "members": [
                {"player_tag": "#P1", "name": "甲", "attacks": [
                    {"defender_tag": "#E1", "stars": 3},
                    {"defender_tag": "#E2", "stars": 1},
                ]},
                {"player_tag": "#P2", "name": "乙", "attacks": []},
            ],
        },
        "opponent": {
            "tag": "#ENEMY", "members": [
                {"player_tag": "#E1", "attacks": [
                    {"defender_tag": "#P1", "stars": 3},
                ]},
                {"player_tag": "#E2", "attacks": [
                    {"defender_tag": "#P1", "stars": 2},
                    {"defender_tag": "#P2", "stars": 3},
                ]},
            ],
        },
    }


def _team():
    return {
        "period": "2026-10", "team_index": 2, "team_alias": "二队",
        "team_name": "自有二队", "clan_tag": "#OWN", "category": "combat",
    }


def test_raw_group_requires_every_final_war_before_projection():
    group = _group()
    assert group_raw_status(group, {"#WAR1": _war("in_war")}) == "collecting"
    assert group_raw_status(group, {"#WAR1": _war()}) == "complete"


def test_projection_aggregates_offense_and_defense_from_raw_wars(db):
    rows = build_league_result_rows(_group(), {"#WAR1": _war()}, _team())
    assert rows == [
        {"player_tag": "#P1", "account_name": "甲", "total_stars": 4, "attacks": 2,
         "appearances": 1, "missed_attacks": 0,
         "offense_1stars": 1, "offense_3stars": 1,
         "defense_3stars": 1, "defense_total": 2},
        {"player_tag": "#P2", "account_name": "乙", "total_stars": 0, "attacks": 0,
         "appearances": 1, "missed_attacks": 1,
         "offense_1stars": 0, "offense_3stars": 0,
         "defense_3stars": 1, "defense_total": 1},
    ]
    db.conn.executemany(
        "INSERT INTO accounts (player_tag, account_name) VALUES (?, ?)",
        [("#P1", "甲"), ("#P2", "乙")],
    )
    written, skipped = rebuild_league_results(
        db.conn, _group(), {"#WAR1": _war()}, _team(), rebuilt_at="2026-10-08T00:00:00+00:00",
    )
    assert (written, skipped) == (2, 0)
    actual = db.conn.execute(
        """SELECT player_tag, total_stars, attacks, appearances, missed_attacks,
                  offense_1stars, offense_3stars, defense_3stars, defense_total
           FROM league_results ORDER BY player_tag"""
    ).fetchall()
    assert [tuple(row) for row in actual] == [
        ("#P1", 4, 2, 1, 0, 1, 1, 1, 2),
        ("#P2", 0, 0, 1, 1, 0, 0, 1, 1),
    ]
