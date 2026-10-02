"""CWL 集结检查的纯数据转换。

本模块不做网络或数据库 I/O：正式公示表解析、昵称规范化与成员比较都保持为
确定性纯函数，调度器负责腾讯文档、COC API 和 SQLite 编排。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from typing import Any

from modules.coc_sync.official.mapper import normalize_tag

_SHELL_SCORE_SUFFIX = re.compile(r"\s+-?\d+(?:\.\d+)?\s*$")


def published_sheet_name(period: str) -> str:
    """把 ``YYYY-MM`` 转为正式公示子表名。"""
    year, month = period.split("-", 1)
    return f"{int(year) % 100:02d}.{int(month)}月联赛 报名结果"


def normalize_roster_name(value: Any, category: str) -> str:
    """做最小化昵称清理；壳子名单额外去掉发布时附加的末尾匹配值。"""
    name = "" if value is None else str(value).strip()
    if category == "shell":
        name = _SHELL_SCORE_SUFFIX.sub("", name).strip()
    return name


def parse_published_roster(rows: list[dict], teams: list[dict]) -> dict:
    """按当月 ``league_teams`` 从 Part4 五列表格中解析正式名单。

    每个队伍抬头的 ``col1`` 是 clan tag，随后 ``ceil(member_count / 5)``
    行是五列成员网格。人数不足时允许空单元格，但当月每个队伍抬头必须且只能出现
    一次，避免把残缺或错误月份的表格锁成正式快照。
    """
    if not rows:
        raise ValueError("正式名单子表为空")
    columns = list(rows[0].keys())[:5]
    if len(columns) < 2 or "col1" not in columns:
        raise ValueError("正式名单不是预期的 Part4 五列表格")

    headings: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        tag = normalize_tag(row.get("col1"))
        if tag and str(row.get("col1") or "").strip().startswith("#"):
            headings[tag].append(index)

    parsed_teams = []
    for team in teams:
        tag = normalize_tag(team.get("clan_tag"))
        if not tag:
            raise ValueError(f"队伍 {team.get('team_alias') or team.get('team_index')} 缺少部落标签")
        positions = headings.get(tag, [])
        if len(positions) != 1:
            raise ValueError(f"正式名单中部落 {tag} 抬头出现 {len(positions)} 次")

        start = positions[0] + 1
        capacity = max(0, int(team.get("member_count") or 0))
        member_rows = max(1, math.ceil(capacity / 5))
        names = []
        for row in rows[start:start + member_rows]:
            for column in columns:
                name = normalize_roster_name(row.get(column), team.get("category") or "combat")
                if name:
                    names.append(name)
        if not names:
            raise ValueError(f"正式名单中部落 {tag} 没有成员")

        parsed_teams.append({
            "team_index": team.get("team_index"),
            "team_alias": team.get("team_alias"),
            "team_name": team.get("team_name") or team.get("team_alias") or tag,
            "clan_tag": tag,
            "category": team.get("category") or "combat",
            "member_count": capacity,
            "members": names,
        })

    return {"teams": parsed_teams}


def roster_content_hash(roster: dict) -> str:
    payload = json.dumps(roster, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_roster_members(roster_names: list[str], current_members: list[dict]) -> dict:
    """按精确昵称和出现次数比较正式名单与当前成员。"""
    by_name: dict[str, deque] = defaultdict(deque)
    for member in current_members:
        name = str(member.get("account_name") or member.get("name") or "").strip()
        if name:
            by_name[name].append(member)

    present = []
    missing = []
    consumed = Counter()
    for position, roster_name in enumerate(roster_names, start=1):
        name = str(roster_name or "").strip()
        if by_name[name]:
            member = by_name[name].popleft()
            consumed[name] += 1
            present.append(_member_view(member, "present", position, name))
        else:
            missing.append({
                "name": name,
                "status": "missing",
                "roster_position": position,
                "player_tag": None,
                "role": None,
                "town_hall_level": None,
            })

    extras = []
    seen_occurrences = Counter()
    for member in current_members:
        name = str(member.get("account_name") or member.get("name") or "").strip()
        if not name:
            continue
        seen_occurrences[name] += 1
        if seen_occurrences[name] > consumed[name]:
            extras.append(_member_view(member, "extra", None, name))

    return {
        "official_count": len(roster_names),
        "current_count": len([m for m in current_members if (m.get("account_name") or m.get("name"))]),
        "present_count": len(present),
        "missing_count": len(missing),
        "extra_count": len(extras),
        "missing_members": missing,
        "extra_members": extras,
        "present_members": present,
    }


def _member_view(
    member: dict,
    status: str,
    roster_position: int | None,
    name: str,
) -> dict:
    return {
        "name": name,
        "status": status,
        "roster_position": roster_position,
        "player_tag": normalize_tag(member.get("player_tag") or member.get("tag")),
        "role": member.get("clan_role") or member.get("role"),
        "town_hall_level": member.get("town_hall_level") or member.get("townHallLevel"),
    }
