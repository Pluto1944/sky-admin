#!/usr/bin/env python3
"""从 ClashKing 历史战争日志回填指定月份的 CWL 实时看板缓存。

默认只做 dry-run；验证全部月度队伍成功后，显式传入 ``--apply`` 才写库。

用法：
    python scripts/backfill_cwl_live.py --period 2026-09
    python scripts/backfill_cwl_live.py --period 2026-09 --apply
    python scripts/backfill_cwl_live.py --period 2026-08 --prefer-archive
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.env_loader import load_env  # noqa: E402
load_env()

import config  # noqa: E402
from modules.coc_sync.clashking.client import (  # noqa: E402
    fetch_historical_cwl_groups,
    filter_cwl_wars,
)
from modules.coc_sync.cwl_backfill import (  # noqa: E402
    CwlBackfillError,
    build_historical_cwl_cache,
    infer_group_tags,
)
from modules.coc_sync.cwl_live import build_cwl_dashboard  # noqa: E402
from modules.coc_sync.cwl_projection import group_raw_status, rebuild_league_results  # noqa: E402
from modules.coc_sync.official.mapper import normalize_tag  # noqa: E402
from shared.db.connection import Database  # noqa: E402


class MultipleCwlSeasonsError(CwlBackfillError):
    """The monthly single-group cache cannot represent several CWL seasons."""


def _valid_period(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m") == value
    except (TypeError, ValueError):
        return False


def _load_teams(db: Database, period: str) -> list[dict]:
    rows = db.conn.execute(
        """SELECT period, team_index, team_alias, team_name, clan_tag,
                  category, member_count, league_level
           FROM league_teams
           WHERE period = ? AND category IN ('combat', 'shell')
           ORDER BY team_index""",
        (period,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_cached(
    cache: dict[str, list[dict]],
    clan_tag: str,
    period: str,
) -> list[dict]:
    tag = normalize_tag(clan_tag)
    if tag not in cache:
        print(f"  [fetch] {tag}", flush=True)
        cache[tag] = filter_cwl_wars(tag, period)
        print(f"          {len(cache[tag])} 场", flush=True)
    return cache[tag]


def _validate_history_totals(
    db: Database,
    period: str,
    clan_tag: str,
    dashboard: dict,
) -> tuple[int, list[str]]:
    historical = db.conn.execute(
        """SELECT player_tag, total_stars, attacks
           FROM league_results WHERE period = ? AND clan_tag = ?""",
        (period, clan_tag),
    ).fetchall()
    offense = {
        normalize_tag(item.get("player_tag")): item
        for item in dashboard.get("overview", {}).get("offense", {}).get("rows", [])
    }
    mismatches = []
    for row in historical:
        tag = normalize_tag(row["player_tag"])
        current = offense.get(tag)
        if current is None:
            mismatches.append(f"{tag}: 历史汇总存在但逐场数据缺失")
            continue
        expected = (int(row["total_stars"] or 0), int(row["attacks"] or 0))
        actual = (int(current.get("total_stars") or 0), int(current.get("attacks") or 0))
        if actual != expected:
            mismatches.append(f"{tag}: 星/刀 {actual} != 历史 {expected}")
    return len(historical), mismatches


def _build_from_stored_groups(
    db: Database,
    period: str,
    team: dict,
    timestamp: str,
) -> tuple[dict, dict[str, dict], dict, int]:
    """Build and verify a bundle from ClashKing's dedicated CWL archive."""
    stored_groups = fetch_historical_cwl_groups(team["clan_tag"], period)
    if len(stored_groups) > 1:
        seasons = ", ".join(str(group.get("season") or "-") for group in stored_groups)
        raise MultipleCwlSeasonsError(
            f"同一部落同月存在 {len(stored_groups)} 套 CWL 赛季档案：{seasons}"
        )
    errors = []
    for stored in stored_groups:
        try:
            group_tags = {
                normalize_tag(clan.get("tag"))
                for clan in stored.get("clans") or []
                if normalize_tag(clan.get("tag"))
            }
            raw_wars = [
                war
                for round_item in stored.get("rounds") or []
                for war in (round_item.get("warTags") or [])
                if isinstance(war, dict)
            ]
            if not group_tags or not raw_wars:
                raise CwlBackfillError("专用 CWL 档案缺少部落或逐场数据")
            group, wars, summary = build_historical_cwl_cache(
                team,
                {tag: raw_wars for tag in group_tags},
                timestamp,
            )
            dashboard = build_cwl_dashboard(group, wars)
            checked, mismatches = _validate_history_totals(
                db, period, normalize_tag(team["clan_tag"]), dashboard
            )
            if mismatches:
                preview = "；".join(mismatches[:5])
                raise CwlBackfillError(
                    f"与 league_results 不一致 {len(mismatches)} 条：{preview}"
                )
            group["source"] = "clashking_cwl_archive_backfill"
            for war in wars.values():
                war["source"] = "clashking_cwl_archive_backfill"
            summary["history_rows_checked"] = checked
            summary["dashboard_status"] = dashboard["status"]
            summary["archive_season"] = stored.get("season")
            return group, wars, summary, checked
        except Exception as exc:  # noqa: BLE001 - try every matching archive season
            errors.append(str(exc))
    detail = "；".join(errors) if errors else "未找到匹配月份的专用 CWL 档案"
    raise CwlBackfillError(detail)


