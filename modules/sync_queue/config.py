"""M4 queue feature switches shared by planner, worker and legacy jobs."""
from __future__ import annotations

import os
from collections.abc import Iterable


RESOURCE_TYPES = ("clan_profile", "clan_members", "current_war", "cwl_live")
RESOURCE_TYPE_SET = frozenset(RESOURCE_TYPES)


def parse_resource_types(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    raw = value.split(",") if isinstance(value, str) else value
    selected: list[str] = []
    for item in raw:
        name = str(item).strip()
        if not name:
            continue
        if name not in RESOURCE_TYPE_SET:
            raise ValueError(f"unsupported sync queue resource type: {name}")
        if name not in selected:
            selected.append(name)
    return tuple(selected)


def live_resource_types() -> tuple[str, ...]:
    return parse_resource_types(os.getenv("SYNC_QUEUE_LIVE_TYPES", ""))


def worker_enabled() -> bool:
    return os.getenv("SYNC_QUEUE_WORKER_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def active_live_resource_types() -> tuple[str, ...]:
    """Return cut-over types only when the live worker is explicitly enabled."""
    return live_resource_types() if worker_enabled() else ()
