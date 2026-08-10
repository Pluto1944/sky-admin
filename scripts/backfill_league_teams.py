#!/usr/bin/env python3
"""从历史报名结果文档回填 league_teams 表。

腾讯文档「苍穹联赛报名结果」包含从 2023.12 到 2026.08 的所有月份报名数据。
每个月的子表格式为：
- 第一列"苍穹联赛报名"：队伍级别名（如"冠一"、"冠二"、"定级"等）
- col1：clan_tag（#开头）或玩家名
- 队伍行特征：第一列是级别名，col1 是 # 开头的 clan_tag

本脚本：
1. 从腾讯文档读取所有历史月份的队伍信息
2. 将每个队伍映射为 league_teams 记录
3. 幂等写入（INSERT OR REPLACE），可安全重复运行
"""

import os
import re
import sqlite3
import sys

# 确保项目路径在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from shared.io_adapter.tencent_doc import TencentDocAdapter

# ── 配置 ──────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "league.db")
PUBLISH_DOC_FILE_ID = os.environ.get("PUBLISH_DOC_FILE_ID", "DUmJScGxhRFdzdUdU")

# 月份名 → CWL period 映射
# 报名表中的月份名是"联赛时间"（如"26.3月联赛"表示2026年3月打的CWL）
# league_teams.period 也是联赛时间
MONTH_PATTERN = re.compile(r"(\d{2})\.(\d{1,2})月联赛")

# 哪些子表名需要排除
SKIP_SHEETS = {"模板", "公式备份"}
SKIP_KEYWORDS = ["备份", "副本"]


def parse_period_from_sheet(sheet_title: str) -> str | None:
    """从子表标题解析 period（如 '26.3月联赛 报名结果' → '2026-03'）。"""
    m = MONTH_PATTERN.search(sheet_title)
    if not m:
        return None
    year_short = int(m.group(1))
    month = int(m.group(2))
    year = 2000 + year_short
    return f"{year}-{month:02d}"


def _safe_str(value) -> str:
    """安全转字符串并去空白。"""
    if value is None:
        return ""
    return str(value).strip()


def extract_teams_from_sheet(rows: list[dict]) -> list[dict]:
    """从报名结果表中提取队伍信息。

    队伍行特征：第一列是级别名（非空），col1 是 # 开头的 clan_tag。
    报名表按强度从上往下排列：实战队伍在前，壳子在后。
    一旦遇到"壳子"关键字，后续所有队伍都归为 shell。
    返回 list[dict]，每个 dict 包含 level_name, clan_tag, category。
    """
    teams = []
    in_shell_zone = False
    for row in rows:
        level_name = _safe_str(row.get("苍穹联赛报名"))
        col1 = _safe_str(row.get("col1"))

        if not level_name or not col1:
            continue
        if not col1.startswith("#"):
            continue

        # 排除太短的 tag
        if len(col1) < 3:
            continue

        # 清理 clan_tag：去空格、统一大写
        tag = col1.replace(" ", "").upper()
        if not tag.startswith("#"):
            continue

        # 判断分类：遇到"壳子"后进入 shell 区域
        if "壳子" in level_name or "扫尾" in level_name:
            in_shell_zone = True

        teams.append({
            "level_name": level_name,
            "clan_tag": tag,
            "category": "shell" if in_shell_zone else "combat",
        })

    return teams


def _clean_level(name: str) -> str:
    """清理级别名：去掉"实战:"、"壳子:"前缀和人数后缀。"""
    name = name.strip()
    # 去掉前缀
    for prefix in ["实战:", "实战：", "壳子:", "壳子："]:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    # 去掉人数后缀，如 "15/15"、"30/30"、"18/30"
    name = re.sub(r"\s*\d+/\d+\s*$", "", name).strip()
    return name


def normalize_team_alias(level_name: str) -> str:
    """将报名表中的级别名清理为标准 team_alias。

    直接清理前缀后缀，保留原始级别语义。
    不强制映射为固定别名，因为同一 clan_tag 在不同月份可能处于不同级别。
    """
    return _clean_level(level_name)


def categorize_team(level_name: str) -> str:
    """判断队伍类别：combat 或 shell。"""
    name = level_name.strip()
    # 用原始名判断，在清理之前
    if re.search(r"壳子|扫尾", name):
        return "shell"
    return "combat"


