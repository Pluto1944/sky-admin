#!/usr/bin/env python3
"""互刷独立账号的受控运维入口。"""
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


def _password() -> str:
    password = getpass.getpass("新密码（不会回显）: ")
    if password != getpass.getpass("再次输入新密码: "):
        raise ValueError("两次密码不一致")
    return password


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="管理互刷系统独立账号")
    parser.add_argument("--db-path", default=_default_db_path())
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建账号")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", choices=("creator", "admin", "member"), default="member")

    for command in ("reset-password", "enable", "disable"):
        item = subparsers.add_parser(command)
        item.add_argument("--username", required=True)
    transfer = subparsers.add_parser("transfer-creator", help="原子转移唯一创建者")
    transfer.add_argument("--from-username", required=True)
    transfer.add_argument("--to-username", required=True)
    transfer.add_argument("--yes", action="store_true", help="确认执行角色转移")
    initialize = subparsers.add_parser("initialize-creator", help="无创建者时初始化唯一创建者")
    initialize.add_argument("--username", required=True)
    initialize.add_argument("--yes", action="store_true", help="确认执行创建者初始化")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_farm_system_schema(Path(args.db_path))
    db = Database(args.db_path)
    try:
        repository = FarmAccountRepository(db.conn)
        service = FarmAuthService(repository)
        if args.command == "create":
            account = service.create_account(
                username=args.username,
                display_name=args.display_name,
                password=_password(),
                role=args.role,
            )
        elif args.command == "transfer-creator":
            if not args.yes:
                raise ValueError("转移创建者必须显式指定 --yes")
            source = repository.get_by_username(args.from_username)
            target = repository.get_by_username(args.to_username)
            if source is None or target is None:
                raise LookupError("创建者转移账号不存在")
            _, account = repository.transfer_creator(source["id"], target["id"])
        elif args.command == "initialize-creator":
            if not args.yes:
                raise ValueError("初始化创建者必须显式指定 --yes")
            target = repository.get_by_username(args.username)
            if target is None:
                raise LookupError("创建者账号不存在")
            account = repository.initialize_creator(target["id"])
        else:
            account = repository.get_by_username(args.username)
            if account is None:
                raise LookupError("互刷账号不存在")
            if args.command == "reset-password":
                account = service.reset_password(account["id"], _password())
            else:
                status = "active" if args.command == "enable" else "disabled"
                account = service.set_status(account["id"], status)
        print(
            f"操作完成 id={account['id']} username={account['username']} "
            f"role={account['role']} status={account['status']}"
        )
        return 0
    except (LookupError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
