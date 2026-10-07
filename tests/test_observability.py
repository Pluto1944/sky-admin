from datetime import datetime, timezone
from urllib.error import HTTPError

from scripts.observability_report import build_report
from scripts.scheduler import JOBS, _ensure_rows, run_one
from shared.db.connection import Database
from shared.observability import (
    capture_external_requests,
    finish_job_run,
    observe_external_request,
    prune_observability_history,
    start_job_run,
)


def test_request_observation_classifies_wrapped_http_429():
    with capture_external_requests("cwl_live") as collector:
        try:
            with observe_external_request(
                "coc_official", "cwl_war", resource_key="#WAR",
            ):
                try:
                    raise HTTPError("https://example.invalid", 429, "limited", {}, None)
                except HTTPError as exc:
                    raise RuntimeError("upstream failed") from exc
        except RuntimeError:
            pass

    assert len(collector.events) == 1
    event = collector.events[0]
    assert event.job_id == "cwl_live"
    assert event.provider == "coc_official"
    assert event.operation == "cwl_war"
    assert event.resource_key == "#WAR"
    assert event.outcome == "rate_limited"
    assert event.http_status == 429


def test_expected_http_status_is_not_counted_as_external_failure():
    with capture_external_requests("cwl_live") as collector:
        try:
            with observe_external_request(
                "coc_official",
                "cwl_group",
                expected_http_statuses=(404,),
            ):
                raise HTTPError("https://example.invalid", 404, "missing", {}, None)
        except HTTPError:
            pass

    db = Database(":memory:")
    db.init_schema()
    db.conn.execute(
        "INSERT INTO sync_jobs (job_id, job_name) VALUES ('cwl_live', 'CWL')"
    )
    db.conn.commit()
    run_id = start_job_run(db.conn, "cwl_live", "2026-10-07T00:00:00+00:00")
    finish_job_run(
        db.conn,
        run_id=run_id,
        job_id="cwl_live",
        finished_at="2026-10-07T00:00:01+00:00",
        status="success",
        duration_ms=1000,
        reason="not in league",
        events=collector.events,
    )

    run = db.conn.execute(
        "SELECT * FROM sync_job_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert collector.events[0].outcome == "expected_http_status"
    assert run["external_request_count"] == 1
    assert run["external_failure_count"] == 0
    db.close()


def test_scheduler_persists_job_run_and_external_request(monkeypatch):
    def observed_job():
        with observe_external_request(
            "coc_official", "clan_profile", resource_key="#2QQ",
        ):
            pass
        return {"status": "success", "reason": "ok"}

    monkeypatch.setitem(JOBS, "observed_test", {
        "name": "观测测试",
        "interval": 60,
        "run": observed_job,
    })
    db = Database(":memory:")
    db.init_schema()
    _ensure_rows(db)

    result = run_one(db, "observed_test")

    assert result == {"status": "success", "reason": "ok"}
    run = db.conn.execute(
        "SELECT * FROM sync_job_runs WHERE job_id = 'observed_test'"
    ).fetchone()
    assert run["status"] == "success"
    assert run["external_request_count"] == 1
    assert run["external_failure_count"] == 0
    event = db.conn.execute(
        "SELECT * FROM external_request_events WHERE run_id = ?", (run["id"],)
    ).fetchone()
    assert event["provider"] == "coc_official"
    assert event["operation"] == "clan_profile"
    assert event["outcome"] == "success"
    db.close()


def test_observability_write_failure_does_not_change_job_result(monkeypatch):
    def fail_start(*_args, **_kwargs):
        raise RuntimeError("metrics down")

    monkeypatch.setitem(JOBS, "metrics_failure_test", {
        "name": "观测失败测试",
        "interval": 60,
        "run": lambda: {"status": "success", "reason": "business ok"},
    })
    monkeypatch.setattr(
        "scripts.scheduler.start_job_run",
        fail_start,
    )
    db = Database(":memory:")
    db.init_schema()
    _ensure_rows(db)

    result = run_one(db, "metrics_failure_test")

    assert result == {"status": "success", "reason": "business ok"}
    row = db.conn.execute(
        "SELECT last_status FROM sync_jobs WHERE job_id = 'metrics_failure_test'"
    ).fetchone()
    assert row["last_status"] == "success"
    db.close()


def test_observability_finish_failure_does_not_change_job_result(monkeypatch):
    def fail_finish(*_args, **_kwargs):
        raise RuntimeError("metrics flush down")

    monkeypatch.setitem(JOBS, "metrics_finish_failure_test", {
        "name": "观测完成失败测试",
        "interval": 60,
        "run": lambda: {"status": "success", "reason": "business ok"},
    })
    monkeypatch.setattr("scripts.scheduler.finish_job_run", fail_finish)
    db = Database(":memory:")
    db.init_schema()
    _ensure_rows(db)

    result = run_one(db, "metrics_finish_failure_test")

    assert result == {"status": "success", "reason": "business ok"}
    row = db.conn.execute(
        "SELECT last_status FROM sync_jobs WHERE job_id = 'metrics_finish_failure_test'"
    ).fetchone()
    assert row["last_status"] == "success"
    db.close()


def test_prune_removes_old_runs_and_request_events():
    db = Database(":memory:")
    db.init_schema()
    db.conn.execute(
        "INSERT INTO sync_jobs (job_id, job_name) VALUES ('old_job', 'old')"
    )
    db.conn.commit()
    run_id = start_job_run(db.conn, "old_job", "2026-08-01T00:00:00+00:00")
    with capture_external_requests("old_job") as collector:
        with observe_external_request("coc_official", "clan_profile"):
            pass
    finish_job_run(
        db.conn,
        run_id=run_id,
        job_id="old_job",
        finished_at="2026-08-01T00:00:01+00:00",
        status="success",
        duration_ms=1000,
        reason="ok",
        events=collector.events,
    )

    deleted = prune_observability_history(
        db.conn,
        retention_days=30,
        now=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )

    assert deleted == 1
    assert db.conn.execute("SELECT COUNT(*) FROM sync_job_runs").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM external_request_events").fetchone()[0] == 0
    db.close()


def test_report_summarizes_requests_jobs_and_freshness():
    db = Database(":memory:")
    db.init_schema()
    db.conn.execute(
        "INSERT INTO sync_jobs (job_id, job_name) VALUES ('report_job', 'report')"
    )
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, updated_at,
            attempted_at, failure_count, last_success_at)
           VALUES ('#2QQ', '云深', 'combat', 'in_war', '{}', ?, ?, 0, ?)""",
        (
            "2026-10-07T00:00:00+00:00",
            "2026-10-07T00:00:00+00:00",
            "2026-10-07T00:00:00+00:00",
        ),
    )
    db.conn.commit()
    run_id = start_job_run(db.conn, "report_job", "2026-10-07T00:00:00+00:00")
    with capture_external_requests("report_job") as collector:
        with observe_external_request("coc_official", "current_war"):
            pass
    finish_job_run(
        db.conn,
        run_id=run_id,
        job_id="report_job",
        finished_at="2026-10-07T00:00:01+00:00",
        status="success",
        duration_ms=1000,
        reason="ok",
        events=collector.events,
    )

    report = build_report(
        db.conn,
        hours=24,
        now=datetime(2026, 10, 7, 1, tzinfo=timezone.utc),
    )

    assert report["requests"][0]["requests"] == 1
    assert report["requests"][0]["success_rate"] == 1.0
    assert report["jobs"][0]["external_requests"] == 1
    assert report["freshness"]["current_wars"][0]["clan_tag"] == "#2QQ"
    db.close()
