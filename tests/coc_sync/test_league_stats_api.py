import api_server.routes as routes


def _insert_result(
    db,
    period: str,
    attacks: int,
    offense_3stars: int,
    defense_total: int,
    defense_3stars: int,
):
    db.conn.execute(
        """INSERT INTO league_results
           (period, team_index, team_alias, category, player_tag, account_name,
            attacks, offense_3stars, defense_total, defense_3stars, fetched_at)
           VALUES (?, 0, '一队', 'combat', '#P1', '甲', ?, ?, ?, ?,
                   '2026-10-04T00:00:00+00:00')""",
        (period, attacks, offense_3stars, defense_total, defense_3stars),
    )


def test_league_stats_returns_attack_samples_for_every_window(db):
    db.conn.execute(
        """INSERT INTO accounts
           (player_tag, account_name, town_hall_level, membership_status)
           VALUES ('#P1', '甲', 18, 'member')""",
    )
    db.conn.execute(
        """INSERT INTO registrations
           (account_name, player_tag, period, account_type)
           VALUES ('甲', '#P1', '2026-09', 'combat')""",
    )
    _insert_result(db, "2026-07", 5, 3, 4, 1)
    _insert_result(db, "2026-08", 6, 4, 5, 2)
    _insert_result(db, "2026-09", 7, 7, 6, 6)
    db.conn.commit()

    response = routes.league_stats("2026-09", db)

    assert response["updated_at"] == "2026-10-04T00:00:00+00:00"
    item = response["stats"][0]
    assert item["offense_1m"] == 1.0
    assert item["offense_1m_sample"] == {"three_stars": 7, "attacks": 7}
    assert item["defense_1m"] == 1.0
    assert item["defense_1m_sample"] == {"three_stars": 6, "attacks": 6}
    assert item["offense_3m"] == 0.778
    assert item["offense_3m_sample"] == {"three_stars": 14, "attacks": 18}
    assert item["defense_3m"] == 0.6
    assert item["defense_3m_sample"] == {"three_stars": 9, "attacks": 15}
    assert item["offense_6m_sample"] == item["offense_3m_sample"]
    assert item["defense_6m_sample"] == item["defense_3m_sample"]
