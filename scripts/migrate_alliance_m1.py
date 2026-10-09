#!/usr/bin/env python3
"""Preview or apply the M1 Sky alliance tenant mapping.

Preview is the default and opens SQLite read-only. Applying is explicit, creates a
consistent local backup first, and never derives alliance roles from the legacy
``wechat_users.role`` column.
"""
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


def _read_assignments(path: Path | None) -> list[dict]:
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("members")
    if not isinstance(raw, list):
        raise ValueError("membership file must be a JSON list or an object with a members list")
    return raw


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"{db_path.stem}-before-m1-{stamp}{db_path.suffix or '.db'}"
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
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / config.DB_PATH,
        help="SQLite database path (defaults to config.DB_PATH)",
    )
    parser.add_argument("--apply", action="store_true", help="write the M1 mapping")
    parser.add_argument("--yes", action="store_true", help="confirm the explicit apply operation")
    parser.add_argument(
        "--members-file",
        type=Path,
        help="reviewed JSON role assignments: [{\"user_id\": 1, \"role\": \"member\"}]",
    )
    parser.add_argument(
        "--expected-config-hash",
        help="refuse apply if the current clan manifest differs from the reviewed preview",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "backups" / "m1",
        help="directory for the mandatory pre-apply SQLite backup",
    )
    return parser.parse_args()


def main() -> int:
    import config
    from modules.alliance.migration import (
        apply_sky_migration,
        build_existing_user_assignments,
        build_sky_manifest,
        preview_sky_migration,
    )
    from shared.db.connection import Database

    args = parse_args()
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(f"database does not exist: {db_path}", file=sys.stderr)
        return 1
    try:
        assignments = _read_assignments(args.members_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"invalid membership file: {exc}", file=sys.stderr)
        return 1

    manifest = build_sky_manifest(config.CLANS)
    if args.expected_config_hash and args.expected_config_hash != manifest["config_hash"]:
        print("config hash differs from the reviewed preview; refusing to continue", file=sys.stderr)
        return 1

    if not args.apply:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            assignments = build_existing_user_assignments(conn, assignments)
            result = preview_sky_migration(conn, config.CLANS, assignments)
        finally:
            conn.close()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if not args.yes:
        print("refusing to apply without --yes; preview is the default", file=sys.stderr)
        return 2

    backup_path = _backup_database(db_path, args.backup_dir.resolve())
    db = Database(str(db_path))
    try:
        db.init_schema()
        assignments = build_existing_user_assignments(db.conn, assignments)
        result = apply_sky_migration(db.conn, config.CLANS, assignments)
        integrity = db.conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = [tuple(row) for row in db.conn.execute("PRAGMA foreign_key_check")]
        if integrity != "ok" or foreign_key_issues:
            raise RuntimeError(
                f"post-apply database checks failed: integrity={integrity}, "
                f"foreign_key_issues={foreign_key_issues}"
            )
    finally:
        db.close()
    result["backup_path"] = str(backup_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
