from __future__ import annotations

import sqlite3

import pytest

from scripts.retire_legacy_results import drop_results, preflight
from shared.db.connection import Database


def _create_legacy_results(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE results (
            player_tag TEXT NOT NULL,
            period TEXT NOT NULL,
            league_type TEXT,
            raw_metrics TEXT
        )
        """
    )


def _seed_structured_result(conn: sqlite3.Connection, tag: str = "#P") -> None:
    conn.execute(
        "INSERT INTO accounts (player_tag, account_name) VALUES (?, '甲')", (tag,)
    )
    conn.execute(
        """
        INSERT INTO league_results
            (period, team_index, team_alias, category, player_tag, account_name)
        VALUES ('2026-07', 0, '一队', 'combat', ?, '甲')
        """,
        (tag,),
    )


def test_legacy_results_preflight_and_drop(tmp_path):
    path = tmp_path / "league.db"
    db = Database(str(path))
    db.init_schema()
    _create_legacy_results(db.conn)
    _seed_structured_result(db.conn)
    db.conn.execute(
        "INSERT INTO results VALUES ('#P', '2026-07', 'combat', '{}')"
    )
    db.conn.commit()
    db.close()

    assert preflight(path) == (True, 1, 0)
    drop_results(path)

    conn = sqlite3.connect(path)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'results'"
    ).fetchone() is None
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    conn.close()


def test_legacy_results_drop_refuses_unmigrated_row(tmp_path):
    path = tmp_path / "league.db"
    db = Database(str(path))
    db.init_schema()
    _create_legacy_results(db.conn)
    db.conn.execute(
        "INSERT INTO results VALUES ('#P', '2026-07', 'combat', '{}')"
    )
    db.conn.commit()
    db.close()

    assert preflight(path) == (True, 1, 1)
    with pytest.raises(RuntimeError, match="absent from league_results"):
        drop_results(path)
