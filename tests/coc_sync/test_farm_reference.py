from __future__ import annotations

from modules.coc_sync.clashking import farm_stats


def _member(position: int, town_hall: int) -> dict:
    return {
        "tag": f"#P{position}",
        "name": f"玩家{position}",
        "mapPosition": position,
        "townhallLevel": town_hall,
    }


def test_reference_composition_is_confirmed_50_player_standard():
    assert farm_stats.REFERENCE_COMPOSITION_50 == (
        (18, 26), (17, 9), (16, 6), (15, 6), (14, 2), (13, 1),
    )
    slots = farm_stats.reference_slots()
    assert len(slots) == 50
    assert slots[25] == 18
    assert slots[26:35] == [17] * 9
    assert slots[35:41] == [16] * 6
    assert slots[41:47] == [15] * 6
    assert slots[47:49] == [14, 14]
    assert slots[49] == 13


def test_fixed_reference_calculates_distribution_and_candidates():
    standards = farm_stats.reference_slots()
    members = [_member(position, level) for position, level in enumerate(standards, 1)]
    members[26] = _member(27, 18)
    members[35] = _member(36, 18)
    members[49] = _member(50, 18)
    war = {
        "clan": {"members": members},
        "opponent": {"members": [_member(27, 10)]},
    }

    result = farm_stats.calc_despeed_config(war)
    candidates = [
        item for item in farm_stats.calc_member_rushed(war)
        if item["rushed_degree"] > 0
    ]

    assert sum(result["distribution"].values()) == 50
    assert [(item["map_position"], item["despeed_town_hall"], item["rushed_degree"])
            for item in candidates] == [(27, 17, 1), (36, 16, 2), (50, 13, 5)]


def test_fixed_reference_does_not_raise_lower_town_hall():
    result = farm_stats.calc_despeed_config({
        "clan": {"members": [_member(1, 16)]},
    })

    assert result["avg_th"] == 16.0
    assert result["distribution"]["16"] == 1
    assert farm_stats.calc_member_rushed({
        "clan": {"members": [_member(1, 16)]},
    })[0]["rushed_degree"] == 0


def test_farm_stats_keeps_existing_api_fields_with_fixed_algorithm(monkeypatch):
    monkeypatch.setattr(farm_stats, "fetch_clan_members", lambda _tag: [
        {"townHallLevel": 18},
    ])
    monkeypatch.setattr(farm_stats, "fetch_current_war", lambda _tag: {
        "clan": {"members": [_member(27, 18)]},
        "opponent": {"members": []},
    })

    result = farm_stats.get_farm_clan_stats("#FARM", "互刷一营")

    assert result["member_count"] == 1
    assert result["despeed"]["has_war"] is True
    assert result["replace_candidates"] == [{
        "player_tag": "#P27",
        "account_name": "玩家27",
        "town_hall_level": 18,
        "despeed_town_hall": 17,
        "rushed_degree": 1,
        "map_position": 27,
        "clan_tag": "#FARM",
    }]


def test_historical_position_algorithm_remains_available():
    war = {
        "clan": {"members": [_member(1, 18), _member(2, 18), _member(3, 18)]},
        "opponent": {"members": [_member(1, 18), _member(2, 16), _member(3, 18)]},
    }

    candidates = farm_stats.calc_position_member_rushed(war)

    assert candidates[-1]["map_position"] == 3
    assert candidates[-1]["despeed_town_hall"] == 16
    assert candidates[-1]["rushed_degree"] == 2
