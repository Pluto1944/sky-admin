"""部落官方资料规范化。

本模块只负责纯转换，不做网络或数据库 I/O。
"""
from __future__ import annotations

from modules.coc_sync.official.mapper import normalize_tag


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_named_item(value: dict | None) -> dict | None:
    if not isinstance(value, dict) or not value:
        return None
    result = {
        "id": _int(value.get("id")),
        "name": value.get("name") or "",
    }
    if value.get("countryCode"):
        result["country_code"] = value["countryCode"]
    if "isCountry" in value:
        result["is_country"] = bool(value.get("isCountry"))
    return result


def normalize_clan_profile(raw: dict, configured: dict, synced_at: str) -> dict:
    """将 `/clans/{tag}` 响应转为前端稳定模型。"""
    badge_urls = raw.get("badgeUrls") or {}
    labels = []
    for label in raw.get("labels") or []:
        icons = label.get("iconUrls") or {}
        labels.append({
            "id": _int(label.get("id")),
            "name": label.get("name") or "",
            "icon_urls": {
                key: icons[key]
                for key in ("small", "medium")
                if icons.get(key)
            },
        })

    return {
        "clan_tag": normalize_tag(raw.get("tag") or configured.get("tag")),
        "name": raw.get("name") or configured.get("name") or configured.get("tag"),
        "category": configured.get("category", "normal"),
        "clan_level": _int(raw.get("clanLevel")),
        "official_member_count": _int(raw.get("members")),
        "join_type": raw.get("type") or "",
        "description": raw.get("description") or "",
        "war_frequency": raw.get("warFrequency") or "",
        "war_win_streak": _int(raw.get("warWinStreak")),
        "war_wins": _int(raw.get("warWins")),
        "war_ties": _int(raw.get("warTies")),
        "war_losses": _int(raw.get("warLosses")),
        "is_war_log_public": bool(raw.get("isWarLogPublic")),
        "clan_points": _int(raw.get("clanPoints")),
        "builder_base_points": _int(raw.get("clanBuilderBasePoints")),
        "capital_points": _int(raw.get("clanCapitalPoints")),
        "required_trophies": _int(raw.get("requiredTrophies")),
        "required_builder_base_trophies": _int(raw.get("requiredBuilderBaseTrophies")),
        "required_town_hall_level": _int(raw.get("requiredTownhallLevel")),
        "is_family_friendly": bool(raw.get("isFamilyFriendly")),
        "location": _compact_named_item(raw.get("location")),
        "war_league": _compact_named_item(raw.get("warLeague")),
        "capital_league": _compact_named_item(raw.get("capitalLeague")),
        "badge_urls": {
            key: badge_urls[key]
            for key in ("small", "medium", "large")
            if badge_urls.get(key)
        },
        "labels": labels,
        "synced_at": synced_at,
    }
