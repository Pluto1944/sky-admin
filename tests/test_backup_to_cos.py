from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.backup_to_cos import safe_prefix, sha256_file, snapshot_sqlite, verify_sqlite


def test_snapshot_sqlite_makes_a_consistent_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE records (value TEXT)")
    connection.execute("INSERT INTO records VALUES ('saved')")
    connection.commit()
    connection.close()

    snapshot_sqlite(source, target)

    verify_sqlite(target)
    copied = sqlite3.connect(target)
    assert copied.execute("SELECT value FROM records").fetchone() == ("saved",)
    copied.close()
    assert sha256_file(target)


def test_safe_prefix_rejects_traversal() -> None:
    assert str(safe_prefix("rebuild/sky-admin")) == "rebuild/sky-admin"
    for value in ("", "/absolute", "../escape", "rebuild/../escape"):
        try:
            safe_prefix(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected {value!r} to be rejected")
