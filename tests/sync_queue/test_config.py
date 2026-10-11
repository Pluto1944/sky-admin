import pytest

from modules.sync_queue.config import active_live_resource_types, parse_resource_types


def test_parse_resource_types_deduplicates_and_preserves_cutover_order():
    assert parse_resource_types("clan_profile,current_war,clan_profile") == (
        "clan_profile", "current_war",
    )


def test_parse_resource_types_rejects_unknown_handler():
    with pytest.raises(ValueError, match="unsupported"):
        parse_resource_types("clan_profile,unknown")


def test_live_cutover_only_becomes_active_when_worker_is_enabled(monkeypatch):
    monkeypatch.setenv("SYNC_QUEUE_LIVE_TYPES", "clan_profile,current_war")
    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "false")
    assert active_live_resource_types() == ()

    monkeypatch.setenv("SYNC_QUEUE_WORKER_ENABLED", "true")
    assert active_live_resource_types() == ("clan_profile", "current_war")