def _build_from_war_logs(
    db: Database,
    period: str,
    team: dict,
    timestamp: str,
    fetched: dict[str, list[dict]],
) -> tuple[dict, dict[str, dict], dict]:
    """Build and verify a bundle from per-clan historical war logs."""
    selected = normalize_tag(team["clan_tag"])
    own_wars = _fetch_cached(fetched, selected, period)
    group_tags = infer_group_tags(selected, own_wars)
    print(f"  [group] {len(group_tags)} 队：{' '.join(group_tags)}")
    for tag in group_tags:
        _fetch_cached(fetched, tag, period)
    relevant = {tag: fetched[tag] for tag in group_tags}
    group, wars, summary = build_historical_cwl_cache(team, relevant, timestamp)
    dashboard = build_cwl_dashboard(group, wars)
    checked, mismatches = _validate_history_totals(db, period, selected, dashboard)
    if mismatches:
        preview = "；".join(mismatches[:5])
        raise CwlBackfillError(
            f"与 league_results 不一致 {len(mismatches)} 条：{preview}"
        )
    summary["history_rows_checked"] = checked
    summary["dashboard_status"] = dashboard["status"]
    return group, wars, summary


def _write_cache(
    db: Database,
    period: str,
    bundles: list[tuple[dict, dict[str, dict]]],
    timestamp: str,
) -> tuple[int, int]:
    existing_groups = db.conn.execute(
        "SELECT COUNT(*) FROM cwl_live_group_cache WHERE period = ?", (period,)
    ).fetchone()[0]
    existing_wars = db.conn.execute(
        "SELECT COUNT(*) FROM cwl_live_war_cache WHERE season = ?", (period,)
    ).fetchone()[0]
    if existing_groups or existing_wars:
        raise CwlBackfillError(
            f"{period} 已有实时缓存：group={existing_groups}, war={existing_wars}，拒绝覆盖"
        )

    unique_wars: dict[str, dict] = {}
    try:
        db.conn.execute("BEGIN IMMEDIATE")
        for group, wars in bundles:
            group_payload = json.dumps(group, ensure_ascii=False, sort_keys=True)
            db.conn.execute(
                """INSERT INTO cwl_live_group_cache
                   (period, clan_tag, team_index, team_alias, team_name, category,
                    league_level, season, state, status, data_json, error,
                    updated_at, attempted_at, raw_status, raw_complete_at, source,
                    payload_version, payload_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ended', 'ended', ?, NULL, ?, ?,
                           'complete', ?, ?, ?, ?)""",
                (
                    period, group["clan_tag"], group["team_index"], group["team_alias"],
                    group.get("team_name"), group["category"], group.get("league_level"),
                    period, group_payload, timestamp, timestamp, timestamp,
                    group.get("source") or "clashking_history_backfill",
                    int(group.get("payload_version") or 1),
                    hashlib.sha256(group_payload.encode("utf-8")).hexdigest(),
                ),
            )
            unique_wars.update(wars)
        for war_tag, war in unique_wars.items():
            war_payload = json.dumps(war, ensure_ascii=False, sort_keys=True)
            db.conn.execute(
                """INSERT INTO cwl_live_war_cache
                   (war_tag, season, state, status, data_json, error, updated_at, attempted_at,
                    source, finalized_at, payload_version, payload_hash)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)""",
                (
                    war_tag, period, war["state"], war["status"],
                    war_payload, timestamp, timestamp,
                    war.get("source") or "clashking_history_backfill", timestamp,
                    int(war.get("payload_version") or 1),
                    hashlib.sha256(war_payload.encode("utf-8")).hexdigest(),
                ),
            )
        for group, wars in bundles:
            if group_raw_status(group, wars) != "complete":
                raise CwlBackfillError(f"{group['clan_tag']} 回填后仍非完整分组")
            team = {
                key: group.get(key)
                for key in ("period", "team_index", "team_alias", "team_name", "clan_tag", "category")
            }
            rebuild_league_results(db.conn, group, wars, team, rebuilt_at=timestamp)
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    return len(bundles), len(unique_wars)


