from modules.sync_queue import handlers
from scripts import scheduler


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
