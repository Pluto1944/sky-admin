from datetime import datetime, timezone

import config
import modules.coc_sync.service as service_module
from modules.coc_sync.capital_status import (
    raid_weekend_window,
    summarize_capital_raid_status,
)
from scripts.scheduler import _run_capital_raid_status
from shared.db.connection import Database


def _season(state="ongoing"):
    return {
        "state": state,
        "startTime": "20261002T070000.000Z",
        "endTime": "20261005T070000.000Z",
    }


def test_capital_status_uses_latest_started_weekend():
    active = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    start, end = raid_weekend_window(active)
    assert start.isoformat() == "2026-10-02T07:00:00+00:00"
    assert end.isoformat() == "2026-10-05T07:00:00+00:00"
    assert summarize_capital_raid_status([], active)["status"] == "not_started"
    assert summarize_capital_raid_status([_season()], active)["status"] == "ongoing"

    finished = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    assert summarize_capital_raid_status([], finished)["status"] == "missed"
    assert summarize_capital_raid_status([_season("ended")], finished)["status"] == "ended"


def test_capital_status_scheduler_stops_polling_opened_clans(tmp_path, monkeypatch):
    db_path = str(tmp_path / "capital-status.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#OPEN", "name": "已开启", "enabled": True},
        {"tag": "#WAIT", "name": "未开启", "enabled": True},
    ])
    calls = []

    class FakeService:
        def fetch_capital_raid_seasons(self, clan_tag, limit=2):
            calls.append(clan_tag)
            return [_season()] if clan_tag == "#OPEN" else []

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    first = _run_capital_raid_status(
        now=datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    )
    assert first["status"] == "success"
    assert calls == ["#OPEN", "#WAIT"]

    calls.clear()
    skipped = _run_capital_raid_status(
        now=datetime(2026, 10, 3, 0, 5, tzinfo=timezone.utc)
    )
    assert skipped["status"] == "skipped"
    assert calls == []

    _run_capital_raid_status(
        now=datetime(2026, 10, 3, 0, 11, tzinfo=timezone.utc)
    )
    assert calls == ["#WAIT"]

    db = Database(db_path)
    rows = {
        row["clan_tag"]: row["status"]
        for row in db.conn.execute("SELECT clan_tag, status FROM capital_raid_status_cache")
    }
    assert rows == {"#OPEN": "ongoing", "#WAIT": "not_started"}
    db.close()


def test_capital_status_scheduler_finalizes_weekend(tmp_path, monkeypatch):
    db_path = str(tmp_path / "capital-finished.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#OPEN", "name": "已开启", "enabled": True},
        {"tag": "#WAIT", "name": "未开启", "enabled": True},
    ])
    db = Database(db_path)
    db.init_schema()
    for clan_tag, status in (("#OPEN", "ongoing"), ("#WAIT", "not_started")):
        db.conn.execute(
            """INSERT INTO capital_raid_status_cache
               (clan_tag, clan_name, status, weekend_start, weekend_end,
                updated_at, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                clan_tag, clan_tag, status,
                "2026-10-02T07:00:00+00:00", "2026-10-05T07:00:00+00:00",
                "2026-10-05T06:50:00+00:00", "2026-10-05T06:50:00+00:00",
            ),
        )
    db.conn.commit()
    db.close()
    calls = []

    class FakeService:
        def fetch_capital_raid_seasons(self, clan_tag, limit=2):
            calls.append(clan_tag)
            return []

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    result = _run_capital_raid_status(
        now=datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    )

    assert result["status"] == "success"
    assert calls == ["#WAIT"]
    db = Database(db_path)
    rows = {
        row["clan_tag"]: row["status"]
        for row in db.conn.execute("SELECT clan_tag, status FROM capital_raid_status_cache")
    }
    assert rows == {"#OPEN": "ended", "#WAIT": "missed"}
    db.close()