def run(period: str, apply: bool = False, prefer_archive: bool = False) -> int:
    if not _valid_period(period):
        print("period 必须为 YYYY-MM", file=sys.stderr)
        return 2

    db = Database(config.DB_PATH)
    db.init_schema()
    teams = _load_teams(db, period)
    if not teams:
        print(f"{period} 没有 league_teams 月度快照", file=sys.stderr)
        db.close()
        return 1

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fetched: dict[str, list[dict]] = {}
    bundles: list[tuple[dict, dict[str, dict]]] = []
    summaries = []
    errors = []

    print(f"[{period}] 历史回填 {'APPLY' if apply else 'DRY-RUN'}：{len(teams)} 支队伍")
    for team in teams:
        selected = normalize_tag(team.get("clan_tag"))
        print(f"\n[{team['team_index']}] {team['team_alias']} {team.get('team_name') or ''} {selected}")
        try:
            if prefer_archive:
                try:
                    group, wars, summary, _checked = _build_from_stored_groups(
                        db, period, team, timestamp
                    )
                    print(
                        f"  [archive] season={summary.get('archive_season')}",
                        flush=True,
                    )
                except MultipleCwlSeasonsError:
                    raise
                except Exception as archive_error:  # noqa: BLE001 - verified fallback
                    print(f"  [fallback] 专用 CWL 档案不可用：{archive_error}", flush=True)
                    group, wars, summary = _build_from_war_logs(
                        db, period, team, timestamp, fetched
                    )
            else:
                try:
                    group, wars, summary = _build_from_war_logs(
                        db, period, team, timestamp, fetched
                    )
                except Exception as history_error:  # noqa: BLE001 - verified fallback
                    print(f"  [fallback] 战争日志不完整：{history_error}", flush=True)
                    group, wars, summary, _checked = _build_from_stored_groups(
                        db, period, team, timestamp
                    )
                    print(
                        f"  [archive] season={summary.get('archive_season')}",
                        flush=True,
                    )
            summaries.append(summary)
            bundles.append((group, wars))
            print(
                f"  [ok] {summary['group_clans']}队 {summary['rounds']}轮 "
                f"{summary['wars']}场，核对历史 {summary['history_rows_checked']} 人",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - 汇总所有队伍错误后统一拒绝写入
            errors.append(f"{selected}: {exc}")
            print(f"  [error] {exc}", flush=True)

    print("\n=== 汇总 ===")
    for item in summaries:
        print(
            f"{item['clan_tag']}: {item['group_clans']}队/{item['rounds']}轮/"
            f"{item['wars']}场，成员{item['member_count']}，历史核对{item['history_rows_checked']}"
        )
    if errors:
        print(f"\n失败 {len(errors)} 支，拒绝写入：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        db.close()
        return 1

    if not apply:
        print(f"\nDRY-RUN 通过：{len(bundles)}/{len(teams)} 支队伍；未写数据库。")
        db.close()
        return 0

    groups, wars = _write_cache(db, period, bundles, timestamp)
    db.close()
    print(f"\n写入完成：group={groups}, unique_wars={wars}, period={period}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回填历史 CWL 实时看板缓存")
    parser.add_argument("--period", required=True, help="CWL 实际月份 YYYY-MM")
    parser.add_argument("--apply", action="store_true", help="验证通过后写入数据库；默认 dry-run")
    parser.add_argument(
        "--prefer-archive",
        action="store_true",
        help="优先使用完整 CWL 赛季档案；不可用时再回退战争日志",
    )
    args = parser.parse_args()
    return run(args.period, args.apply, args.prefer_archive)


if __name__ == "__main__":
    raise SystemExit(main())
