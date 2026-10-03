import sqlite3

from scripts.retire_normal_war_legacy import drop_legacy_tables, preflight
from shared.db.connection import Database


def test_retire_normal_war_legacy_tables_after_v2_fact_check(tmp_path):
    path = tmp_path / "league.db"
    db = Database(str(path))
    db.init_schema()
    db.conn.execute("CREATE TABLE war_results (id INTEGER PRIMARY KEY)")
    db.conn.execute("CREATE TABLE member_combat_stats_cache (player_tag TEXT PRIMARY KEY)")
    db.conn.execute("INSERT INTO war_results VALUES (1)")
    db.conn.execute("INSERT INTO member_combat_stats_cache VALUES ('#P1')")
    db.conn.commit()
    db.close()

    counts, missing = preflight(path)
    assert counts == {"war_results": 1, "member_combat_stats_cache": 1}
    assert missing == 0

    drop_legacy_tables(path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'war_results'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'member_combat_stats_cache'"
        ).fetchone() is None
    finally:
        conn.close()
