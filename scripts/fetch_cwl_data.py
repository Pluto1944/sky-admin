"""拉取 CWL 数据 + 导入 results 表（含回退逻辑）。

--period 语义：CWL 实际发生月（拉哪个月的 CWL 就传哪个月）。
  - 编排 8 月联赛 → 需要 7 月 CWL 数据 → --period 2026-07

回退顺序：
  1. COC API 拉取 CWL 战绩 → JSON → 导入 results 表
  2. API 失败 → 检查本地 JSON 是否存在 → 导入 results 表
  3. 两者都失败 → 打印显眼告警，返回非零退出码

用法：
  python scripts/fetch_cwl_data.py --period 2026-07              # 拉取 + 导入 DB
  python scripts/fetch_cwl_data.py --period 2026-07 --fetch-only  # 仅拉取 JSON
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 自动加载项目根 .env，确保读取最新配置（环境变量已有值时不覆盖）
from shared.config.env_loader import load_env  # noqa: E402
load_env()

from modules.coc_sync.api_client import CocApiClient, CocApiError  # noqa: E402
from modules.cwl_registration.config import TEAMS  # noqa: E402
from shared.config.common import DB_PATH, LEAGUE_COMBAT  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"


def _load_teams_to_fetch(cwl_period: str) -> list[tuple[int, str, str]]:
    """加载需要拉取 CWL 数据的实战队伍列表。

    优先级：league_teams 表（上月配置快照） > TEAMS（当前配置回退）。
    team_index = combat 队伍在配置列表中的顺序索引，是队伍的唯一身份标识。
    返回 [(team_index, team_alias, clan_tag), ...]
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM league_teams WHERE period = ? AND category = ? ORDER BY team_index",
            (cwl_period, LEAGUE_COMBAT),
        ).fetchall()
        conn.close()
        if rows:
            return [(r["team_index"], r["team_alias"], r["clan_tag"]) for r in rows]
    except Exception:
        pass

    # 回退到当前 TEAMS 配置
    return [
        (i, t["name"], t["clan_tag"])
        for i, t in enumerate(t for t in TEAMS if t["category"] == LEAGUE_COMBAT)
    ]


TEAMS_TO_FETCH: list[tuple[int, str, str]] = []  # 延迟加载，在 main() 中按 period 加载

ALERT_LINE = "\n" + "=" * 65 + "\n"


# ═══════════════════════════════════════════════════════════════════════
# COC API 拉取（原 fetch_cwl_data.py）
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


def _fetch_team_cwl(client: CocApiClient, team_name: str, clan_tag: str) -> dict | None:
    """拉取一个队伍的 CWL 战绩（并发拉取 war 详情）。"""
    normalized = _normalize_tag(clan_tag)

    try:
        lg = client.get_league_group(clan_tag)
    except CocApiError as e:
        print(f"  {team_name}({clan_tag}): ❌ {e}")
        return None

    if lg is None:
        print(f"  {team_name}({clan_tag}): ⚠️ 无联赛组数据（非CWL周，API返回404）")
        return None

    my_war_tags: list[str] = []
    for rd in lg.get("rounds", []):
        my_war_tags.extend(rd.get("warTags", []))

    print(f"  {team_name}: {len(lg.get('clans',[]))}部 {len(lg.get('rounds',[]))}轮 {len(my_war_tags)}wars", end="", flush=True)

    player_stats: dict[str, dict] = defaultdict(
        lambda: {"tag": "", "name": "", "total_stars": 0, "total_attacks": 0},
    )
    n_wars = 0

    # 并发拉取所有 war 详情
    max_workers = min(8, len(my_war_tags))
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

    max_possible = 3 * n_wars
    players = []
    for ptag, rec in player_stats.items():
        players.append({
            "tag": rec["tag"], "name": rec["name"],
            "total_stars": rec["total_stars"],
            "total_attacks": rec["total_attacks"],
            "three_star_rate": round(rec["total_stars"] / max_possible, 4) if max_possible else 0,
            "avg_stars": round(rec["total_stars"] / n_wars, 2) if n_wars else 0,
        })
    players.sort(key=lambda p: p["total_stars"], reverse=True)

    return {
        "team_name": team_name, "clan_tag": clan_tag,
        "season": lg.get("season"), "state": lg.get("state"),
        "league_clans": [{"tag": c.get("tag"), "name": c.get("name"), "level": c.get("clanLevel")}
                         for c in lg.get("clans", [])],
        "n_wars": n_wars, "n_players": len(players),
        "fetched_at": datetime.now().isoformat(), "players": players,
    }


def _fetch_from_api(data_dir: Path) -> list[str]:
    """从 COC API 拉取 CWL 数据 → 保存 JSON。返回成功的队伍名列表。"""
    if not os.environ.get("COC_API_TOKEN"):
        print(ALERT_LINE + "❌ 未设置 COC_API_TOKEN" + ALERT_LINE)
        return []

    data_dir.mkdir(parents=True, exist_ok=True)
    client = CocApiClient()

    ok_teams = []
    for team_index, team_name, clan_tag in TEAMS_TO_FETCH:
        # 已有文件且 <2h，跳过重新拉取（文件名用 team_index 避免重名冲突）
        filepath = data_dir / f"{team_index}_{team_name.replace(' ', '_')}.json"
        if filepath.exists():
            age_h = (datetime.now().timestamp() - filepath.stat().st_mtime) / 3600
            if age_h < 2:
                print(f"  {team_name}: 跳过（{age_h:.1f}h 前已拉取）")
                ok_teams.append(team_name)
                continue

        data = _fetch_team_cwl(client, team_name, clan_tag)
        if data is None:
            print(f"  {team_name}: ❌ 拉取失败")
            # 如果有旧文件，仍可使用
            if filepath.exists():
                print(f"    ↳ 旧数据仍可用")
                ok_teams.append(team_name)
            continue

        data["team_index"] = team_index
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {team_name}: ✅ ({data['n_wars']}场 {data['n_players']}人)")
        ok_teams.append(team_name)

    failed = [t for _, t, _ in TEAMS_TO_FETCH if t not in ok_teams]
    print(f"\n[fetch] 成功: {len(ok_teams)}/{len(TEAMS_TO_FETCH)} 队" +
          (f"，失败: {failed}" if failed else ""))
    return ok_teams


