"""互刷部落清退辅助数据。

填坑号是人工维护的长期身份；当前部落归属和活跃事实仍以 ``accounts`` 为准。
本模块只操作本地 SQLite，不在 API 请求路径访问腾讯文档或 COC。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from modules.coc_sync.official.mapper import normalize_tag


REQUIRED_FILL_ACCOUNT_HEADERS = {
    "账号编号",
    "账号名字",
    "大本等级",
    "所在部落名字+标签",
    "玩家标签",
    "最后查询时间",
}


def canonical_tag(value: Any) -> str | None:
    """生成只用于关联的 Tag 键；兼容历史字体把数字 0 写成字母 O。"""
    normalized = normalize_tag(value)
    return normalized.replace("O", "0") if normalized else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _town_hall(value: Any) -> int | None:
    match = re.search(r"(\d+)", _text(value))
    return int(match.group(1)) if match else None


def _source_clan_tag(value: Any) -> str | None:
    match = re.search(r"#[A-Z0-9]+", _text(value).upper())
    return canonical_tag(match.group(0)) if match else None


def parse_fill_account_rows(
    rows: list[dict],
    *,
    source_doc_id: str,
    source_sheet_id: str,
    source_sheet_title: str,
    imported_at: str | None = None,
) -> list[dict]:
    """校验并规范化一次性腾讯文档导入行。"""
    if not rows:
        raise ValueError("填坑号 Sheet 没有数据行")
    missing = REQUIRED_FILL_ACCOUNT_HEADERS - set(rows[0])
    if missing:
        raise ValueError(f"填坑号 Sheet 缺少列：{sorted(missing)}")

    timestamp = imported_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict] = []
    account_numbers: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        account_number = _text(row.get("账号编号"))
        player_tag = canonical_tag(row.get("玩家标签"))
        if not account_number:
            raise ValueError(f"第 {row_number} 行缺少账号编号")
        if not player_tag:
            raise ValueError(f"第 {row_number} 行缺少玩家标签")
        if account_number in account_numbers:
            raise ValueError(f"账号编号重复：{account_number}")
        account_numbers.add(account_number)
        source_clan_text = _text(row.get("所在部落名字+标签")) or None
        records.append({
            "account_number": account_number,
            "player_tag": player_tag,
            "account_name_snapshot": _text(row.get("账号名字")) or None,
            "town_hall_level_snapshot": _town_hall(row.get("大本等级")),
            "source_clan_text": source_clan_text,
            "source_clan_tag": _source_clan_tag(source_clan_text),
            "source_checked_text": _text(row.get("最后查询时间")) or None,
            "status": "active",
            "source_doc_id": source_doc_id,
            "source_sheet_id": source_sheet_id,
            "source_sheet_title": source_sheet_title,
            "imported_at": timestamp,
            "updated_at": timestamp,
            "note": None,
        })
    return records


def upsert_fill_accounts(conn: sqlite3.Connection, records: Iterable[dict]) -> int:
    """幂等写入填坑号登记；不因账号当前离开联盟而删除长期身份。"""
    count = 0
    for record in records:
        conn.execute(
            """INSERT INTO farm_fill_accounts
               (account_number, player_tag, account_name_snapshot,
                town_hall_level_snapshot, source_clan_text, source_clan_tag,
                source_checked_text, status, source_doc_id, source_sheet_id,
                source_sheet_title, imported_at, updated_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_number) DO UPDATE SET
                   player_tag = excluded.player_tag,
                   account_name_snapshot = excluded.account_name_snapshot,
                   town_hall_level_snapshot = excluded.town_hall_level_snapshot,
                   source_clan_text = excluded.source_clan_text,
                   source_clan_tag = excluded.source_clan_tag,
                   source_checked_text = excluded.source_checked_text,
                   status = excluded.status,
                   source_doc_id = excluded.source_doc_id,
                   source_sheet_id = excluded.source_sheet_id,
                   source_sheet_title = excluded.source_sheet_title,
                   updated_at = excluded.updated_at,
                   note = COALESCE(farm_fill_accounts.note, excluded.note)""",
            (
                record["account_number"], record["player_tag"],
                record.get("account_name_snapshot"),
                record.get("town_hall_level_snapshot"),
                record.get("source_clan_text"), record.get("source_clan_tag"),
                record.get("source_checked_text"), record.get("status") or "active",
                record["source_doc_id"], record["source_sheet_id"],
                record.get("source_sheet_title"), record["imported_at"],
                record["updated_at"], record.get("note"),
            ),
        )
        count += 1
    return count


def _activity_reasons(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def farm_management_by_clan(
    conn: sqlite3.Connection,
    clan_tags: Iterable[str],
    *,
    inactive_limit: int = 5,
) -> dict[str, dict]:
    """返回每个互刷部落的填坑号及相对最不活跃成员。

    填坑号和首领不进入不活跃候选；无活动时间时使用开始观察时间。
    完全没有观察时间的成员排在有依据的成员之后，避免伪造不活跃结论。
    """
    configured = {
        key: normalize_tag(tag)
        for tag in clan_tags
        if (key := canonical_tag(tag))
    }
    result = {
        tag: {"fill_accounts": [], "inactive_members": []}
        for tag in configured.values()
    }
    if not configured:
        return result

    fill_rows = conn.execute(
        """SELECT account_number, player_tag, account_name_snapshot,
                  town_hall_level_snapshot, imported_at
           FROM farm_fill_accounts
           WHERE status = 'active'
           ORDER BY account_number"""
    ).fetchall()
    fill_by_player: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in fill_rows:
        key = canonical_tag(row["player_tag"])
        if key:
            fill_by_player[key].append(row)

    members_by_clan: dict[str, list[dict]] = defaultdict(list)
    account_rows = conn.execute(
        """SELECT player_tag, account_name, town_hall_level, clan_tag, clan_role,
                  last_activity_at, last_activity_reason, activity_observed_since,
                  last_synced_at
           FROM accounts
           WHERE COALESCE(membership_status, 'member') = 'member'"""
    ).fetchall()
    for row in account_rows:
        clan_key = canonical_tag(row["clan_tag"])
        configured_tag = configured.get(clan_key)
        if not configured_tag:
            continue
        item = dict(row)
        item["player_tag"] = normalize_tag(item.get("player_tag"))
        item["last_activity_reasons"] = _activity_reasons(
            item.pop("last_activity_reason", None)
        )
        item["activity_reference_at"] = (
            item.get("last_activity_at") or item.get("activity_observed_since")
        )
        item["never_observed_activity"] = not bool(item.get("last_activity_at"))
        members_by_clan[configured_tag].append(item)

    for clan_tag, members in members_by_clan.items():
        inactive_candidates: list[dict] = []
        for member in members:
            player_key = canonical_tag(member.get("player_tag"))
            fill_records = fill_by_player.get(player_key, [])
            if fill_records:
                result[clan_tag]["fill_accounts"].append({
                    **member,
                    "account_numbers": [row["account_number"] for row in fill_records],
                    "fill_account_count": len(fill_records),
                    "fill_imported_at": max(
                        (row["imported_at"] for row in fill_records if row["imported_at"]),
                        default=None,
                    ),
                })
                continue
            if member.get("clan_role") == "leader":
                continue
            inactive_candidates.append(member)

        result[clan_tag]["fill_accounts"].sort(
            key=lambda item: (item.get("account_name") or "", item.get("player_tag") or "")
        )
        inactive_candidates.sort(key=lambda item: (
            item.get("activity_reference_at") is None,
            item.get("activity_reference_at") or "",
            item.get("player_tag") or "",
        ))
        result[clan_tag]["inactive_members"] = inactive_candidates[:inactive_limit]

    return result