def guess_member_count(level_name: str) -> int:
    """从级别名中推测成员数。"""
    name = level_name.strip()
    # 先尝试匹配人数后缀如 "30/30"
    m = re.search(r"(\d+)/\d+", name)
    if m:
        return int(m.group(1))
    # 再尝试匹配 "30人"
    m = re.search(r"(\d+)\s*人", name)
    if m:
        return int(m.group(1))
    # 默认值
    if categorize_team(name) == "shell":
        return 30
    return 15


def backfill_period(
    adapter: TencentDocAdapter,
    file_id: str,
    sheet_title: str,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> int:
    """回填一个月的 league_teams 数据，返回写入条数。"""
    period = parse_period_from_sheet(sheet_title)
    if not period:
        print(f"  [skip] 无法解析 period: {sheet_title}")
        return 0

    rows = adapter.read_sheet(file_id, sheet_title)
    teams = extract_teams_from_sheet(rows)

    if not teams:
        print(f"  [skip] {sheet_title} → {period}: 未找到队伍行")
        return 0

    # 报名表已按强度从上往下排列（实战在前，壳子在后），保持原始顺序即可

    count = 0
    for idx, team in enumerate(teams):
        alias = normalize_team_alias(team["level_name"])
        category = team["category"]
        member_count = guess_member_count(team["level_name"])

        if dry_run:
            print(
                f"  [dry] period={period} idx={idx} alias={alias} "
                f"tag={team['clan_tag']} cat={category} count={member_count} "
                f"(原始: {team['level_name']})"
            )
        else:
            conn.execute(
                """INSERT OR REPLACE INTO league_teams
                   (period, team_index, team_alias, team_name, clan_tag, category,
                    member_count, leader, league_level, reserved_slots)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    period,
                    idx,
                    alias,
                    "",  # team_name 留空，后续可通过 COC API 补全
                    team["clan_tag"],
                    category,
                    member_count,
                    "",  # leader 留空
                    "",  # league_level 留空
                    0,   # reserved_slots
                ),
            )
        count += 1

    if not dry_run:
        conn.commit()

    print(f"  [ok] {sheet_title} → {period}: {count} 条队伍记录")
    return count


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="从腾讯文档历史报名结果回填 league_teams 表"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印不写入"
    )
    parser.add_argument(
        "--period", type=str, default=None,
        help="只回填指定月份（如 2026-03），默认回填所有月份"
    )
    parser.add_argument(
        "--start-period", type=str, default=None,
        help="回填起始月份（含），如 2026-01"
    )
    args = parser.parse_args()

    adapter = TencentDocAdapter()
    file_id = PUBLISH_DOC_FILE_ID

    # 获取所有子表
    props = adapter._list_sheets(file_id)
    print(f"文档包含 {len(props)} 个子表")

    # 筛选需要处理的子表
    # 同一月份可能有多份（正式版、月中版、备份版），优先取正式版
    period_candidates: dict[str, list[tuple[str, str]]] = {}
    for p in props:
        title = p.get("title", "")
        if title in SKIP_SHEETS:
            continue
        if any(kw in title for kw in SKIP_KEYWORDS):
            continue

        period = parse_period_from_sheet(title)
        if not period:
            continue

        if args.period and period != args.period:
            continue
        if args.start_period and period < args.start_period:
            continue

        if period not in period_candidates:
            period_candidates[period] = []
        period_candidates[period].append((title, period))

    # 同一月份优先取正式版（不含"月中"、"backup"等关键字）
    sheets_to_process = []
    for period, candidates in sorted(period_candidates.items()):
        # 优先选正式版（没有额外后缀的）
        preferred = None
        for title, p in candidates:
            if "月中" not in title and "backup" not in title.lower():
                preferred = (title, p)
                break
        if not preferred:
            preferred = candidates[0]  # 兜底取第一个
        sheets_to_process.append(preferred)

    if not sheets_to_process:
        print("没有找到需要处理的月份")
        return

    print(f"将处理 {len(sheets_to_process)} 个月份：")
    for title, period in sheets_to_process:
        print(f"  {title} → {period}")
    print()

    conn = sqlite3.connect(DB_PATH)
    total = 0

    try:
        for title, period in sheets_to_process:
            n = backfill_period(adapter, file_id, title, conn, dry_run=args.dry_run)
            total += n
    finally:
        conn.close()

    action = "将写入" if args.dry_run else "已写入"
    print(f"\n总计 {action} {total} 条记录到 league_teams 表")


if __name__ == "__main__":
    main()
