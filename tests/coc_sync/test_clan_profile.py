from modules.coc_sync.clan_profile import normalize_clan_profile


def test_normalize_clan_profile_keeps_display_fields_without_member_list():
    raw = {
        "tag": "#2qq",
        "name": "云深不知处",
        "clanLevel": 25,
        "members": 47,
        "type": "inviteOnly",
        "description": "部落描述",
        "warFrequency": "always",
        "warWinStreak": 129,
        "warWins": 131,
        "warTies": 192,
        "warLosses": 3,
        "isWarLogPublic": True,
        "clanPoints": 167890,
        "clanBuilderBasePoints": 40352,
        "clanCapitalPoints": 4890,
        "requiredTrophies": 3500,
        "requiredBuilderBaseTrophies": 0,
        "requiredTownhallLevel": 16,
        "isFamilyFriendly": False,
        "location": {"id": 1, "name": "China", "isCountry": True, "countryCode": "CN"},
        "warLeague": {"id": 2, "name": "Legend League"},
        "capitalLeague": {"id": 3, "name": "Titan League I"},
        "badgeUrls": {"small": "s", "medium": "m", "large": "l"},
        "labels": [{"id": 4, "name": "Clan Wars", "iconUrls": {"small": "ls"}}],
        "memberList": [{"tag": "#PLAYER", "name": "成员"}],
    }

    result = normalize_clan_profile(
        raw, {"tag": "#2QQ", "name": "配置名", "category": "combat"},
        "2026-10-01T01:00:00+00:00",
    )

    assert result["clan_tag"] == "#2QQ"
    assert result["clan_level"] == 25
    assert result["official_member_count"] == 47
    assert result["war_league"] == {"id": 2, "name": "Legend League"}
    assert result["location"]["country_code"] == "CN"
    assert result["labels"] == [{
        "id": 4, "name": "Clan Wars", "icon_urls": {"small": "ls"},
    }]
    assert "memberList" not in result
