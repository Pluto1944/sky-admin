import json
from datetime import datetime, timezone

import config
import modules.coc_sync.service as service_module
from scripts.scheduler import _archive_current_war, _current_war_refresh_minutes, _run_current_wars
from shared.db.connection import Database


def test_scheduler_writes_success_and_error_cache(tmp_path, monkeypatch):
    db_path = str(tmp_path / "current-war.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)

    class FakeService:
        def fetch_current_wars(self, clans):
            assert [clan["tag"] for clan in clans] == ["#OK", "#BAD"]
            return [
                {
                    "clan_tag": "#OK", "clan_name": "成功部落", "category": "combat",
                    "status": "not_in_war", "rows": [], "error": None,
                    "synced_at": "2026-09-27T01:00:00+00:00",
                },
                {
                    "clan_tag": "#BAD", "clan_name": "失败部落", "category": "farm",
                    "status": "error", "rows": [], "error": "模拟失败",
                    "synced_at": "2026-09-27T01:00:00+00:00",
                },
            ]

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#OK", "name": "成功部落", "category": "combat", "enabled": True},
        {"tag": "#BAD", "name": "失败部落", "category": "farm", "enabled": True},
    ])

    result = _run_current_wars()

    assert result == {"status": "success", "reason": "同步 1 个部落，失败 1"}
    db = Database(db_path)
    rows = db.conn.execute(
        "SELECT clan_tag, status, data_json FROM current_war_cache ORDER BY clan_tag"
    ).fetchall()
    assert [(row["clan_tag"], row["status"]) for row in rows] == [
        ("#BAD", "error"), ("#OK", "not_in_war")
    ]
    assert json.loads(rows[0]["data_json"])["error"] == "模拟失败"
    db.close()


