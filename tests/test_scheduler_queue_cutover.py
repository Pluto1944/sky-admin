from datetime import datetime, timezone

import config
from scripts import scheduler


def test_live_types_do_not_disable_legacy_jobs_without_worker(monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "current_war,cwl_live")
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "false")

    assert scheduler._queue_live_types() == set()


def test_legacy_current_war_and_cwl_jobs_skip_when_worker_owns_type(monkeypatch):
    monkeypatch.setattr(
        scheduler, "_queue_live_types", lambda: {"current_war", "cwl_live"},
    )

    assert scheduler._run_current_wars() == {
        "status": "skipped", "reason": "current_war 已由 M4 Worker 接管",
    }
    assert scheduler._run_cwl_live(
        now=datetime(2026, 10, 5, tzinfo=timezone.utc),
    ) == {
        "status": "skipped", "reason": "cwl_live 已由 M4 Worker 接管",
    }


def test_legacy_coc_sync_skips_when_both_resource_types_are_cut_over(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "queue-cutover.db"))
    monkeypatch.setattr(
        scheduler, "_queue_live_types", lambda: {"clan_profile", "clan_members"},
    )

    assert scheduler._run_coc_sync() == {
        "status": "skipped",
        "reason": "clan_members 和 clan_profile 已由 M4 Worker 接管",
    }
