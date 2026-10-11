#!/usr/bin/env python3
"""预览或安全应用互刷系统数据库底座。默认只读预览。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH  # noqa: E402
from shared.db.connection import _FARM_SYSTEM_CORE_DDL  # noqa: E402


FARM_TABLES = (
    "farm_auth_accounts", "farm_clans", "farm_audit_logs", "farm_rounds",
    "farm_round_clans", "farm_matches", "farm_score_ledger",
    "farm_registration_attempts", "farm_auth_events",
)


def _default_db_path() -> Path:
    path = Path(DB_PATH)
    return path if path.is_absolute() else ROOT / path


def _existing_tables(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _backup_database(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"{path.stem}.pre-farm-{stamp}{path.suffix or '.db'}"
    source = sqlite3.connect(str(path))
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"备份完整性检查失败：{result}")
    finally:
        destination.close()
        source.close()
    return target


def ensure_farm_system_schema(path: Path) -> None:
    """只创建互刷系统表，禁止顺带执行主库的其他待发布迁移。"""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(f"BEGIN IMMEDIATE;\n{_FARM_SYSTEM_CORE_DDL}\nCOMMIT;")
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"迁移后完整性检查失败：{result}")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def prepare(path: Path, *, apply: bool, yes: bool, backup_dir: Path) -> dict:
    path = path.resolve()
    existing = _existing_tables(path)
    missing = [table for table in FARM_TABLES if table not in existing]
    result = {
        "db_path": str(path),
        "apply": bool(apply),
        "existing_farm_tables": sorted(set(FARM_TABLES) & existing),
        "missing_farm_tables": missing,
        "backup_path": None,
    }
    if not apply:
        return result
    if not yes:
        raise ValueError("写入必须同时指定 --apply --yes")
    if path.is_file():
        result["backup_path"] = str(_backup_database(path, backup_dir.resolve()))
    ensure_farm_system_schema(path)
    conn = sqlite3.connect(str(path))
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        still_missing = [table for table in FARM_TABLES if table not in tables]
        if still_missing:
            raise RuntimeError(f"迁移后仍缺少互刷表：{', '.join(still_missing)}")
    finally:
        conn.close()
    result["missing_after_apply"] = []
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="预览或应用互刷系统数据库表结构")
    parser.add_argument("--db-path", type=Path, default=_default_db_path())
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "data" / "backups")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare(
            args.db_path, apply=args.apply, yes=args.yes, backup_dir=args.backup_dir
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
