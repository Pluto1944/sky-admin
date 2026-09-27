import json

import config
import modules.coc_sync.service as service_module
from scripts.scheduler import _run_current_wars
from shared.db.connection import Database


def test_scheduler_writes_success_and_error_cache(tmp_path, monkeypatch):
    db_path = str(tmp_path / "current-war.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)

    class FakeService:
        def fetch_current_wars(self):
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
