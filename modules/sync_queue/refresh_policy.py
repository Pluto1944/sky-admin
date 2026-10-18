"""Shared refresh intervals for scheduled and user-triggered COC work.

The HTTP layer only queues work.  These helpers keep the eligibility window
used by free-page refreshes aligned with the high-quality automatic policy,
while retaining a much smaller lifecycle safety net for low-tier resources.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from modules.coc_sync.cwl_live import group_war_tags


PROFILE_INTERVAL_SECONDS = 6 * 60 * 60
LOW_DISCOVERY_INTERVAL_SECONDS = 6 * 60 * 60
CURRENT_WAR_ERROR_BACKOFF_SECONDS = (5 * 60, 10 * 60, 20 * 60, 30 * 60)
LOW_ERROR_BACKOFF_SECONDS = (10 * 60, 30 * 60, 60 * 60)
CURRENT_WAR_PREPARATION_SECONDS = 30 * 60
CURRENT_WAR_REALTIME_SECONDS = 2 * 60
CURRENT_WAR_IDLE_SECONDS = 5 * 60
CURRENT_WAR_CWL_SECONDS = 30 * 60
CWL_ACTIVE_SECONDS = 2 * 60
CWL_OTHER_SECONDS = 30 * 60
LIFECYCLE_CONFIRM_DELAY_SECONDS = 2 * 60


def as_utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return as_utc(parsed)


def _json_object(value: object) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _backoff(failures: int, values: tuple[int, ...]) -> int:
    index = min(max(1, failures) - 1, len(values) - 1)
    return values[index]


def paid_current_war_interval_seconds(
    cache: dict | sqlite3.Row | None,
    now: datetime | None = None,
) -> int:
    """Return the automatic high-quality interval for a current-war cache."""
    item = dict(cache) if cache is not None else {}
    current = as_utc(now)
    failures = int(item.get("failure_count") or 0)
    if item.get("status") == "error" or failures > 0:
        return _backoff(failures, CURRENT_WAR_ERROR_BACKOFF_SECONDS)
    status = item.get("status")
    if status == "in_war":
        return CURRENT_WAR_REALTIME_SECONDS
    if status == "preparation":
        start_time = parse_time(_json_object(item.get("data_json")).get("start_time"))
        if start_time is not None and start_time - current <= timedelta(minutes=30):
            return CURRENT_WAR_REALTIME_SECONDS
        return CURRENT_WAR_PREPARATION_SECONDS
    if status == "cwl":
        return CURRENT_WAR_CWL_SECONDS
    return CURRENT_WAR_IDLE_SECONDS


def low_current_war_interval_seconds(
    cache: dict | sqlite3.Row | None,
    now: datetime | None = None,
) -> int:
    """Return the low-tier discovery/finalization interval.

    Free resources do not poll live progress.  Once a preparation or battle is
    discovered, the next automatic check is aimed just after its start/end so
    that the final archive does not depend on a visitor opening the page.
    """
    item = dict(cache) if cache is not None else {}
    current = as_utc(now)
    failures = int(item.get("failure_count") or 0)
    if item.get("status") == "error" or failures > 0:
        return _backoff(failures, LOW_ERROR_BACKOFF_SECONDS)
    status = item.get("status")
    payload = _json_object(item.get("data_json"))
    event_time = None
    if status == "preparation":
        event_time = parse_time(payload.get("start_time"))
    elif status == "in_war":
        event_time = parse_time(item.get("expected_end_at") or payload.get("end_time"))
    if event_time is None:
        return LOW_DISCOVERY_INTERVAL_SECONDS
    delay = int((event_time - current).total_seconds()) + LIFECYCLE_CONFIRM_DELAY_SECONDS
    return max(CURRENT_WAR_REALTIME_SECONDS, delay)


def cwl_page_interval_seconds(
    conn: sqlite3.Connection,
    period: str,
    clan_tag: str,
) -> int:
    """Match the high-quality CWL cadence for an explicit page refresh."""
    rows = _cwl_war_rows(conn, period, clan_tag)
    return CWL_ACTIVE_SECONDS if any(row["state"] == "inWar" for row in rows) else CWL_OTHER_SECONDS


def low_cwl_interval_seconds(
    conn: sqlite3.Connection,
    period: str,
    clan_tag: str,
    now: datetime | None = None,
) -> int:
    """Discover CWL groups infrequently and wake once around round boundaries."""
    current = as_utc(now)
    candidates: list[int] = []
    for row in _cwl_war_rows(conn, period, clan_tag):
        payload = _json_object(row["data_json"])
        event_time = None
        if row["state"] == "inWar":
            event_time = parse_time(payload.get("end_time"))
        elif row["state"] == "preparation":
            event_time = parse_time(payload.get("start_time"))
        if event_time is not None:
            delay = int((event_time - current).total_seconds()) + LIFECYCLE_CONFIRM_DELAY_SECONDS
            candidates.append(max(CWL_ACTIVE_SECONDS, delay))
    return min(candidates) if candidates else LOW_DISCOVERY_INTERVAL_SECONDS


def _cwl_war_rows(
    conn: sqlite3.Connection,
    period: str,
    clan_tag: str,
) -> list[sqlite3.Row]:
    group_row = conn.execute(
        """SELECT data_json FROM cwl_live_group_cache
           WHERE period=? AND clan_tag=? AND data_json IS NOT NULL""",
        (period, clan_tag),
    ).fetchone()
    if group_row is None:
        return []
    war_tags = group_war_tags(_json_object(group_row["data_json"]))
    if not war_tags:
        return []
    placeholders = ",".join("?" for _ in war_tags)
    return conn.execute(
        f"""SELECT state, data_json FROM cwl_live_war_cache
            WHERE war_tag IN ({placeholders})""",
        war_tags,
    ).fetchall()
