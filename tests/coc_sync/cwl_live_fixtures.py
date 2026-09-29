def attack(attacker, defender, stars, destruction, order):
    return {
        "attackerTag": attacker,
        "defenderTag": defender,
        "stars": stars,
        "destructionPercentage": destruction,
        "order": order,
    }


def league_group():
    return {
        "season": "2026-09",
        "state": "inWar",
        "clans": [
            {
                "tag": "#AAA", "name": "我方", "clanLevel": 20,
                "members": [
                    {"tag": "#A1", "name": "甲", "townHallLevel": 18},
                    {"tag": "#A2", "name": "乙", "townHallLevel": 17},
                ],
            },
            {
                "tag": "#BBB", "name": "对方", "clanLevel": 19,
                "members": [
                    {"tag": "#B1", "name": "丙", "townHallLevel": 18},
                    {"tag": "#B2", "name": "丁", "townHallLevel": 17},
                ],
            },
        ],
        "rounds": [{"warTags": ["#W1"]}, {"warTags": ["#W2"]}],
    }


def league_war_one(state="inWar"):
    return {
        "state": state,
        "teamSize": 2,
        "attacksPerMember": 1,
        "startTime": "20260903T010000.000Z",
        "endTime": "20260904T010000.000Z",
        "clan": {
            "tag": "#AAA", "name": "我方", "stars": 3, "destructionPercentage": 50,
            "members": [
                {
                    "tag": "#A1", "name": "甲", "townhallLevel": 18, "mapPosition": 1,
                    "attacks": [attack("#A1", "#B2", 3, 100, 1)],
                },
                {"tag": "#A2", "name": "乙", "townhallLevel": 17, "mapPosition": 2},
            ],
        },
        "opponent": {
            "tag": "#BBB", "name": "对方", "stars": 5, "destructionPercentage": 90,
            "members": [
                {
                    "tag": "#B1", "name": "丙", "townhallLevel": 18, "mapPosition": 1,
                    "attacks": [attack("#B1", "#A1", 2, 80, 2)],
                },
                {
                    "tag": "#B2", "name": "丁", "townhallLevel": 17, "mapPosition": 2,
                    "attacks": [attack("#B2", "#A2", 3, 100, 3)],
                },
            ],
        },
    }


def league_war_two():
    return {
        "state": "warEnded",
        "teamSize": 2,
        "attacksPerMember": 1,
        "startTime": "20260904T010000.000Z",
        "endTime": "20260905T010000.000Z",
        "clan": {
            "tag": "#BBB", "name": "对方", "stars": 1, "destructionPercentage": 50,
            "members": [
                {
                    "tag": "#B1", "name": "丙", "townhallLevel": 18, "mapPosition": 1,
                    "attacks": [attack("#B1", "#A1", 1, 50, 1)],
                },
                {"tag": "#B2", "name": "丁", "townhallLevel": 17, "mapPosition": 2},
            ],
        },
        "opponent": {
            "tag": "#AAA", "name": "我方", "stars": 2, "destructionPercentage": 45,
            "members": [
                {
                    "tag": "#A1", "name": "甲", "townhallLevel": 18, "mapPosition": 1,
                    "attacks": [attack("#A1", "#B1", 2, 90, 2)],
                },
                {"tag": "#A2", "name": "乙", "townhallLevel": 17, "mapPosition": 2},
            ],
        },
    }


def team():
    return {
        "period": "2026-09",
        "team_index": 0,
        "team_alias": "冠军三",
        "team_name": "我方",
        "clan_tag": "#AAA",
        "category": "combat",
        "member_count": 2,
        "league_level": "Champion League III",
    }
