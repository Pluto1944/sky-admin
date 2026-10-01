from modules.coc_sync.current_war import normalize_current_war
from modules.coc_sync.war_history import (
    is_archivable_war,
    war_history_key,
    war_history_record,
    war_history_summary,
)

from .test_current_war import _war


def test_regular_war_has_stable_key_and_lightweight_summary():
    item = normalize_current_war(
        _war(), {"tag": "#AAA", "name": "我方", "category": "combat"},
        "2026-10-01T01:00:00+00:00",
    )

    assert is_archivable_war(item)
    assert war_history_key(item) == war_history_key(dict(item))
    record = war_history_record(item)
    summary = war_history_summary(item, record["war_key"])
    assert record["clan_tag"] == "#AAA"
    assert record["opponent_tag"] == "#BBB"
    assert summary["war_key"] == record["war_key"]
    assert "rows" not in summary


def test_cwl_and_empty_states_are_not_archivable():
    cwl = _war()
    cwl["type"] = "cwl"
    cwl["attacksPerMember"] = 1
    cwl_item = normalize_current_war(
        cwl, {"tag": "#AAA", "name": "我方"}, "2026-10-01T01:00:00+00:00"
    )
    empty = normalize_current_war(
        {"state": "notInWar"}, {"tag": "#AAA", "name": "我方"},
        "2026-10-01T01:00:00+00:00",
    )

    assert not is_archivable_war(cwl_item)
    assert not is_archivable_war(empty)
