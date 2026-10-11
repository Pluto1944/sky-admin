#!/usr/bin/env python3
"""Preview or apply the M3.1 Sky CWL monthly configuration migration."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def _preview(conn: sqlite3.Connection) -> dict:
    legacy = [
        {"period": row[0], "team_count": int(row[1])}
        for row in conn.execute(
            """SELECT period, COUNT(*) FROM league_teams
               WHERE category IN ('combat', 'shell')
               GROUP BY period ORDER BY period"""
        ).fetchall()
    ]
    existing = []
    if _table_exists(conn, "alliance_cwl_seasons"):
        existing = [
            {"period": row[0], "status": row[1], "team_count": int(row[2])}
            for row in conn.execute(
                """SELECT seasons.period, seasons.status, COUNT(teams.id)
                   FROM alliance_cwl_seasons AS seasons
                   JOIN alliances ON alliances.id = seasons.alliance_id
                   LEFT JOIN alliance_cwl_teams AS teams ON teams.season_id = seasons.id
                   WHERE alliances.alliance_key = 'sky-internal'
                   GROUP BY seasons.id ORDER BY seasons.period"""
            ).fetchall()
        ]
    return {
        "mode": "preview",
        "legacy_period_count": len(legacy),
        "legacy_team_count": sum(item["team_count"] for item in legacy),
        "legacy_periods": legacy,
        "existing_sky_seasons": existing,
    }


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"{db_path.stem}-before-m31-cwl-{stamp}{db_path.suffix or '.db'}"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("backup integrity check failed")
    finally:
        target.close()
        source.close()
    return destination


def parse_args() -> argparse.Namespace:
    import config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / config.DB_PATH)
    parser.add_argument("--apply", action="store_true", help="write schema and Sky mappings")
    parser.add_argument("--yes", action="store_true", help="confirm the explicit apply operation")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "backups" / "m31-cwl",
    )
    return parser.parse_args()


def main() -> int:
    from modules.alliance.cwl_config import sync_sky_league_teams
    from shared.db.connection import Database

    args = parse_args()
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(f"database does not exist: {db_path}", file=sys.stderr)
        return 1
    if not args.apply:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            print(json.dumps(_preview(conn), ensure_ascii=False, indent=2, sort_keys=True))
        finally:
            conn.close()
        return 0
    if not args.yes:
        print("refusing to apply without --yes; preview is the default", file=sys.stderr)
        return 2

    backup = _backup_database(db_path, args.backup_dir.resolve())
    db = Database(str(db_path))
    try:
        db.init_schema()
        result = sync_sky_league_teams(db.conn)
        integrity = db.conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = [tuple(row) for row in db.conn.execute("PRAGMA foreign_key_check")]
        if integrity != "ok" or foreign_key_issues:
            raise RuntimeError(
                f"post-apply database checks failed: integrity={integrity}, "
                f"foreign_key_issues={foreign_key_issues}"
            )
    finally:
        db.close()
    print(json.dumps({
        "mode": "apply",
        **result,
        "backup_path": str(backup),
        "integrity": "ok",
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
