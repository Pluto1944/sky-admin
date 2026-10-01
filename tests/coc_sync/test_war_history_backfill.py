import config

import scripts.backfill_war_history as backfill
from modules.coc_sync.current_war import normalize_current_war
from scripts.scheduler import _archive_current_war
from shared.db.connection import Database

from scripts.backfill_war_history import prepare_clan_history

from .test_current_war import _war


def test_prepare_clan_history_keeps_latest_regular_ended_wars():
    older = _war()
    older["state"] = "warEnded"
    newer = _war()
    newer["state"] = "warEnded"
    newer["preparationStartTime"] = "20260927T010000.000Z"
    newer["startTime"] = "20260928T010000.000Z"
    newer["endTime"] = "20260929T010000.000Z"
    cwl = _war()
    cwl["state"] = "warEnded"
    cwl["type"] = "cwl"
    cwl["attacksPerMember"] = 1

    result = prepare_clan_history(
        [older, cwl, newer],
        {"tag": "#AAA", "name": "我方", "category": "combat"},
        keep=1,
        synced_at="2026-10-01T00:00:00+00:00",
    )

    assert len(result) == 1
    assert result[0]["end_time"] == "20260929T010000.000Z"
    assert result[0]["status"] == "war_ended"


def test_apply_backfill_preserves_current_active_snapshot(tmp_path, monkeypatch):
    db_path = str(tmp_path / "backfill.sqlite3")
    clan = {"tag": "#AAA", "name": "我方", "category": "combat", "enabled": True}
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [clan])

    active_raw = _war()
    active_raw["state"] = "inWar"
    active_raw["preparationStartTime"] = "20261001T010000.000Z"
    active_raw["startTime"] = "20261002T010000.000Z"
    active_raw["endTime"] = "20261003T010000.000Z"
    active = normalize_current_war(active_raw, clan, "2026-10-02T00:00:00+00:00")
    db = Database(db_path)
    db.init_schema()
    assert _archive_current_war(db, active)
    db.conn.commit()
    db.close()

    ended = _war()
    ended["state"] = "warEnded"
    monkeypatch.setattr(backfill, "fetch_war_log", lambda tag, limit: [ended])

    assert backfill.run(limit=100, keep=15, apply=True) == 0
    db = Database(db_path)
    rows = db.conn.execute(
        "SELECT status FROM war_history_cache WHERE clan_tag='#AAA' ORDER BY status"
    ).fetchall()
    assert [row["status"] for row in rows] == ["in_war", "war_ended"]
    db.close()
