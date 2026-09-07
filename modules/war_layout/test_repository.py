import sqlite3
from datetime import datetime, timezone

from .repository import WarLayoutRepository


def test_duplicate_fingerprint_is_idempotent_and_status_can_retry():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    repo = WarLayoutRepository(db)
    repo.initialize()
    fields = dict(post_id="p1", author="a", fingerprint="f1", layout_url="https://link/a", image_url="https://img/a")
    assert repo.add_discovered(**fields) is True
    assert repo.add_discovered(**fields) is False
    repo.update_status("f1", "failed", error_message="temporary")
    assert repo.get("f1")["status"] == "failed"
    repo.update_status("f1", "draft_created", draft_media_id="m1", error_message=None)
    row = repo.get("f1")
    assert row["status"] == "draft_created"
    assert row["draft_media_id"] == "m1"
    assert row["error_message"] is None


def test_sync_watermark_is_persisted_per_author():
    repo = WarLayoutRepository(sqlite3.connect(":memory:"))
    repo.initialize()
    timestamp = datetime(2026, 9, 6, 1, 2, 3, tzinfo=timezone.utc)
    repo.set_last_pull_time("alice", timestamp)
    assert repo.get_last_pull_time("alice") == timestamp
    assert repo.get_last_pull_time("bob") is None


def test_sync_history_records_window_and_advances_only_on_success():
    repo = WarLayoutRepository(sqlite3.connect(":memory:"))
    repo.initialize()
    start = datetime(2026, 9, 6, 1, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)
    repo.record_sync("alice", window_start=start, window_end=end, status="failed", posts=2, error_message="timeout")
    assert repo.get_last_pull_time("alice") is None
    repo.record_sync("alice", window_start=start, window_end=end, status="success", posts=2, layouts=1)
    assert repo.get_last_pull_time("alice") == end
    row = repo.connection.execute("SELECT status, posts, layouts FROM war_layout_sync_history ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ("success", 2, 1)


def test_global_sync_cursor_advances_only_after_success():
    repo = WarLayoutRepository(sqlite3.connect(":memory:"))
    repo.initialize()
    start = datetime(2026, 9, 6, 1, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)
    repo.record_global_sync(window_start=start, window_end=end, status="failed", posts=3, error_message="timeout")
    assert repo.get_global_last_pull_time() is None
    repo.record_global_sync(window_start=start, window_end=end, status="success", posts=3, layouts=2)
    assert repo.get_global_last_pull_time() == end
    row = repo.connection.execute("SELECT author, status FROM war_layout_sync_history ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ("*", "success")
