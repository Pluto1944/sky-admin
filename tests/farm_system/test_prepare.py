from __future__ import annotations

import sqlite3

import pytest

from scripts.prepare_farm_system import FARM_TABLES, prepare


def test_prepare_defaults_to_read_only_preview(tmp_path):
    path = tmp_path / "league.db"
    result = prepare(path, apply=False, yes=False, backup_dir=tmp_path / "backups")
    assert result["missing_farm_tables"] == list(FARM_TABLES)
    assert not path.exists()


def test_prepare_requires_yes_and_is_repeatable_with_backup(tmp_path):
    path = tmp_path / "league.db"
    sqlite3.connect(path).close()
    with pytest.raises(ValueError, match="--apply --yes"):
        prepare(path, apply=True, yes=False, backup_dir=tmp_path / "backups")

    first = prepare(path, apply=True, yes=True, backup_dir=tmp_path / "backups")
    second = prepare(path, apply=True, yes=True, backup_dir=tmp_path / "backups")
    assert first["missing_after_apply"] == []
    assert second["missing_farm_tables"] == []
    assert first["backup_path"] and second["backup_path"]
    assert len(list((tmp_path / "backups").glob("*.db"))) >= 1


def test_prepare_does_not_apply_unrelated_main_schema(tmp_path):
    path = tmp_path / "league.db"
    prepare(path, apply=True, yes=True, backup_dir=tmp_path / "backups")
    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert set(FARM_TABLES) <= tables
    assert "alliance_cwl_seasons" not in tables
    assert "league_results" not in tables
