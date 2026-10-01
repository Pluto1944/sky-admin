import json

from scripts.scheduler import _sync_clan_profiles


class _ProfileService:
    def __init__(self, results):
        self.results = results

    def fetch_clan_profiles(self):
        return self.results


def _success(points=100):
    return {
        "status": "success",
        "data": {
            "clan_tag": "#AAA",
            "name": "一队",
            "category": "normal",
            "clan_points": points,
            "synced_at": "2026-10-01T01:00:00+00:00",
        },
        "error": None,
        "attempted_at": "2026-10-01T01:00:00+00:00",
    }


def test_sync_clan_profiles_writes_success_cache(db):
    stats = _sync_clan_profiles(db, _ProfileService([_success()]))

    row = db.conn.execute("SELECT * FROM clan_profile_cache WHERE clan_tag = '#AAA'").fetchone()
    assert stats == {"success": 1, "failed": 0}
    assert row["status"] == "success"
    assert json.loads(row["data_json"])["clan_points"] == 100
    assert row["error"] is None


def test_sync_clan_profiles_keeps_last_success_when_refresh_fails(db):
    _sync_clan_profiles(db, _ProfileService([_success(points=100)]))
    failed = {
        "status": "error",
        "clan_tag": "#AAA",
        "clan_name": "一队",
        "category": "normal",
        "data": None,
        "error": "temporary failure",
        "attempted_at": "2026-10-01T02:00:00+00:00",
    }

    stats = _sync_clan_profiles(db, _ProfileService([failed]))

    row = db.conn.execute("SELECT * FROM clan_profile_cache WHERE clan_tag = '#AAA'").fetchone()
    assert stats == {"success": 0, "failed": 1}
    assert row["status"] == "stale"
    assert json.loads(row["data_json"])["clan_points"] == 100
    assert row["updated_at"] == "2026-10-01T01:00:00+00:00"
    assert row["attempted_at"] == "2026-10-01T02:00:00+00:00"
