#!/usr/bin/env python3
"""一次性把腾讯文档填坑号登记导入本地 SQLite。

默认只校验和预览；显式传入 ``--apply`` 才写库。该脚本不由调度器调用，
运行时页面和 API 也不会访问腾讯文档。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402

load_env()

import config  # noqa: E402
from modules.player.farm_management import (  # noqa: E402
    canonical_tag,
    parse_fill_account_rows,
    upsert_fill_accounts,
)
from shared.db.connection import Database  # noqa: E402
from shared.io_adapter.tencent_doc import TencentDocAdapter  # noqa: E402


def run(
    doc_id: str,
    sheet_id: str,
    *,
    expected_rows: int | None = None,
    expected_unique_tags: int | None = None,
    apply: bool = False,
) -> int:
    adapter = TencentDocAdapter()
    sheets = adapter._list_sheets(doc_id)
    selected = next((item for item in sheets if item.get("sheetId") == sheet_id), None)
    if not selected:
        print(f"未找到指定 Sheet ID：{sheet_id}", file=sys.stderr)
        return 1
    title = selected.get("title")
    rows = adapter.read_sheet(doc_id, sheet=title)
    try:
        records = parse_fill_account_rows(
            rows,
            source_doc_id=doc_id,
            source_sheet_id=sheet_id,
            source_sheet_title=title or "",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    unique_tags = {canonical_tag(record["player_tag"]) for record in records}
    if expected_rows is not None and len(records) != expected_rows:
        print(
            f"行数不符：期望 {expected_rows}，实际 {len(records)}；拒绝继续",
            file=sys.stderr,
        )
        return 1
    if expected_unique_tags is not None and len(unique_tags) != expected_unique_tags:
        print(
            f"唯一玩家数不符：期望 {expected_unique_tags}，实际 {len(unique_tags)}；拒绝继续",
            file=sys.stderr,
        )
        return 1

    print(
        f"Sheet={title}({sheet_id})，登记 {len(records)} 行，"
        f"唯一玩家 {len(unique_tags)} 个"
    )
    if not apply:
        print("DRY-RUN 通过；未写入数据库")
        return 0

    db = Database(config.DB_PATH)
    db.init_schema()
    try:
        db.conn.execute("BEGIN IMMEDIATE")
        written = upsert_fill_accounts(db.conn, records)
        db.conn.commit()
        stored = db.conn.execute(
            "SELECT COUNT(*) FROM farm_fill_accounts WHERE status = 'active'"
        ).fetchone()[0]
    except Exception:
        db.conn.rollback()
        raise
    finally:
        db.close()
    print(f"已写入 {written} 行；当前有效登记 {stored} 行")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="一次性导入互刷填坑号登记")
    parser.add_argument("--doc-id", required=True, help="腾讯文档 fileId")
    parser.add_argument("--sheet-id", required=True, help="目标 Sheet ID")
    parser.add_argument("--expected-rows", type=int, help="预期数据行数，防止读错 Sheet")
    parser.add_argument(
        "--expected-unique-tags", type=int, help="预期唯一玩家 Tag 数，防止来源异常"
    )
    parser.add_argument("--apply", action="store_true", help="验证通过后写入数据库")
    args = parser.parse_args()
    return run(
        args.doc_id,
        args.sheet_id,
        expected_rows=args.expected_rows,
        expected_unique_tags=args.expected_unique_tags,
        apply=args.apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
