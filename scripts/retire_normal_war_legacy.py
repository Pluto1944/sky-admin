#!/usr/bin/env python3
"""在完整普通战档案验证后，显式退役旧普通战投影表。

默认只做检查。传入 ``--yes`` 时先创建一份可校验 COS 备份，再在一个 SQLite
事务中删除已无消费者的 ``war_results`` 与 ``member_combat_stats_cache``。
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

LEGACY_TABLES = ("war_results", "member_combat_stats_cache")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def preflight(db_path: Path) -> tuple[dict[str, int], int]:
    """验证新版普通战档案完整，返回旧表行数与未物化战争数。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"SQLite integrity check failed: {integrity!r}")
        legacy_counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in LEGACY_TABLES
            if _table_exists(conn, table)
        }
        missing_facts = int(conn.execute(
            """SELECT COUNT(*) FROM war_history_cache h
               WHERE h.status = 'war_ended'
                 AND NOT EXISTS (
                     SELECT 1 FROM member_war_facts f
                     WHERE f.clan_tag = h.clan_tag AND f.war_key = h.war_key
                       AND f.metric_version >= 2
                 )"""
        ).fetchone()[0])
        return legacy_counts, missing_facts
    finally:
        conn.close()


def drop_legacy_tables(db_path: Path) -> None:
    """再次检查并在同一事务中删除旧表。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        missing_facts = int(conn.execute(
            """SELECT COUNT(*) FROM war_history_cache h
               WHERE h.status = 'war_ended'
                 AND NOT EXISTS (
                     SELECT 1 FROM member_war_facts f
                     WHERE f.clan_tag = h.clan_tag AND f.war_key = h.war_key
                       AND f.metric_version >= 2
                 )"""
        ).fetchone()[0])
        if missing_facts:
            raise RuntimeError(f"refusing to retire legacy tables: {missing_facts} wars lack v2 facts")
        for table in LEGACY_TABLES:
            if _table_exists(conn, table):
                conn.execute(f"DROP TABLE {table}")
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise RuntimeError(f"foreign key check failed: {fk_issues!r}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="确认删除两个旧投影表")
    parser.add_argument("--dry-run", action="store_true", help="只执行完整性检查")
    args = parser.parse_args()

    from shared.config.env_loader import load_env

    load_env()
    import config
    from scripts.backup_to_cos import DEFAULT_MOUNT, DEFAULT_PREFIX, backup, safe_prefix

    db_path = (PROJECT_ROOT / config.DB_PATH).resolve()
    counts, missing_facts = preflight(db_path)
    print(f"preflight: legacy_rows={counts}, missing_v2_facts={missing_facts}")
    if missing_facts:
        return 1
    if args.dry_run:
        return 0
    if not args.yes:
        print("refusing to drop legacy tables without --yes", file=sys.stderr)
        return 2

    mount = Path(os.getenv("COS_BACKUP_MOUNT", DEFAULT_MOUNT))
    prefix = safe_prefix(os.getenv("COS_BACKUP_PREFIX", DEFAULT_PREFIX))
    backup(mount=mount, prefix=prefix, dry_run=False)
    drop_legacy_tables(db_path)
    print("retired normal-war legacy tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
