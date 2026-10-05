from datetime import datetime, timezone

import config
import modules.coc_sync.service as service_module
from scripts.scheduler import (
    JOBS,
    _run_capital_member_stats,
    _run_clan_games_stats,
)
from shared.db.connection import Database


def test_capital_member_job_writes_ended_seasons(tmp_path, monkeypatch):
    db_path = str(tmp_path / "capital.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#OWN", "name": "自有部落", "enabled": True},
    ])
    monkeypatch.setattr("scripts.scheduler.PLAYER_DETAIL_REQUEST_DELAY_SECONDS", 0)

    class FakeService:
        def fetch_capital_raid_seasons(self, clan_tag, limit=8):
            assert clan_tag == "#OWN"
            return [{
                "state": "ended",
                "startTime": "20261002T070000.000Z",
                "endTime": "20261005T070000.000Z",
                "members": [{
                    "tag": "#P1", "name": "甲", "attackLimit": 5,
                    "bonusAttackLimit": 1, "attacks": 6,
                    "capitalResourcesLooted": 88888,
                }],
            }]

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    result = _run_capital_member_stats(
        now=datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
    )
    assert result["status"] == "success"
    db = Database(db_path)
    row = db.conn.execute("SELECT * FROM capital_raid_member_results").fetchone()
    assert row["player_tag"] == "#P1"
    assert row["capital_resources_looted"] == 88888
    db.close()


def test_clan_games_job_uses_previous_month_baseline(tmp_path, monkeypatch):
    db_path = str(tmp_path / "games.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "ALLIANCE_CLAN_TAGS", ["#OWN"])
    monkeypatch.setattr("scripts.scheduler.PLAYER_DETAIL_REQUEST_DELAY_SECONDS", 0)
    db = Database(db_path)
    db.init_schema()
    db.conn.execute(
        """INSERT INTO accounts
           (player_tag, account_name, clan_tag, membership_status, activity_observed_since)
           VALUES ('#P1', '甲', '#OWN', 'member', '2026-09-01T00:00:00+00:00')"""
    )
    db.conn.execute(
        """INSERT INTO clan_games_member_snapshots
           (period, player_tag, cumulative_value, points, complete, fetched_at)
           VALUES ('2026-09', '#P1', 4000, NULL, 0, '2026-09-29T00:00:00+00:00')"""
    )
    db.conn.commit()
    db.close()

    class FakeService:
        def fetch_player(self, player_tag):
            return {
                "tag": player_tag, "name": "甲", "role": "member",
                "clan": {"tag": "#OWN", "name": "自有部落"},
                "attackWins": 12,
                "achievements": [{"name": "Games Champion", "value": 7500}],
            }

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    result = _run_clan_games_stats(
        now=datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
    )
    assert result["status"] == "success"
    db = Database(db_path)
    row = db.conn.execute(
        "SELECT points, complete FROM clan_games_member_snapshots WHERE period='2026-10'"
    ).fetchone()
    assert row["points"] == 3500
    assert row["complete"] == 1
    assert db.conn.execute(
        "SELECT season_attack_wins FROM accounts WHERE player_tag='#P1'"
    ).fetchone()["season_attack_wins"] == 12
    db.close()


def test_clan_games_force_before_event_creates_previous_month_baseline(tmp_path, monkeypatch):
    db_path = str(tmp_path / "games-baseline.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "ALLIANCE_CLAN_TAGS", ["#OWN"])
    monkeypatch.setattr("scripts.scheduler.PLAYER_DETAIL_REQUEST_DELAY_SECONDS", 0)
    db = Database(db_path)
    db.init_schema()
    db.conn.execute(
        """INSERT INTO accounts (player_tag, account_name, clan_tag, membership_status)
           VALUES ('#P1', '甲', '#OWN', 'member')"""
    )
    db.conn.commit()
    db.close()

    class FakeService:
        def fetch_player(self, player_tag):
            return {
                "tag": player_tag, "name": "甲", "role": "member",
                "clan": {"tag": "#OWN"},
                "achievements": [{"name": "Games Champion", "value": 4000}],
            }

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    result = _run_clan_games_stats(
        force=True, now=datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
    )
    assert result["status"] == "success"
    db = Database(db_path)
    row = db.conn.execute("SELECT * FROM clan_games_member_snapshots").fetchone()
    assert row["period"] == "2026-09"
    assert row["points"] is None
    assert row["complete"] == 0
    db.close()


def test_member_jobs_are_registered_with_bounded_intervals():
    assert JOBS["player_details"]["interval"] == 1440
    assert JOBS["member_combat_stats"]["interval"] == 1440
    assert JOBS["capital_raid_status"]["interval"] == 10
    assert JOBS["capital_member_stats"]["interval"] == 360
    assert JOBS["clan_games_stats"]["interval"] == 360
