from modules.sync_queue import handlers
from modules.sync_queue.repository import SyncQueueRepository
from scripts import scheduler
from shared.db.connection import Database


def test_cwl_handler_preserves_per_war_due_policy(monkeypatch):
    calls = []
    monkeypatch.setattr(
        handlers,
        "_cwl_team",
        lambda _key: ("2026-10", {"clan_tag": "#2QQ", "team_index": 0}),
    )

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "reason": "ok"}

    monkeypatch.setattr(scheduler, "_run_cwl_live", fake_run)

    result = handlers.execute_resource_task("cwl_live", "2026-10:#2QQ")

    assert result["status"] == "success"
    assert calls == [{
        "force": False,
        "teams": [{"clan_tag": "#2QQ", "team_index": 0}],
        "period_override": "2026-10",
    }]


def test_clan_context_accepts_active_farm_validation_interest(tmp_path, monkeypatch):
    tag = "#VALIDATE9"
    path = tmp_path / "farm-sync.db"
    db = Database(str(path))
    db.init_schema()
    SyncQueueRepository(db.conn).upsert_interest(
        source_type="farm_clan_request",
        source_key=f"account:1:tag:{tag}",
        resource_type="clan_profile",
        resource_key=tag,
        priority="interactive",
        desired_interval_seconds=3600,
        metadata={"category": "farm"},
    )
    db.close()
    monkeypatch.setattr(handlers.config, "DB_PATH", str(path))

    assert handlers._clan_context(tag) == {
        "tag": tag, "name": tag, "category": "farm",
    }
