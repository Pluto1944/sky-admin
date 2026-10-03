from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

import scripts.archive_local_backups_to_cos as archive_module
from scripts.archive_local_backups_to_cos import archive, backup_files, local_prune_candidates
from scripts.backup_to_cos import safe_prefix


def _backup(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE records (value TEXT)")
    connection.execute("INSERT INTO records VALUES (?)", (value,))
    connection.commit()
    connection.close()


def test_local_prune_candidates_keep_newest(tmp_path: Path) -> None:
    files = []
    for index in range(3):
        path = tmp_path / f"backup-{index}.db"
        path.touch()
        path.chmod(0o600)
        path_stat = path.stat()
        os.utime(path, (path_stat.st_atime, path_stat.st_mtime + index))
        files.append(path)

    assert [path.name for path in local_prune_candidates(files, 2)] == ["backup-0.db"]


def test_backup_files_detects_sqlite_when_db_is_not_the_final_suffix(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "league.db.before-migration"
    _backup(sqlite_path, "saved")
    (tmp_path / "notes.txt").write_text("not a database", encoding="utf-8")

    assert [path.name for path in backup_files(tmp_path)] == ["league.db.before-migration"]


def test_archive_verifies_upload_then_prunes_old_local_backups(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    source = project_root / "data" / "backups"
    source.mkdir(parents=True)
    files = []
    for index in range(3):
        path = source / f"backup-{index}.db"
        _backup(path, str(index))
        path_stat = path.stat()
        os.utime(path, (path_stat.st_atime, path_stat.st_mtime + index))
        files.append(path)

    mount = tmp_path / "mount"
    mount.mkdir()
    monkeypatch.setattr(archive_module, "DEFAULT_SOURCE_DIR", source)
    monkeypatch.setattr(archive_module, "is_cosfs_mount", lambda value: value == mount)
    destination = archive(
        mount=mount,
        prefix=safe_prefix("archive/sky-admin/local-db-backups"),
        source_dir=source,
        apply=True,
        prune_local=True,
        keep_local=2,
        now=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )

    assert destination is not None
    assert (destination / "manifest.json").is_file()
    assert sorted(path.name for path in source.iterdir()) == ["backup-1.db", "backup-2.db"]
    assert sorted(path.name for path in destination.iterdir()) == ["backup-0.db", "backup-1.db", "backup-2.db", "manifest.json"]