def _seed_cache(db, tag, status, attempted_at, failure_count=0, start_time=None):
    payload = {
        "clan_tag": tag,
        "clan_name": tag,
        "category": "normal",
        "status": status,
        "rows": [],
        "error": "模拟失败" if status == "error" else None,
        "synced_at": attempted_at,
        "start_time": start_time,
    }
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, error, updated_at,
            attempted_at, failure_count)
           VALUES (?, ?, 'normal', ?, ?, ?, ?, ?, ?)""",
        (
            tag, tag, status, json.dumps(payload), payload["error"], attempted_at,
            attempted_at, failure_count,
        ),
    )
    db.conn.commit()


def test_non_active_current_war_states_use_configured_intervals():
    now = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)

    assert _current_war_refresh_minutes({"status": "not_in_war"}, now) == 5
    assert _current_war_refresh_minutes({"status": "war_ended"}, now) == 5
    assert _current_war_refresh_minutes({"status": "cwl"}, now) == 30
    assert _current_war_refresh_minutes(
        {"status": "preparation", "data_json": json.dumps({
            "start_time": "20260930T020000.000Z",
        })},
        now,
    ) == 30
    assert _current_war_refresh_minutes(
        {"status": "preparation", "data_json": json.dumps({
            "start_time": "20260930T003000.000Z",
        })},
        now,
    ) == 2
    assert _current_war_refresh_minutes(
        {"status": "in_war", "failure_count": 2}, now,
    ) == 10


def test_scheduler_keeps_last_successful_snapshot_on_transient_error(tmp_path, monkeypatch):
    db_path = str(tmp_path / "stale-current-war.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#STALE", "name": "保留快照部落", "category": "combat", "enabled": True},
    ])
    db = Database(db_path)
    db.init_schema()
    _seed_cache(db, "#STALE", "in_war", "2026-09-30T00:00:00+00:00")
    db.close()

    class FakeService:
        def fetch_current_wars(self, clans):
            return [{
                "clan_tag": "#STALE", "clan_name": "保留快照部落", "category": "combat",
                "status": "error", "rows": [], "error": "The read operation timed out",
                "synced_at": "2026-09-30T00:02:00+00:00",
            }]

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)

    result = _run_current_wars(
        force=True,
        now=datetime(2026, 9, 30, 0, 2, tzinfo=timezone.utc),
    )

    assert result == {"status": "failed", "reason": "全部 1 个部落同步失败"}
    db = Database(db_path)
    row = db.conn.execute(
        """SELECT status, data_json, error, updated_at, attempted_at, failure_count
           FROM current_war_cache WHERE clan_tag = '#STALE'"""
    ).fetchone()
    assert row["status"] == "in_war"
    assert json.loads(row["data_json"])["status"] == "in_war"
    assert row["error"] == "The read operation timed out"
    assert row["updated_at"] == "2026-09-30T00:00:00+00:00"
    assert row["attempted_at"] == "2026-09-30T00:02:00+00:00"
    assert row["failure_count"] == 1
    db.close()


def test_scheduler_refreshes_each_clan_by_cached_state(tmp_path, monkeypatch):
    db_path = str(tmp_path / "state-aware.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#WAR", "name": "战斗日", "enabled": True},
        {"tag": "#PREP-NEAR", "name": "临近开战", "enabled": True},
        {"tag": "#PREP-FAR", "name": "准备日", "enabled": True},
        {"tag": "#IDLE", "name": "无战争", "enabled": True},
        {"tag": "#ENDED", "name": "已结束", "enabled": True},
    ])
    db = Database(db_path)
    db.init_schema()
    last_attempt = "2026-09-30T00:00:00+00:00"
    _seed_cache(db, "#WAR", "in_war", last_attempt)
    _seed_cache(
        db, "#PREP-NEAR", "preparation", last_attempt,
        start_time="20260930T003000.000Z",
    )
    _seed_cache(
        db, "#PREP-FAR", "preparation", last_attempt,
        start_time="20260930T020000.000Z",
    )
    _seed_cache(db, "#IDLE", "not_in_war", last_attempt)
    _seed_cache(db, "#ENDED", "war_ended", last_attempt)
    db.close()

    requested = []

    class FakeService:
        def fetch_current_wars(self, clans):
            requested.extend(clan["tag"] for clan in clans)
            return [
                {
                    "clan_tag": clan["tag"], "clan_name": clan["name"],
                    "category": "normal", "status": "in_war", "rows": [],
                    "error": None, "synced_at": "2026-09-30T00:02:00+00:00",
                }
                for clan in clans
            ]

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)

    result = _run_current_wars(now=datetime(2026, 9, 30, 0, 2, tzinfo=timezone.utc))

    assert requested == ["#WAR", "#PREP-NEAR"]
    assert result == {"status": "success", "reason": "同步 2 个部落，按状态跳过 3"}


def test_scheduler_uses_error_backoff_and_force_override(tmp_path, monkeypatch):
    db_path = str(tmp_path / "backoff.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "CLANS", [
        {"tag": "#ERROR", "name": "失败部落", "enabled": True},
    ])
    db = Database(db_path)
    db.init_schema()
    _seed_cache(db, "#ERROR", "error", "2026-09-30T00:00:00+00:00", failure_count=3)
    db.close()

    requested = []

    class FakeService:
        def fetch_current_wars(self, clans):
            requested.extend(clan["tag"] for clan in clans)
            return [{
                "clan_tag": "#ERROR", "clan_name": "失败部落", "category": "normal",
                "status": "not_in_war", "rows": [], "error": None,
                "synced_at": "2026-09-30T00:05:00+00:00",
            }]

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)

    skipped = _run_current_wars(now=datetime(2026, 9, 30, 0, 5, tzinfo=timezone.utc))
    forced = _run_current_wars(
        force=True,
        now=datetime(2026, 9, 30, 0, 5, tzinfo=timezone.utc),
    )

    assert skipped == {"status": "skipped", "reason": "1 个部落均未到刷新时间"}
    assert forced == {"status": "success", "reason": "同步 1 个部落"}
    assert requested == ["#ERROR"]

    db = Database(db_path)
    row = db.conn.execute(
        "SELECT failure_count, attempted_at FROM current_war_cache WHERE clan_tag = '#ERROR'"
    ).fetchone()
    assert row["failure_count"] == 0
    assert row["attempted_at"] == "2026-09-30T00:05:00+00:00"
    db.close()


def test_archive_current_war_keeps_latest_fifteen_ended_wars(tmp_path):
    db = Database(str(tmp_path / "history.sqlite3"))
    db.init_schema()
    for day in range(1, 18):
        item = {
            "clan_tag": "#AAA", "clan_name": "我方", "category": "combat",
            "status": "war_ended", "state": "warEnded", "war_type": "random",
            "attacks_per_member": 2, "preparation_start_time": f"202609{day:02d}T000000.000Z",
            "start_time": f"202609{day:02d}T230000.000Z",
            "end_time": f"202609{day + 1:02d}T230000.000Z", "result": "victory",
            "opponent": {"tag": f"#B{day}", "name": f"对手{day}"},
            "rows": [], "synced_at": "2026-10-01T00:00:00+00:00",
        }
        assert _archive_current_war(db, item)
    db.conn.commit()

    rows = db.conn.execute(
        "SELECT end_time FROM war_history_cache WHERE clan_tag='#AAA' ORDER BY end_time"
    ).fetchall()
    assert len(rows) == 15
    assert rows[0]["end_time"] == "20260904T230000.000Z"
    db.close()


def test_historical_backfill_does_not_remove_active_snapshot(tmp_path):
    db = Database(str(tmp_path / "history-active.sqlite3"))
    db.init_schema()
    active = {
        "clan_tag": "#AAA", "clan_name": "我方", "category": "combat",
        "status": "in_war", "state": "inWar", "war_type": "random",
        "attacks_per_member": 2, "preparation_start_time": "20261001T000000.000Z",
        "start_time": "20261002T000000.000Z", "end_time": "20261003T000000.000Z",
        "result": "leading", "opponent": {"tag": "#ACTIVE", "name": "当前对手"},
        "rows": [], "synced_at": "2026-10-02T01:00:00+00:00",
    }
    ended = {
        **active,
        "status": "war_ended", "state": "warEnded",
        "preparation_start_time": "20260920T000000.000Z",
        "start_time": "20260921T000000.000Z", "end_time": "20260922T000000.000Z",
        "result": "victory", "opponent": {"tag": "#ENDED", "name": "历史对手"},
    }
    assert _archive_current_war(db, active)
    assert _archive_current_war(db, ended, cleanup_active=False)
    db.conn.commit()

    rows = db.conn.execute(
        "SELECT status FROM war_history_cache WHERE clan_tag='#AAA' ORDER BY status"
    ).fetchall()
    assert [row["status"] for row in rows] == ["in_war", "war_ended"]
    db.close()
