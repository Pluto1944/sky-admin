"""从历史 CWL 战争日志重建实时看板缓存所需的数据。

本模块只做数据归组、校验和标准化，不发网络请求、不写数据库。
历史战争由调用方提供，便于 dry-run、测试和生产写入前验证。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from modules.coc_sync.cwl_live import normalize_cwl_group, normalize_cwl_war
from modules.coc_sync.official.mapper import normalize_tag


class CwlBackfillError(ValueError):
    """历史数据不足或互相矛盾，不能安全回填。"""


def _war_tag(war: dict) -> str | None:
    return normalize_tag(war.get("tag") or war.get("warTag"))


def _side_tag(side: dict | None) -> str | None:
    return normalize_tag((side or {}).get("tag"))


def _participants(war: dict) -> tuple[str | None, str | None]:
    return _side_tag(war.get("clan")), _side_tag(war.get("opponent"))


def _parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _war_start(war: dict) -> datetime | None:
    return _parse_coc_time(war.get("startTime") or war.get("warStartTime"))


def infer_group_tags(clan_tag: str, own_wars: Iterable[dict]) -> list[str]:
    """从目标部落的完整轮次对手推断该月联赛组全部部落标签。"""
    selected = normalize_tag(clan_tag)
    if not selected:
        raise CwlBackfillError("目标部落缺少有效标签")
    tags = {selected}
    for war in own_wars:
        left, right = _participants(war)
        if selected not in {left, right}:
            continue
        if left:
            tags.add(left)
        if right:
            tags.add(right)
    return sorted(tags)


def _dedupe_group_wars(group_tags: set[str], wars_by_clan: dict[str, list[dict]]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for wars in wars_by_clan.values():
        for war in wars:
            tag = _war_tag(war)
            left, right = _participants(war)
            if tag and left in group_tags and right in group_tags:
                result[tag] = war
    return result


def _round_anchors(clan_tag: str, own_wars: list[dict]) -> list[datetime]:
    selected = normalize_tag(clan_tag)
    anchors = []
    seen = set()
    for war in own_wars:
        if selected not in set(_participants(war)):
            continue
        start = _war_start(war)
        if start and start not in seen:
            anchors.append(start)
            seen.add(start)
    return sorted(anchors)


def _assign_rounds(
    group_tags: set[str],
    group_wars: dict[str, dict],
    anchors: list[datetime],
) -> list[list[str]]:
    if not anchors:
        raise CwlBackfillError("目标部落没有可用的轮次时间")
    rounds: list[list[str]] = [[] for _ in anchors]
    for tag, war in group_wars.items():
        start = _war_start(war)
        if start is None:
            raise CwlBackfillError(f"战争 {tag} 缺少开战时间")
        distances = [abs((start - anchor).total_seconds()) for anchor in anchors]
        index = min(range(len(distances)), key=distances.__getitem__)
        if distances[index] > 12 * 60 * 60:
            raise CwlBackfillError(f"战争 {tag} 无法匹配到轮次")
        rounds[index].append(tag)

    expected_wars = len(group_tags) // 2
    for index, tags in enumerate(rounds, start=1):
        if len(tags) != expected_wars:
            raise CwlBackfillError(
                f"第 {index} 轮战争不完整：期望 {expected_wars} 场，实际 {len(tags)} 场"
            )
        participants = []
        for tag in tags:
            participants.extend(value for value in _participants(group_wars[tag]) if value)
        if len(participants) != len(set(participants)) or set(participants) != group_tags:
            raise CwlBackfillError(f"第 {index} 轮参战部落重复或缺失")
        tags.sort()
    return rounds


def _group_clans(group_tags: set[str], group_wars: dict[str, dict]) -> list[dict]:
    clans: dict[str, dict] = {}
    members: dict[str, dict[str, dict]] = {tag: {} for tag in group_tags}
    for war in group_wars.values():
        for side_key in ("clan", "opponent"):
            side = war.get(side_key) or {}
            tag = _side_tag(side)
            if tag not in group_tags:
                continue
            entry = clans.setdefault(tag, {
                "tag": tag,
                "name": side.get("name") or tag,
                "clanLevel": side.get("clanLevel") or 0,
                "badgeUrls": side.get("badgeUrls") or {},
            })
            if side.get("name"):
                entry["name"] = side["name"]
            if side.get("clanLevel"):
                entry["clanLevel"] = side["clanLevel"]
            if side.get("badgeUrls"):
                entry["badgeUrls"] = side["badgeUrls"]
            for member in side.get("members") or []:
                member_tag = normalize_tag(member.get("tag"))
                if not member_tag:
                    continue
                existing = members[tag].get(member_tag, {})
                town_hall = (
                    member.get("townHallLevel")
                    or member.get("townhallLevel")
                    or existing.get("townHallLevel")
                    or 0
                )
                members[tag][member_tag] = {
                    "tag": member_tag,
                    "name": member.get("name") or existing.get("name") or member_tag,
                    "townHallLevel": town_hall,
                }

    missing = group_tags - set(clans)
    if missing:
        raise CwlBackfillError(f"缺少部落资料：{', '.join(sorted(missing))}")
    result = []
    for tag in sorted(clans):
        result.append({**clans[tag], "members": list(members[tag].values())})
    return result


def build_historical_cwl_cache(
    team: dict,
    wars_by_clan: dict[str, list[dict]],
    synced_at: str,
) -> tuple[dict, dict[str, dict], dict]:
    """重建一个自有部落所属联赛组，返回 group、战争映射和校验摘要。"""
    selected = normalize_tag(team.get("clan_tag") or team.get("tag"))
    own_wars = wars_by_clan.get(selected, [])
    if not own_wars:
        raise CwlBackfillError(f"{selected} 没有历史 CWL 战争")
    group_tags = set(infer_group_tags(selected, own_wars))
    if len(group_tags) < 2 or len(group_tags) % 2:
        raise CwlBackfillError(f"{selected} 推断出的联赛组数量异常：{len(group_tags)}")
    anchors = _round_anchors(selected, own_wars)
    if len(anchors) != len(group_tags) - 1:
        raise CwlBackfillError(
            f"{selected} 轮次数与组规模不符：{len(anchors)} 轮 / {len(group_tags)} 队"
        )
    group_wars = _dedupe_group_wars(group_tags, wars_by_clan)
    rounds = _assign_rounds(group_tags, group_wars, anchors)
    raw_group = {
        "season": team["period"],
        "state": "ended",
        "clans": _group_clans(group_tags, group_wars),
        "rounds": [{"warTags": tags} for tags in rounds],
    }
    group = normalize_cwl_group(raw_group, team, synced_at)
    group["source"] = "clashking_history_backfill"
    group["backfilled_at"] = synced_at
    normalized_wars = {}
    for tag, raw in group_wars.items():
        item = normalize_cwl_war(raw, tag, synced_at)
        item["source"] = "clashking_history_backfill"
        item["backfilled_at"] = synced_at
        normalized_wars[tag] = item
    summary = {
        "clan_tag": selected,
        "group_clans": len(group_tags),
        "rounds": len(rounds),
        "wars": len(normalized_wars),
        "member_count": len(next(
            (clan["members"] for clan in group["clans"] if clan["tag"] == selected),
            [],
        )),
    }
    return group, normalized_wars, summary
