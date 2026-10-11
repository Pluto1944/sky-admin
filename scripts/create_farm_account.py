#!/usr/bin/env python3
"""受控创建互刷系统账号，不在命令行参数中传递密码。"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH  # noqa: E402
from modules.farm_system.repository import FarmAccountRepository  # noqa: E402
from modules.farm_system.service import FarmAuthService  # noqa: E402
from shared.db.connection import Database  # noqa: E402
from scripts.prepare_farm_system import ensure_farm_system_schema  # noqa: E402


def _default_db_path() -> str:
    path = Path(DB_PATH)
    return str(path if path.is_absolute() else ROOT / path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建互刷系统独立账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", choices=("creator", "admin", "member"), default="member")
    parser.add_argument("--db-path", default=_default_db_path())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = getpass.getpass("初始密码（不会回显）: ")
    confirm = getpass.getpass("再次输入初始密码: ")
    if password != confirm:
        print("两次密码不一致", file=sys.stderr)
        return 2

    ensure_farm_system_schema(Path(args.db_path))
    db = Database(args.db_path)
    try:
        account = FarmAuthService(FarmAccountRepository(db.conn)).create_account(
            username=args.username,
            display_name=args.display_name,
            password=password,
            role=args.role,
        )
        print(
            f"已创建互刷账号 id={account['id']} username={account['username']} "
            f"role={account['role']}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
