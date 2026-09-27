import json

import pytest
from fastapi import HTTPException

import api_server.routes as routes
from modules.coc_sync.current_war import normalize_current_war

from .test_current_war import _war


def _seed(db):
    item = normalize_current_war(
        _war(), {"tag": "#AAA", "name": "我方", "category": "combat"},
        "2026-09-27T01:00:00+00:00",
    )
    db.conn.execute(
        """INSERT INTO current_war_cache
           (clan_tag, clan_name, category, status, data_json, error, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("#AAA", "我方", "combat", item["status"], json.dumps(item), None, item["synced_at"]),
    )
    db.conn.commit()


def test_current_wars_returns_configured_summary_and_pending_clan(db, monkeypatch):
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#AAA", "name": "我方", "category": "combat", "enabled": True},
        {"tag": "#CCC", "name": "未同步", "category": "farm", "enabled": True},
    ])
    _seed(db)

    response = routes.current_wars(db)

    assert [item["clan_tag"] for item in response["clans"]] == ["#AAA", "#CCC"]
    assert response["clans"][0]["status"] == "in_war"
    assert "rows" not in response["clans"][0]
    assert response["clans"][1]["status"] == "sync_pending"
    assert response["categories"] == [
        {"key": "combat", "label": "战营"},
        {"key": "farm", "label": "互刷"},
    ]


def test_current_war_detail_returns_rows_and_rejects_external_clan(db, monkeypatch):
    monkeypatch.setattr(routes, "CLANS", [
        {"tag": "#AAA", "name": "我方", "category": "combat", "enabled": True},
    ])
    _seed(db)

    detail = routes.current_war_detail("#aaa", db)
    assert detail["clan_tag"] == "#AAA"
    assert len(detail["rows"]) == 2

    with pytest.raises(HTTPException) as exc:
        routes.current_war_detail("#OUTSIDE", db)
    assert exc.value.status_code == 404
