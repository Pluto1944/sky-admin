"""拉取 CWL 数据并写入数据库。

流程（两级降级）：
  1. 查 league_teams 表获取 combat 队伍列表
  2. 逐队拉取 CWL 战绩（两级降级）：
     a. 通道1 🥇 ClashKing War Log — 主力数据源，支持按月份筛选
     b. 通道2 🥈 本地 JSON 文件 — 兜底
  3. 查不到 league_teams → 冷启动：读本地 JSON 导入

注意：Supercell 官方 API 的 get_league_group 只能查当前 CWL，不按月份过滤，
会误把当月数据写入历史月份，因此不纳入降级链路。

--period 语义：CWL 实际发生月（与联赛月相同）。
  - fetch --period 2026-08 → 拉取 2026-08 CWL 战绩

用法：
  python scripts/fetch_cwl_data.py --period 2026-08
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

from modules.coc_sync.clashking.client import fetch_cwl_players  # noqa: E402
from config import DB_PATH, LEAGUE_COMBAT  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"

ALERT_LINE = "\n" + "=" * 65 + "\n"
COLD_START_BANNER = (
    "\n"
    + "╔" + "═" * 63 + "╗\n"
    + "║  ⚠️  league_teams 中无 {period} 的 combat 记录                          ║\n"
    + "║  ⚠️  进入冷启动模式：尝试从本地 JSON 读取                               ║\n"
    + "╚" + "═" * 63 + "╝\n"
)

# 队伍信息结构: (team_index, team_alias, team_name, clan_tag)
TeamInfo = tuple[int, str, str, str]


# ═══════════════════════════════════════════════════════════════════════
# 队伍加载
# ═══════════════════════════════════════════════════════════════════════

def _load_teams_from_db(period: str) -> list[TeamInfo]:
    """从 league_teams 表加载 combat 队伍列表。

    返回 [(team_index, team_alias, team_name, clan_tag), ...]
    查不到返回空列表。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT team_index, team_alias, team_name, clan_tag "
            "FROM league_teams WHERE period = ? AND category = ? "
            "ORDER BY team_index",
            (period, LEAGUE_COMBAT),
        ).fetchall()
        conn.close()
        return [(r["team_index"], r["team_alias"], r["team_name"] or "", r["clan_tag"]) for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

def _normalize_tag(tag: str) -> str:
    return tag.strip().lstrip("#").upper()


# ═══════════════════════════════════════════════════════════════════════
# 通道 1：ClashKing API
# ═══════════════════════════════════════════════════════════════════════

def _fetch_via_clashking(team_alias: str, clan_tag: str, period: str) -> list[dict] | None:
    """通道1：通过 ClashKing War Log 拉取 CWL 历史战绩。

    每个玩家: {"tag", "name", "total_stars", "total_attacks"}
    返回 None 表示该通道不可用。
    """
    players = fetch_cwl_players(clan_tag, period)
    if not players:
        return None
    return players


# ═══════════════════════════════════════════════════════════════════════
# 通道 2：本地 JSON
# ═══════════════════════════════════════════════════════════════════════

def _fetch_via_local_json(team_alias: str, period: str) -> list[dict] | None:
    """通道2：从本地 data/cwl_YYYYMM/X_alias.json 读取队伍战绩。

    返回格式与 _fetch_via_clashking() 一致。
    返回 None 表示该通道不可用。
    """
    data_dir = DATA_ROOT / f"cwl_{period.replace('-', '')}"
    if not data_dir.exists():
        return None

    # 按 team_alias 匹配 JSON 文件（文件名格式: 1_冠一_一队.json）
    for f in sorted(data_dir.glob("*.json")):
        team_data = json.loads(f.read_text(encoding="utf-8"))
        if team_data.get("team_name", "") == team_alias:
            return [
                {"tag": p["tag"], "name": p["name"],
                 "total_stars": p["total_stars"], "total_attacks": p["total_attacks"]}
                for p in team_data.get("players", [])
            ]

    return None


# ═══════════════════════════════════════════════════════════════════════
# 统一入口：三级降级
# ═══════════════════════════════════════════════════════════════════════

def _fetch_team_players(team_alias: str, clan_tag: str, period: str) -> tuple[list[dict] | None, str]:
    """两级降级拉取一个队伍的 CWL 战绩。

    ClashKing → 本地 JSON，任一成功即返回。
    两个通道全部失败返回 (None, "") 并打印明显告警。

    注意：官方 API 的 get_league_group 只能查当前 CWL，不按月份过滤，
    会误把当月数据写入历史月份，因此不纳入降级链路。

    Returns:
        (players, source): players 为玩家列表，source 为数据来源标识
    """
    # ── 通道 1：ClashKing API ──
    players = _fetch_via_clashking(team_alias, clan_tag, period)
    if players:
        print(f"  {team_alias}: ✅ [ClashKing] ({len(players)}人)")
        return players, "ClashKing"
    print(f"  {team_alias}: ⚠️ [ClashKing] 失败 → 降级本地 JSON")

    # ── 通道 2：本地 JSON 文件 ──
    players = _fetch_via_local_json(team_alias, period)
    if players:
        print(f"  {team_alias}: ✅ [本地JSON] ({len(players)}人)")
        return players, "本地JSON"

    # ── 全部失败 ──
    print(ALERT_LINE)
    print(f"  🚨 [全部失败] {team_alias}({clan_tag}) 无任何数据源可用！")
    print(f"      请检查: 1) ClashKing 是否可访问")
    print(f"              2) data/cwl_{period.replace('-', '')}/ 目录是否存在 JSON 文件")
    print(ALERT_LINE)
    return None, ""


def _fetch_and_write(period: str, teams: list[TeamInfo]) -> tuple[list[str], int, int, dict[str, str]]:
    """逐队拉取 CWL 战绩并直接写入数据库（两级降级）。

    返回 (ok_team_aliases, n_ok, n_skip, source_map)。
    source_map 记录每队的数据来源 {team_alias: source}，用于汇总报告。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute("SELECT player_tag, account_name FROM accounts")
    known_tags = {r[0]: r[1] for r in cur.fetchall()}

    ok_teams: list[str] = []
    n_ok = n_skip = 0
    source_map: dict[str, str] = {}  # team_alias → 数据来源

    for team_index, team_alias, team_name, clan_tag in teams:
        players, source = _fetch_team_players(team_alias, clan_tag, period)
        if players is None:
            continue
        source_map[team_alias] = source
        ok_teams.append(team_alias)

        for p in players:
            tag = p["tag"]
            if tag not in known_tags:
                n_skip += 1
                continue

            account_name = known_tags[tag]
            raw_metrics = {
                "total_stars": p["total_stars"],
                "team_name": team_alias,
                "clan_tag": clan_tag,
                "team_index": team_index,
            }

            # 写入 league_results 新表
            conn.execute(
                """INSERT INTO league_results
                   (period, team_index, team_alias, team_name, clan_tag, category,
                    player_tag, account_name, total_stars, attacks, raw_metrics)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(period, team_index, player_tag) DO UPDATE SET
                   team_alias = excluded.team_alias,
                   team_name = excluded.team_name,
                   clan_tag = excluded.clan_tag,
                   account_name = excluded.account_name,
                   total_stars = excluded.total_stars,
                   attacks = excluded.attacks,
                   raw_metrics = excluded.raw_metrics""",
                (
                    period, team_index, team_alias, team_name, clan_tag,
                    LEAGUE_COMBAT, tag, account_name,
                    p["total_stars"], p["total_attacks"],
                    json.dumps(raw_metrics, ensure_ascii=False),
                ),
            )

            # 双写旧 results 表（过渡期兼容）
            conn.execute(
                """INSERT INTO results (player_tag, period, league_type, raw_metrics)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(player_tag, period, league_type) DO UPDATE SET
                   raw_metrics = excluded.raw_metrics""",
                (tag, period, LEAGUE_COMBAT, json.dumps(raw_metrics)),
            )

            n_ok += 1

    conn.commit()
    conn.close()

    failed = [alias for _, alias, _, _ in teams if alias not in ok_teams]
    print(f"\n[fetch] 成功: {len(ok_teams)}/{len(teams)} 队" +
          (f"，失败: {failed}" if failed else ""))

    if n_ok:
        print(f"[write] {n_ok} 条战绩 → league_results + results（period={period}）" +
              (f"，跳过 {n_skip} 条（不在 accounts）" if n_skip else ""))

    return ok_teams, n_ok, n_skip, source_map


# ═══════════════════════════════════════════════════════════════════════
# 冷启动：从本地 JSON 导入
# ═══════════════════════════════════════════════════════════════════════

def _cold_start_from_json(period: str) -> tuple[list[str], int, int]:
    """冷启动：从 data/cwl_YYYYMM/*.json 导入 league_results + results 表。

    返回 (ok_team_aliases, n_ok, n_skip)。
    """
    data_dir = DATA_ROOT / f"cwl_{period.replace('-', '')}"
    if not data_dir.exists():
        print(ALERT_LINE)
        print(f"🚨 冷启动失败：{data_dir} 目录不存在，无 JSON 可导入")
        print("🚨 请确认数据文件路径或先手动准备 JSON 数据")
        print(ALERT_LINE)
        return [], 0, 0

    json_files = sorted(data_dir.glob("*.json"))
    if not json_files:
        print(ALERT_LINE)
        print(f"🚨 冷启动失败：{data_dir} 目录为空")
        print(ALERT_LINE)
        return [], 0, 0

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute("SELECT player_tag, account_name FROM accounts")
    known_tags = {r[0]: r[1] for r in cur.fetchall()}

    ok_teams: list[str] = []
    n_ok = n_skip = 0

    for f in json_files:
        team_data = json.loads(f.read_text(encoding="utf-8"))
        team_index = team_data.get("team_index")
        team_alias = team_data.get("team_name", "")
        clan_tag = team_data.get("clan_tag", "")

        # 从 league_clans 匹配 COC 真实部落名称
        coc_team_name = ""
        for lc in team_data.get("league_clans", []):
            if _normalize_tag(lc.get("tag", "")) == _normalize_tag(clan_tag):
                coc_team_name = lc.get("name", "")
                break

        ok_teams.append(team_alias)

        for p in team_data.get("players", []):
            tag = p["tag"]
            if tag not in known_tags:
                n_skip += 1
                continue

            account_name = known_tags[tag]
            raw_metrics = {
                "total_stars": p["total_stars"],
                "team_name": team_alias,
                "clan_tag": clan_tag,
                "team_index": team_index,
            }

            conn.execute(
                """INSERT INTO league_results
                   (period, team_index, team_alias, team_name, clan_tag, category,
                    player_tag, account_name, total_stars, attacks, raw_metrics)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(period, team_index, player_tag) DO UPDATE SET
                   team_alias = excluded.team_alias,
                   team_name = excluded.team_name,
                   clan_tag = excluded.clan_tag,
                   account_name = excluded.account_name,
                   total_stars = excluded.total_stars,
                   attacks = excluded.attacks,
                   raw_metrics = excluded.raw_metrics""",
                (
                    period, team_index, team_alias, coc_team_name, clan_tag,
                    LEAGUE_COMBAT, tag, account_name,
                    p["total_stars"], p["total_attacks"],
                    json.dumps(raw_metrics, ensure_ascii=False),
                ),
            )

            conn.execute(
                """INSERT INTO results (player_tag, period, league_type, raw_metrics)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(player_tag, period, league_type) DO UPDATE SET
                   raw_metrics = excluded.raw_metrics""",
                (tag, period, LEAGUE_COMBAT, json.dumps(raw_metrics)),
            )

            n_ok += 1

    conn.commit()
    conn.close()

    if n_ok:
        print(f"[cold-start] {n_ok} 条战绩 → league_results + results（period={period}）" +
              (f"，跳过 {n_skip} 条（不在 accounts）" if n_skip else ""))
    return ok_teams, n_ok, n_skip


# ═══════════════════════════════════════════════════════════════════════
# 升降级总结
# ═══════════════════════════════════════════════════════════════════════

def _print_promotion_summary(period: str, team_order: list[str], ok_teams: set[str]) -> None:
    """输出相邻队伍的升降级参与情况。"""
    print(f"\n── 升降级参与情况（{period} CWL）──")
    for i in range(len(team_order) - 1):
        hi, lo = team_order[i], team_order[i + 1]
        hi_ok = hi in ok_teams
        lo_ok = lo in ok_teams
        if hi_ok and lo_ok:
            print(f"  ✅ {hi} ↔ {lo}")
        else:
            missing = [t for t, ok in [(hi, hi_ok), (lo, lo_ok)] if not ok]
            print(f"  ⛔ {hi} ↔ {lo}  跳过（缺: {', '.join(missing)}）")


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="拉取 CWL 数据并写入 league_results/results 表")
    parser.add_argument("--period", required=True, help="CWL 月份（实际发生月），如 2026-08")
    args = parser.parse_args()

    period = args.period
    print(f"CWL 发生月: {period}")

    # ── 1. 加载队伍列表 ──
    teams = _load_teams_from_db(period)

    if teams:
        # ── 正常流程：查 league_teams → 三级降级拉取 → 写 DB ──
        print(f"拉取队伍: {[alias for _, alias, _, _ in teams]}")
        ok_teams, n_ok, n_skip, source_map = _fetch_and_write(period, teams)

        # ── 汇总报告：数据来源 ──
        print(f"\n── 数据来源汇总（{period} CWL）──")
        for _, alias, _, _ in teams:
            src = source_map.get(alias, "🚨 失败")
            icon = "✅" if alias in ok_teams else "🚨"
            print(f"  {icon} {alias}: [{src}]")

        if not ok_teams:
            print(ALERT_LINE)
            print(f"🚨 全部队伍拉取失败")
            print("🚨 编排时自动跳过升降级")
            print(ALERT_LINE)
            return 1

        if n_ok == 0:
            print(ALERT_LINE + f"⚠️ 0 条战绩写入（{n_skip} 条不在 accounts）" + ALERT_LINE)
            return 1

        _print_promotion_summary(period, [alias for _, alias, _, _ in teams], set(ok_teams))
        print(f"\n✅ 数据就绪：{n_ok} 条星数已写入 league_results + results 表（period={period}）")
        return 0

    else:
        # ── 冷启动：查不到 league_teams → 读本地 JSON ──
        print(COLD_START_BANNER.format(period=period))
        ok_teams, n_ok, n_skip = _cold_start_from_json(period)

        if n_ok == 0:
            return 1

        print(f"\n✅ 冷启动完成：{n_ok} 条星数已写入 league_results + results 表（period={period}）")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
