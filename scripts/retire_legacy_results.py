#!/usr/bin/env python3
"""Safely retire the obsolete ``results`` table after CWL migration.

The command is intentionally explicit: it verifies that every legacy row has
already been migrated to ``league_results``, creates a fresh verified COS
recovery backup, and only then drops the table in one SQLite transaction.
Run it only after code without legacy-table readers/writers has been deployed.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _missing_structured_rows(conn: sqlite3.Connection) -> int:
    """Count legacy rows that cannot be represented by structured CWL data."""
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM results AS legacy
            WHERE NOT EXISTS (
                SELECT 1
                FROM league_results AS structured
                WHERE structured.period = legacy.period
                  AND structured.player_tag = legacy.player_tag
                  AND structured.category = legacy.league_type
            )
            """
        ).fetchone()[0]
    )


def preflight(db_path: Path) -> tuple[bool, int, int]:
    """Validate the legacy table and return ``(exists, rows, unmigrated)``."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not _table_exists(conn, "results"):
            return False, 0, 0
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"SQLite integrity check failed: {integrity!r}")
        row_count = int(conn.execute("SELECT COUNT(*) FROM results").fetchone()[0])
        return True, row_count, _missing_structured_rows(conn)
    finally:
        conn.close()


def drop_results(db_path: Path) -> None:
    """Drop the legacy table after a second in-transaction consistency check."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        if not _table_exists(conn, "results"):
            conn.rollback()
            return
        missing = _missing_structured_rows(conn)
        if missing:
            raise RuntimeError(
                f"refusing to drop results: {missing} rows are absent from league_results"
            )
        conn.execute("DROP TABLE results")
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise RuntimeError(f"foreign key check failed after drop: {fk_issues!r}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm the irreversible table drop")
    parser.add_argument("--dry-run", action="store_true", help="run preflight only; do not back up or write")
    return parser.parse_args()


def main() -> int:
    from shared.config.env_loader import load_env

    load_env()
    import config
    from scripts.backup_to_cos import DEFAULT_MOUNT, DEFAULT_PREFIX, backup, safe_prefix

    args = parse_args()
    db_path = (PROJECT_ROOT / config.DB_PATH).resolve()
    if not db_path.is_file():
        print(f"legacy retirement failed: database does not exist: {db_path}", file=sys.stderr)
        return 1

    exists, row_count, missing = preflight(db_path)
    if not exists:
        print("results table is already absent; nothing to do")
        return 0
    if missing:
        print(
            f"legacy retirement blocked: {missing}/{row_count} results rows are not in league_results",
            file=sys.stderr,
        )
        return 1
    print(f"preflight passed: {row_count} legacy rows are represented in league_results")
    if args.dry_run:
        print("dry run complete; no COS backup or database write was performed")
        return 0
    if not args.yes:
        print("refusing to drop results without --yes", file=sys.stderr)
        return 2

    mount = Path(os.getenv("COS_BACKUP_MOUNT", DEFAULT_MOUNT))
    prefix = safe_prefix(os.getenv("COS_BACKUP_PREFIX", DEFAULT_PREFIX))
    backup(mount=mount, prefix=prefix, dry_run=False)
    drop_results(db_path)
    print("legacy results table dropped after verified COS backup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
