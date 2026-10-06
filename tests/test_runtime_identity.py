from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.db.connection import Database
from shared.runtime_identity import RuntimeIdentity, capture_runtime_identity
from shared.service_runtime import (
    build_system_version,
    get_service_runtime,
    record_service_runtime,
    touch_service_runtime,
)


def _identity(component="api", *, dirty=False):
    return RuntimeIdentity(
        component=component,
        release_version="v1.3.0",
        git_commit="abc123" * 6 + "abcd",
        git_describe="v1.3.0-2-gabc123",
        tracked_dirty=dirty,
        started_at="2026-10-06T00:00:00+00:00",
    )


def test_capture_runtime_identity_ignores_untracked_files(tmp_path: Path, monkeypatch):
    (tmp_path / "VERSION").write_text("v2.1.0\n", encoding="utf-8")

    def fake_git(_root, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return "f" * 40
        if args[0] == "describe":
            return "v2.1.0"
        if args[0] == "status":
            return ""
        raise AssertionError(args)

    monkeypatch.setattr("shared.runtime_identity._git_output", fake_git)
    identity = capture_runtime_identity(
        "api",
        project_root=tmp_path,
        started_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )

    assert identity.release_version == "v2.1.0"
    assert identity.git_commit == "f" * 40
    assert identity.tracked_dirty is False
    assert identity.started_at == "2026-10-06T00:00:00+00:00"


def test_service_runtime_roundtrip_and_heartbeat():
    db = Database(":memory:")
    db.init_schema()
    identity = _identity("scheduler")
    record_service_runtime(db.conn, identity, heartbeat_at="2026-10-06T00:00:00+00:00")
    touch_service_runtime(
        db.conn, "scheduler", heartbeat_at="2026-10-06T00:01:00+00:00"
    )

    runtime = get_service_runtime(db.conn, "scheduler")
    assert runtime["release_version"] == "v1.3.0"
    assert runtime["git_commit"] == identity.git_commit
    assert runtime["tracked_dirty"] is False
    assert runtime["heartbeat_at"] == "2026-10-06T00:01:00+00:00"


def test_system_version_requires_live_clean_matching_scheduler():
    api = _identity()
    scheduler = {
        **_identity("scheduler").as_dict(),
        "heartbeat_at": "2026-10-06T00:01:00+00:00",
    }
    result = build_system_version(
        api,
        scheduler,
        now=datetime(2026, 10, 6, 0, 2, tzinfo=timezone.utc),
    )

    assert result["healthy"] is True
    assert result["consistent"] is True
    assert result["status"] == "ok"

    stale = build_system_version(
        api,
        scheduler,
        now=datetime(2026, 10, 6, 0, 2, tzinfo=timezone.utc)
        + timedelta(minutes=20),
    )
    assert stale["healthy"] is False
    assert stale["consistent"] is False
    assert stale["components"]["scheduler"]["health"] == "stale"


def test_system_version_marks_dirty_runtime_inconsistent():
    api = _identity(dirty=True)
    scheduler = {
        **_identity("scheduler").as_dict(),
        "heartbeat_at": "2026-10-06T00:01:00+00:00",
    }
    result = build_system_version(
        api,
        scheduler,
        now=datetime(2026, 10, 6, 0, 2, tzinfo=timezone.utc),
    )

    assert result["healthy"] is True
    assert result["consistent"] is False
    assert result["status"] == "degraded"
