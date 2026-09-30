import pytest

from modules.coc_sync.cwl_backfill import (
    CwlBackfillError,
    build_historical_cwl_cache,
    infer_group_tags,
)


def _side(tag, name):
    member_tag = f"#{tag.lstrip('#')}1"
    return {
        "tag": tag,
        "name": name,
        "clanLevel": 20,
        "stars": 3,
        "destructionPercentage": 100,
        "members": [{
            "tag": member_tag,
            "name": f"{name}成员",
            "townhallLevel": 18,
            "mapPosition": 1,
            "attacks": [],
        }],
    }


def _war(tag, left, right, day):
    return {
        "tag": tag,
        "state": "warEnded",
        "teamSize": 1,
        "startTime": f"2026090{day}T010000.000Z",
        "endTime": f"2026090{day + 1}T010000.000Z",
        "clan": _side(left, left),
        "opponent": _side(right, right),
    }


def _history():
    wars = [
        _war("#W1", "#AAA", "#BBB", 3),
        _war("#W2", "#CCC", "#DDD", 3),
        _war("#W3", "#AAA", "#CCC", 4),
        _war("#W4", "#BBB", "#DDD", 4),
        _war("#W5", "#AAA", "#DDD", 5),
        _war("#W6", "#BBB", "#CCC", 5),
    ]
    return {
        "#AAA": [wars[0], wars[2], wars[4]],
        "#BBB": [wars[0], wars[3], wars[5]],
        "#CCC": [wars[1], wars[2], wars[5]],
        "#DDD": [wars[1], wars[3], wars[4]],
    }


def _team():
    return {
        "period": "2026-09",
        "team_index": 0,
        "team_alias": "测试队",
        "team_name": "AAA",
        "clan_tag": "#AAA",
        "category": "combat",
        "member_count": 1,
        "league_level": "Champion League I",
    }


def test_infer_group_tags_from_selected_clan_rounds():
    assert infer_group_tags("#AAA", _history()["#AAA"]) == ["#AAA", "#BBB", "#CCC", "#DDD"]


def test_build_historical_cache_reconstructs_complete_round_robin_group():
    group, wars, summary = build_historical_cwl_cache(
        _team(), _history(), "2026-09-30T01:00:00+00:00"
    )

    assert group["season"] == "2026-09"
    assert group["state"] == "ended"
    assert group["source"] == "clashking_history_backfill"
    assert [len(item["war_tags"]) for item in group["rounds"]] == [2, 2, 2]
    assert len(group["clans"]) == 4
    assert len(wars) == 6
    assert all(war["status"] == "war_ended" for war in wars.values())
    assert summary == {
        "clan_tag": "#AAA",
        "group_clans": 4,
        "rounds": 3,
        "wars": 6,
        "member_count": 1,
    }


def test_build_historical_cache_rejects_incomplete_round():
    history = _history()
    history["#CCC"] = [war for war in history["#CCC"] if war["tag"] != "#W2"]
    history["#DDD"] = [war for war in history["#DDD"] if war["tag"] != "#W2"]

    with pytest.raises(CwlBackfillError, match="战争不完整"):
        build_historical_cwl_cache(_team(), history, "2026-09-30T01:00:00+00:00")