# ═══════════════════════════════════════════════════════════════════════
# 导入 results 表
# ═══════════════════════════════════════════════════════════════════════

def _import_to_results(data_dir: Path, cwl_period: str, teams_to_fetch: list[tuple[int, str, str]]) -> tuple[int, int]:
    """将 JSON 导入 league_results 表（同时双写到旧 results 表）。

    返回 (ok, skip)。
    """
    if not data_dir.exists():
        return 0, 0

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute("SELECT player_tag, account_name FROM accounts")
    known_tags = {r[0]: r[1] for r in cur.fetchall()}

    # 构建 team_index → team 信息映射
    team_info_map: dict[int, dict] = {
        ti: {"team_alias": alias, "clan_tag": clan_tag}
        for ti, alias, clan_tag in teams_to_fetch
    }

    n_ok = n_skip = 0
    for f in sorted(data_dir.glob("*.json")):
        team_data = json.loads(f.read_text(encoding="utf-8"))
        team_index = team_data.get("team_index")
        team_alias = team_data.get("team_name", "")
        clan_tag = team_data.get("clan_tag", "")
        # COC 真实部落名称（从 API 返回数据中取 league_clans 信息）
        coc_team_name = ""
        league_clans = team_data.get("league_clans", [])
        if league_clans:
            for lc in league_clans:
                if lc.get("tag", "").replace("#", "").upper() == clan_tag.replace("#", "").upper():
                    coc_team_name = lc.get("name", "")
                    break

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
                    cwl_period, team_index, team_alias, coc_team_name, clan_tag,
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
                (tag, cwl_period, LEAGUE_COMBAT, json.dumps(raw_metrics)),
            )

            # 回填 league_teams 表的 team_name（COC 真实名称）
            if coc_team_name and team_index is not None:
                conn.execute(
                    "UPDATE league_teams SET team_name = ? WHERE period = ? AND team_index = ?",
                    (coc_team_name, cwl_period, team_index),
                )

            n_ok += 1
    conn.commit()
    conn.close()

    if n_ok:
        print(f"[import] {n_ok} 条战绩 → league_results + results（period={cwl_period}）" +
              (f"，跳过 {n_skip} 条（不在 accounts）" if n_skip else ""))
    return n_ok, n_skip


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="拉取 CWL 数据 + 导入 league_results/results 表")
    parser.add_argument("--period", required=True, help="CWL 月份（实际发生月），如 2026-07")
    parser.add_argument("--fetch-only", action="store_true",
                        help="仅拉取 JSON，不导入数据库")
    args = parser.parse_args()

    # period = CWL 实际发生月，直接用于 API 拉取、数据目录命名、league_results/results 入库
    cwl_period = args.period

    # 延迟加载队伍列表（按 period 从 league_teams 或 config 读取）
    global TEAMS_TO_FETCH
    TEAMS_TO_FETCH = _load_teams_to_fetch(cwl_period)

    data_dir = DATA_ROOT / f"cwl_{cwl_period.replace('-', '')}"
    print(f"CWL 发生月: {cwl_period}（数据目录: {data_dir}）")
    print(f"拉取队伍: {[alias for _, alias, _ in TEAMS_TO_FETCH]}")

    # ── 拉取 ──
    ok_teams = _fetch_from_api(data_dir)

    if args.fetch_only:
        return 0 if ok_teams else 1

    # ── 导入 ──
    if not ok_teams:
        print(ALERT_LINE)
        print(f"🚨 全部队伍拉取失败 & {data_dir} 无 JSON")
        print("🚨 编排时自动跳过升降级")
        print(ALERT_LINE)
        return 1

    # 导入全部可用 JSON 到 league_results + results 表
    n_ok, n_skip = _import_to_results(data_dir, cwl_period, TEAMS_TO_FETCH)

    if n_ok == 0:
        print(ALERT_LINE + f"⚠️ 0 条战绩导入（{n_skip} 条不在 accounts）" + ALERT_LINE)
        return 1

    # ── 升降级参与总结 ──
    team_order = [alias for _, alias, _ in TEAMS_TO_FETCH]
    print(f"\n── 升降级参与情况（{cwl_period} CWL）──")
    for i in range(len(team_order) - 1):
        hi, lo = team_order[i], team_order[i + 1]
        hi_ok = hi in ok_teams
        lo_ok = lo in ok_teams
        if hi_ok and lo_ok:
            print(f"  ✅ {hi} ↔ {lo}")
        else:
            missing = [t for t, ok in [(hi, hi_ok), (lo, lo_ok)] if not ok]
            print(f"  ⛔ {hi} ↔ {lo}  跳过（缺: {', '.join(missing)}）")

    print(f"\n✅ 数据就绪：{n_ok} 条星数已写入 league_results + results 表（period={cwl_period}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
