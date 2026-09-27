from modules.coc_sync.current_war import normalize_current_war
from modules.coc_sync.service import CocSyncService
from tests.fakes import FakeCocApiClient


def _attack(attacker, defender, stars, destruction, order):
    return {
        "attackerTag": attacker,
        "defenderTag": defender,
        "stars": stars,
        "destructionPercentage": destruction,
        "order": order,
    }


def _war():
    a1_first = _attack("#A1", "#B2", 3, 100, 2)
    a1_second = _attack("#A1", "#B1", 2, 80, 4)
    b1_first = _attack("#B1", "#A1", 3, 100, 1)
    b1_second = _attack("#B1", "#A1", 3, 100, 3)
    b2_first = _attack("#B2", "#A2", 2, 75, 5)
    return {
        "state": "inWar",
        "type": "random",
        "teamSize": 2,
        "attacksPerMember": 2,
        "preparationStartTime": "20260925T010000.000Z",
        "startTime": "20260926T010000.000Z",
        "endTime": "20260927T010000.000Z",
        "clan": {
            "tag": "#AAA",
            "name": "我方",
            "attacks": 2,
            "stars": 5,
            "destructionPercentage": 90,
            "members": [
                {
                    "tag": "#A1", "name": "甲", "mapPosition": 1,
                    "townhallLevel": 18, "opponentAttacks": 2,
                    "attacks": [a1_second, a1_first],
                },
                {
                    "tag": "#A2", "name": "乙", "mapPosition": 2,
                    "townhallLevel": 17, "opponentAttacks": 1,
                },
            ],
        },
        "opponent": {
            "tag": "#BBB",
            "name": "对方",
            "attacks": 3,
            "stars": 8,
            "destructionPercentage": 95,
            "members": [
                {
                    "tag": "#B1", "name": "丙", "mapPosition": 1,
                    "townhallLevel": 18, "opponentAttacks": 1,
                    "attacks": [b1_second, b1_first],
                },
                {
                    "tag": "#B2", "name": "丁", "mapPosition": 2,
                    "townhallLevel": 17, "opponentAttacks": 1,
                    "attacks": [b2_first],
                },
            ],
        },
    }


def test_normalize_current_war_builds_positions_attacks_and_defenses():
    item = normalize_current_war(
        _war(), {"tag": "#AAA", "name": "配置名", "category": "combat"}, "2026-09-27T00:00:00+00:00"
    )

    assert item["status"] == "in_war"
    assert item["result"] == "losing"
    assert item["clan"]["total_attacks"] == 4
    assert len(item["rows"]) == 2

    first = item["rows"][0]["clan_member"]
    assert [attack["order"] for attack in first["attacks"]] == [2, 4]
    assert [attack["target_position"] for attack in first["attacks"]] == [2, 1]
    assert first["defense"]["three_star_count"] == 2
    assert first["defense"]["total_attacks"] == 2
    assert first["defense"]["best_attack"]["attacker_position"] == 1
    assert first["defense"]["best_attack"]["order"] == 1


def test_normalize_current_war_swaps_sides_to_configured_clan():
    raw = _war()
    raw["clan"], raw["opponent"] = raw["opponent"], raw["clan"]

    item = normalize_current_war(raw, {"tag": "#AAA", "name": "我方", "category": "normal"})

    assert item["clan"]["tag"] == "#AAA"
    assert item["opponent"]["tag"] == "#BBB"
    assert item["rows"][0]["clan_member"]["name"] == "甲"


def test_cwl_is_redirect_state_without_rows():
    raw = _war()
    raw["type"] = "cwl"
    raw["attacksPerMember"] = 1

    item = normalize_current_war(raw, {"tag": "#AAA", "name": "我方", "category": "combat"})

    assert item["status"] == "cwl"
    assert item["rows"] == []


def test_not_in_war_has_stable_empty_shape():
    item = normalize_current_war(
        {"state": "notInWar"}, {"tag": "#AAA", "name": "我方", "category": "farm"}
    )

    assert item["status"] == "not_in_war"
    assert item["clan"]["tag"] == "#AAA"
    assert item["opponent"] is None
    assert item["rows"] == []


def test_preparation_and_ended_results_are_normalized():
    preparing = _war()
    preparing["state"] = "preparation"
    item = normalize_current_war(preparing, {"tag": "#AAA", "name": "我方"})
    assert item["status"] == "preparation"
    assert item["result"] == "pending"

    ended = _war()
    ended["state"] = "warEnded"
    ended["clan"]["stars"] = 9
    item = normalize_current_war(ended, {"tag": "#AAA", "name": "我方"})
    assert item["status"] == "war_ended"
    assert item["result"] == "victory"


def test_fifty_player_war_keeps_all_map_positions():
    raw = _war()
    raw["teamSize"] = 50
    raw["clan"]["members"] = [
        {"tag": f"#A{position}", "name": f"己{position}", "mapPosition": position, "townhallLevel": 18}
        for position in range(1, 51)
    ]
    raw["opponent"]["members"] = [
        {"tag": f"#B{position}", "name": f"敌{position}", "mapPosition": position, "townhallLevel": 18}
        for position in range(1, 51)
    ]

    item = normalize_current_war(raw, {"tag": "#AAA", "name": "我方"})

    assert len(item["rows"]) == 50
    assert item["rows"][-1]["position"] == 50
    assert item["rows"][-1]["clan_member"]["name"] == "己50"
    assert item["rows"][-1]["opponent_member"]["name"] == "敌50"


def test_service_isolates_current_war_failure():
    api = FakeCocApiClient(wars_by_clan={"#OK": _war()}, fail_clans={"#BAD"})
    items = CocSyncService(api_client=api).fetch_current_wars([
        {"tag": "#BAD", "name": "坏部落", "category": "farm"},
        {"tag": "#OK", "name": "好部落", "category": "combat"},
    ])

    assert items[0]["status"] == "error"
    assert "抓取失败" in items[0]["error"]
    assert items[1]["status"] == "in_war"
