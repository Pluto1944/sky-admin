"""都城突袭周末状态推断。

本模块只处理时间窗口和官方赛季响应，不访问网络或数据库。官方突袭周末按
UTC 周五 07:00 开始、周一 07:00 结束；对任意时刻选择最近一次已经开始的
周末作为状态归属，避免在周二至周四把上周结果误判成新一周。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


RAID_START_WEEKDAY = 4  # Friday
RAID_START_HOUR_UTC = 7
RAID_DURATION = timedelta(days=3)


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def raid_weekend_window(now: datetime) -> tuple[datetime, datetime]:
    """返回最近一次已经开始的突袭周末 UTC 起止时间。"""
    current = now.astimezone(timezone.utc)
    days_since_friday = (current.weekday() - RAID_START_WEEKDAY) % 7
    start = (current - timedelta(days=days_since_friday)).replace(
        hour=RAID_START_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if start > current:
        start -= timedelta(days=7)
    return start, start + RAID_DURATION


def summarize_capital_raid_status(
    seasons: list[dict] | None,
    now: datetime,
) -> dict:
    """把官方赛季列表归一为概览卡片所需的稳定状态。"""
    current = now.astimezone(timezone.utc)
    weekend_start, weekend_end = raid_weekend_window(current)
    matched = None
    for season in seasons or []:
        if parse_coc_time(season.get("startTime")) == weekend_start:
            matched = season
            break

    active = current < weekend_end
    if matched is None:
        status = "not_started" if active else "missed"
        raw_state = None
    else:
        raw_state = str(matched.get("state") or "").lower() or None
        status = "ended" if raw_state == "ended" or not active else "ongoing"

    return {
        "status": status,
        "raid_state": raw_state,
        "weekend_start": weekend_start.isoformat(timespec="seconds"),
        "weekend_end": weekend_end.isoformat(timespec="seconds"),
    }
