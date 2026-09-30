import json
from datetime import datetime, timezone

import config
import modules.coc_sync.service as service_module
from scripts.scheduler import _current_war_refresh_minutes, _run_current_wars
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
