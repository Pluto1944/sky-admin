import pytest

from modules.coc_sync.clashking import client as clashking_client
from modules.coc_sync.cwl_backfill import (
    CwlBackfillError,
    build_historical_cwl_cache,
    infer_group_tags,
)
from scripts.backfill_cwl_live import (
    MultipleCwlSeasonsError,
    _build_from_stored_groups,
    _write_cache,
    run,
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


def test_backfill_writes_complete_raw_archive_and_projection(db):
    group, wars, _summary = build_historical_cwl_cache(
        _team(), _history(), "2026-09-30T01:00:00+00:00"
    )
    db.conn.execute(
        "INSERT INTO accounts (player_tag, account_name) VALUES (?, ?)",
        ("#AAA1", "AAA成员"),
    )
    db.conn.commit()

    written_groups, written_wars = _write_cache(
        db, "2026-09", [(group, wars)], "2026-09-30T01:00:00+00:00"
    )

    assert (written_groups, written_wars) == (1, 6)
    raw_group = db.conn.execute(
        "SELECT raw_status, source FROM cwl_live_group_cache"
    ).fetchone()
    assert tuple(raw_group) == ("complete", "clashking_history_backfill")
    projection = db.conn.execute(
        "SELECT period, team_index, player_tag, attacks FROM league_results"
    ).fetchone()
    assert tuple(projection) == ("2026-09", 0, "#AAA1", 0)


def test_stored_cwl_archive_fallback_builds_and_validates(monkeypatch, db):
    history = _history()
    wars = {war["tag"]: war for items in history.values() for war in items}
    stored = {
        "season": "2026-09-02",
        "clans": [{"tag": tag} for tag in history],
        "rounds": [
            {"warTags": [wars["#W1"], wars["#W2"]]},
            {"warTags": [wars["#W3"], wars["#W4"]]},
            {"warTags": [wars["#W5"], wars["#W6"]]},
        ],
    }
    db.conn.execute(
        "INSERT INTO accounts (player_tag, account_name) VALUES (?, ?)",
        ("#AAA1", "AAA成员"),
    )
    db.conn.execute(
        """INSERT INTO league_results
           (period, team_index, team_alias, clan_tag, category, player_tag,
            account_name, total_stars, attacks)
           VALUES ('2026-09', 0, '测试队', '#AAA', 'combat', '#AAA1', 'AAA成员', 0, 0)"""
    )
    db.conn.commit()
    monkeypatch.setattr(
        "scripts.backfill_cwl_live.fetch_historical_cwl_groups",
        lambda _tag, _period: [stored],
    )

    group, normalized_wars, summary, checked = _build_from_stored_groups(
        db, "2026-09", _team(), "2026-09-30T01:00:00+00:00"
    )

    assert checked == 1
    assert summary["archive_season"] == "2026-09-02"
    assert group["source"] == "clashking_cwl_archive_backfill"
    assert len(normalized_wars) == 6
    assert {war["source"] for war in normalized_wars.values()} == {
        "clashking_cwl_archive_backfill"
    }


def test_stored_cwl_archive_rejects_multiple_seasons(monkeypatch, db):
    monkeypatch.setattr(
        "scripts.backfill_cwl_live.fetch_historical_cwl_groups",
        lambda _tag, _period: [
            {"season": "2026-06", "clans": [{}], "rounds": [{}]},
            {"season": "2026-06-16", "clans": [{}], "rounds": [{}]},
        ],
    )

    with pytest.raises(MultipleCwlSeasonsError, match="2 套 CWL 赛季档案"):
        _build_from_stored_groups(
            db, "2026-06", _team(), "2026-06-30T01:00:00+00:00"
        )


def test_run_can_prefer_archive_and_finish_dry_run(monkeypatch, capsys):
    class FakeDatabase:
        def __init__(self, _path):
            self.conn = None

        def init_schema(self):
            return None

        def close(self):
            return None

    summary = {
        "clan_tag": "#AAA",
        "group_clans": 4,
        "rounds": 3,
        "wars": 6,
        "member_count": 1,
        "history_rows_checked": 1,
        "dashboard_status": "ended",
        "archive_season": "2026-09-02",
    }
    monkeypatch.setattr("scripts.backfill_cwl_live.Database", FakeDatabase)
    monkeypatch.setattr("scripts.backfill_cwl_live._load_teams", lambda _db, _period: [_team()])
    monkeypatch.setattr(
        "scripts.backfill_cwl_live._build_from_stored_groups",
        lambda _db, _period, _team_value, _timestamp: ({}, {}, summary, 1),
    )

    assert run("2026-09", prefer_archive=True) == 0
    output = capsys.readouterr().out
    assert "season=2026-09-02" in output
    assert "核对历史 1 人" in output
    assert "DRY-RUN 通过：1/1" in output


def test_fetch_historical_cwl_groups_accepts_month_and_dated_seasons(monkeypatch):
    requested = []

    def fake_get(url, timeout=30):
        requested.append((url, timeout))
        if "/seasons?" in url:
            return {
                "items": [
                    {"season": "2026-08-02"},
                    {"season": "2026-07"},
                    {"season": "2026-08"},
                ]
            }
        return {"season": url.rsplit("/", 1)[-1], "clans": [{}], "rounds": [{}]}

    monkeypatch.setattr(clashking_client, "_curl_get", fake_get)

    groups = clashking_client.fetch_historical_cwl_groups("#AAA", "2026-08")

    assert [group["season"] for group in groups] == ["2026-08", "2026-08-02"]
    assert requested[0][0].endswith("/v2/cwl/%23AAA/seasons?limit=24")
    assert [timeout for _url, timeout in requested[1:]] == [60, 60]
