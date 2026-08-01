"""拉取 CWL 数据并写入数据库。

流程：
  1. 查 league_teams 表获取 combat 队伍 → 调 COC API 拉取战绩 → 直接写 DB（正常流程）
  2. 查不到 league_teams → 尝试读本地 JSON 导入（冷启动回退）

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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

from modules.coc_sync.api_client import CocApiClient, CocApiError  # noqa: E402
from shared.config.common import DB_PATH, LEAGUE_COMBAT  # noqa: E402

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
# COC API 拉取
# ═══════════════════════════════════════════════════════════════════════

def _normalize_tag(tag: str) -> str:
    return tag.strip().lstrip("#").upper()


def _fetch_one_war(client: CocApiClient, wt: str, normalized_tag: str) -> dict | None:
    """拉取单场 war 详情，返回我方成员数据（失败返回 None）。"""
    try:
        d = client.get_cwl_war(wt)
    except Exception:
        return None

    clan_side = d.get("clan", {})
    opp_side = d.get("opponent", {})

    if _normalize_tag(clan_side.get("tag", "")) == normalized_tag:
        my_side = clan_side
    elif _normalize_tag(opp_side.get("tag", "")) == normalized_tag:
        my_side = opp_side
    else:
        return None

    return {"members": my_side.get("members", [])}


def _fetch_team_players(client: CocApiClient, team_alias: str, clan_tag: str) -> list[dict] | None:
    """拉取一个队伍的 CWL 战绩，返回玩家列表（失败返回 None）。

    每个玩家: {"tag", "name", "total_stars", "total_attacks"}
    """
    normalized = _normalize_tag(clan_tag)

    try:
        lg = client.get_league_group(clan_tag)
    except CocApiError as e:
        print(f"  {team_alias}({clan_tag}): ❌ {e}")
        return None

    if lg is None:
        print(f"  {team_alias}({clan_tag}): ⚠️ 无联赛组数据（非CWL周，API返回404）")
        return None

    my_war_tags: list[str] = []
    for rd in lg.get("rounds", []):
        my_war_tags.extend(rd.get("warTags", []))

    print(f"  {team_alias}: {len(lg.get('clans', []))}部 {len(lg.get('rounds', []))}轮 {len(my_war_tags)}wars", end="", flush=True)

    player_stats: dict[str, dict] = defaultdict(
        lambda: {"tag": "", "name": "", "total_stars": 0, "total_attacks": 0},
    )
    n_wars = 0

    max_workers = min(8, len(my_war_tags)) if my_war_tags else 0
    if max_workers > 0:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_fetch_one_war, client, wt, normalized): wt
                for wt in my_war_tags
            }
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue
                n_wars += 1
                for m in result.get("members", []):
                    ptag = m["tag"]
                    stars = sum(a.get("stars", 0) for a in m.get("attacks", []))
                    rec = player_stats[ptag]
                    rec["tag"] = ptag
                    rec["name"] = m["name"]
                    rec["total_stars"] += stars
                    rec["total_attacks"] += len(m.get("attacks", []))

    print(f" → {n_wars}场已解析")

    return [
        {"tag": rec["tag"], "name": rec["name"],
         "total_stars": rec["total_stars"], "total_attacks": rec["total_attacks"]}
        for rec in player_stats.values()
    ]


def _fetch_and_write(period: str, teams: list[TeamInfo]) -> tuple[list[str], int, int]:
    """逐队拉取 CWL 战绩并直接写入数据库。

    返回 (ok_team_aliases, n_ok, n_skip)。
    """
    if not os.environ.get("COC_API_TOKEN"):
        print(ALERT_LINE + "❌ 未设置 COC_API_TOKEN" + ALERT_LINE)
        return [], 0, 0

    client = CocApiClient()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute("SELECT player_tag, account_name FROM accounts")
    known_tags = {r[0]: r[1] for r in cur.fetchall()}

    ok_teams: list[str] = []
    n_ok = n_skip = 0

    for team_index, team_alias, team_name, clan_tag in teams:
        players = _fetch_team_players(client, team_alias, clan_tag)
        if players is None:
            print(f"  {team_alias}: ❌ 拉取失败")
            continue

        print(f"  {team_alias}: ✅ ({len(players)}人)")
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

    return ok_teams, n_ok, n_skip


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
        # ── 正常流程：查 league_teams → 调 API → 写 DB ──
        print(f"拉取队伍: {[alias for _, alias, _, _ in teams]}")
        ok_teams, n_ok, n_skip = _fetch_and_write(period, teams)

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
