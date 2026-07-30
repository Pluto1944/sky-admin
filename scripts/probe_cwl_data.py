"""COC CWL 数据探测脚本 —— 验证我们能从 API 获取哪些 2026-06 月度数据。

用途：
  1. 测试 warlog 是否包含 CWL 战争（以及是否含 warTag 字段）
  2. 测试按 warTag 查 CWL 战争详情的端点
  3. 测试玩家端点是否能提取有用的月度星数数据
  4. 为冷启动方案提供"能拿到什么数据"的事实依据

前置：
  export COC_API_TOKEN='你的token'

用法：
  python scripts/probe_cwl_data.py '#2QQ'                # 查一个部落
  python scripts/probe_cwl_data.py '#2QQ' --warlog-limit 10  # 指定 war log 条数
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# 项目根路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.coc_sync.api_client import CocApiClient, CocApiError  # noqa: E402


# ============================================================
# 核心探测逻辑
# ============================================================

def probe_league_group(client: CocApiClient, clan_tag: str):
    """探测 1：当前联赛组（仅 CWL 周有效）"""
    print("\n" + "=" * 60)
    print("探测 1：当前联赛组 (leaguegroup)")
    print("=" * 60)
    result = client.get_league_group(clan_tag)
    if result is None:
        print("→ 无当前联赛组（不在 CWL 周，或部落未参赛）")
        return None
    print(f"→ 联赛组已找到！赛季: {result.get('season')}, 状态: {result.get('state')}")
    rounds = result.get("rounds", [])
    print(f"→ 共 {len(rounds)} 轮，war tags 如下：")
    all_war_tags = []
    for r in rounds:
        tags = r.get("warTags", [])
        all_war_tags.extend(tags)
        print(f"  第 {r.get('round', '?')} 轮: {tags}")
    return all_war_tags


def probe_warlog(client: CocApiClient, clan_tag: str, limit: int = 20):
    """探测 2：战争日志（看是否含 CWL 战争 + warTag）"""
    print("\n" + "=" * 60)
    print(f"探测 2：战争日志 (warlog) —— 前{limit}条")
    print("=" * 60)
    try:
        items = client.get_clan_warlog(clan_tag, limit=limit)
    except CocApiError as e:
        print(f"→ 查询失败: {e}")
        return []

    print(f"→ 共返回 {len(items)} 条战争记录\n")
    war_tags_found = []

    for i, item in enumerate(items):
        result = item.get("result") or "?"
        team_size = item.get("teamSize") or "?"
        stars = item.get("stars")
        stars_str = f"{stars}⭐" if stars is not None else "?⭐"
        opponent = item.get("opponent") or {}
        opponent_name = opponent.get("name", "?")
        end_time = item.get("endTime") or "?"
        end_date = end_time[:10] if end_time != "?" else "?"
        war_tag = item.get("warTag")  # 关键字段：warlog 是否返回 warTag？

        tag_info = f"warTag={war_tag}" if war_tag else "无 warTag"

        print(f"[{i+1:>2}] {end_date} | {team_size}v{team_size} | "
              f"{result} | {stars_str} | vs {opponent_name} | {tag_info}")

        # 打印原始 keys 以便检查是否有 warTag（前3条）
        if i < 3:
            print(f"     keys: {sorted(item.keys())}")

        if end_time.startswith("2026-06"):
            print(f"     ↑ 2026年6月的数据！")

        if war_tag:
            war_tags_found.append(war_tag)

    print(f"\n→ 其中含 warTag 的: {len(war_tags_found)} 条")
    print(f"→ 2026-06 的: {sum(1 for i in items if i.get('endTime','').startswith('2026-06'))} 条")
    return war_tags_found


def probe_cwl_war_detail(client: CocApiClient, war_tags: list[str], max_probe: int = 3):
    """探测 3：按 warTag 查 CWL 战争详情（玩家级星数数据）"""
    print("\n" + "=" * 60)
    print(f"探测 3：CWL 战争详情 (前{max_probe}个 warTag)")
    print("=" * 60)

    all_player_stars: dict[str, dict] = {}

    for idx, war_tag in enumerate(war_tags[:max_probe]):
        try:
            detail = client.get_cwl_war(war_tag)
        except CocApiError as e:
            print(f"[{idx+1}] {war_tag} → 查询失败: {e}")
            continue

        state = detail.get("state", "?")
        team_size = detail.get("teamSize", "?")
        clan = detail.get("clan", {})
        opponent = detail.get("opponent", {})
        clan_name = clan.get("name", "?")
        opponent_name = opponent.get("name", "?")
        clan_stars = clan.get("stars", "?")
        opponent_stars = opponent.get("stars", "?")
        start_time = detail.get("startTime", "?")[:10] if detail.get("startTime") else "?"

        print(f"\n[{idx+1}] warTag={war_tag}")
        print(f"    状态: {state} | {team_size}v{team_size} | {start_time}")
        print(f"    {clan_name} {clan_stars}⭐ vs {opponent_name} {opponent_stars}⭐")

        for side_label, side_data in [("我方", clan), ("对手", opponent)]:
            members = side_data.get("members", [])
            for m in members:
                tag = m.get("tag", "")
                name = m.get("name", "")
                attacks = m.get("attacks", [])
                total_stars = sum(a.get("stars", 0) for a in attacks)
                total_attacks = len(attacks)

                if tag not in all_player_stars:
                    all_player_stars[tag] = {
                        "name": name,
                        "total_stars": 0,
                        "total_attacks": 0,
                        "wars_count": 0,
                    }
                rec = all_player_stars[tag]
                rec["total_stars"] += total_stars
                rec["total_attacks"] += total_attacks
                rec["wars_count"] += 1

                print(f"    {side_label} {name}({tag}) : {total_stars}星/{total_attacks}场进攻")

    print("\n--- 汇总统计 ---")
    print(f"共 {len(all_player_stars)} 名玩家参与（去重后）")
    for tag, rec in sorted(all_player_stars.items(),
                           key=lambda x: x[1]["total_stars"], reverse=True)[:10]:
        print(f"  {rec['name']}({tag}) : "
              f"总计 {rec['total_stars']}星/{rec['total_attacks']}场进攻 "
              f"({rec['wars_count']}场战争)")

    return all_player_stars


def probe_clan_members(client: CocApiClient, clan_tag: str):
    """探测 4：当前部落成员列表（作为对比）"""
    print("\n" + "=" * 60)
    print("探测 4：当前部落成员")
    print("=" * 60)
    try:
        members = client.get_clan_members(clan_tag)
    except CocApiError as e:
        print(f"→ 查询失败: {e}")
        return {}

    print(f"→ {clan_tag} 共 {len(members)} 人\n")
    member_tags = {}
    for m in members[:5]:
        tag = m.get("tag", "")
        name = m.get("name", "")
        role = m.get("role", "")
        member_tags[tag] = name
        print(f"  {name} ({tag}) {role}")
    if len(members) > 5:
        print(f"  ... 还有 {len(members)-5} 人")
    print(f"\n→ 共 {len(members)} 人")
    return member_tags


def probe_player_stars(client: CocApiClient, members: dict[str, str], max_probe: int = 3):
    """探测 5：查个别玩家的 warStars（全历史累计值）"""
    print("\n" + "=" * 60)
    print(f"探测 5：玩家 warStars（前{max_probe}人）")
    print("=" * 60)
    for i, (tag, name) in enumerate(list(members.items())[:max_probe]):
        try:
            player = client.get_player(tag)
        except CocApiError as e:
            print(f"[{i+1}] {name}({tag}) → 查询失败: {e}")
            continue

        war_stars = player.get("warStars", "?")
        attack_wins = player.get("attackWins", "?")
        clan_info = player.get("clan", {})

        print(f"[{i+1}] {name}({tag})")
        print(f"    warStars(全历史): {war_stars}⭐")
        print(f"    attackWins: {attack_wins}")
        print(f"    当前部落: {clan_info.get('name', '无')} ({clan_info.get('tag', '')})")
        print(f"    联赛段位: {(player.get('league') or {}).get('name', '-')}")


# ============================================================
# 主入口
# ============================================================

def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="COC CWL 数据探测 —— 验证可用的 API 端点"
    )
    parser.add_argument("clan_tag", help="部落标签，如 #2QQ")
    parser.add_argument("--warlog-limit", type=int, default=20,
                        help="warlog 查询条数 (默认 20)")
    parser.add_argument("--war-detail-max", type=int, default=3,
                        help="最多查询几个 CWL war 详情 (默认 3)")
    parser.add_argument("--player-max", type=int, default=3,
                        help="最多查询几个玩家 (默认 3)")
    parser.add_argument("--skip-warlog", action="store_true",
                        help="跳过 warlog 探测")
    parser.add_argument("--skip-war-detail", action="store_true",
                        help="跳过 war detail 探测")

    args = parser.parse_args(argv[1:])

    if not os.environ.get("COC_API_TOKEN"):
        print("错误: 未设置环境变量 COC_API_TOKEN", file=sys.stderr)
        print("  export COC_API_TOKEN='你的token'", file=sys.stderr)
        return 1

    client = CocApiClient()

    clan_tag = args.clan_tag

    print(f"🔍 探测目标部落: {clan_tag}")
    print(f"⏰ 当前时间: {datetime.now(timezone.utc).isoformat()}")

    # 1. 当前联赛组（仅 CWL 周）
    league_tags = probe_league_group(client, clan_tag)

    # 2. 战争日志
    war_tags = []
    if not args.skip_warlog:
        war_tags = probe_warlog(client, clan_tag, limit=args.warlog_limit)

    # 如果有 league group 获得的 tags，优先使用
    all_war_tags = list(dict.fromkeys((league_tags or []) + war_tags))

    # 3. 战争详情
    if not args.skip_war_detail and all_war_tags:
        probe_cwl_war_detail(client, all_war_tags, max_probe=args.war_detail_max)
    elif not all_war_tags:
        print("\n⚠️  没有找到任何 warTag，无法查询战争详情。")

    # 4. 当前部落成员
    members = probe_clan_members(client, clan_tag)

    # 5. 玩家 stars（全历史）
    if members:
        probe_player_stars(client, members, max_probe=args.player_max)

    # 总结
    print("\n" + "=" * 60)
    print("📋 探测总结")
    print("=" * 60)
    print(f"1. 当前联赛组: {'✅ 可用' if league_tags else '❌ 不可用（不在 CWL 周）'}")
    print(f"2. warLog 含 CWL: 见上方详情")
    print(f"3. warLog 含 warTag: {'✅' if war_tags else '❌ 或无 warTag 字段'}")
    print(f"4. warDetail 可查历史: {'✅' if all_war_tags else '需有 warTag'}")
    print(f"5. 成员名单: ✅ 可用（当前时刻，非历史）")
    print(f"6. 玩家 warsStars: ⚠️ 全历史累计，非月度值")
    print()
    print("结论：请根据以上探测结果，确认冷启动数据获取路径。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
