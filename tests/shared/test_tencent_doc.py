"""腾讯文档适配器 OAuth 自动刷新测试。"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from shared.io_adapter.tencent_doc import TencentDocAdapter, TencentDocError


class _Response:
    def __init__(self, data: dict):
        self._raw = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._raw


def _header(request, name: str) -> str | None:
    return dict(request.header_items()).get(name)


def test_auth_error_refreshes_access_token_and_retries(monkeypatch):
    requests = []
    responses = iter(
        [
            {"code": 400006, "message": "Authentication Internal Error"},
            {
                "access_token": "fresh-access",
                "expires_in": 259200,
                "user_id": "fresh-open-id",
            },
            {"ret": 0, "data": {"ok": True}},
        ]
    )

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response(next(responses))

    monkeypatch.setattr("shared.io_adapter.tencent_doc.urlopen", fake_urlopen)
    adapter = TencentDocAdapter(
        access_token="expired-access",
        client_id="client-id",
        open_id="old-open-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
    )

    result = adapter._request("GET", "/openapi/test")

    assert result == {"ret": 0, "data": {"ok": True}}
    assert len(requests) == 3
    refresh_query = parse_qs(urlparse(requests[1].full_url).query)
    assert refresh_query == {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "grant_type": ["refresh_token"],
        "refresh_token": ["refresh-token"],
    }
    assert _header(requests[2], "Access-token") == "fresh-access"
    assert _header(requests[2], "Open-id") == "fresh-open-id"


def test_missing_access_token_refreshes_before_request(monkeypatch):
    requests = []
    responses = iter(
        [
            {"access_token": "fresh-access", "user_id": "open-id"},
            {"ret": 0},
        ]
    )

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response(next(responses))

    monkeypatch.setattr("shared.io_adapter.tencent_doc.urlopen", fake_urlopen)
    adapter = TencentDocAdapter(
        client_id="client-id",
        open_id="open-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
    )

    assert adapter._request("GET", "/openapi/test") == {"ret": 0}
    assert "/oauth/v2/token?" in requests[0].full_url
    assert _header(requests[1], "Access-token") == "fresh-access"


def test_auth_error_without_refresh_credentials_is_not_retried(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _Response(
            {"code": 400006, "message": "Authentication Internal Error"}
        )

    monkeypatch.setattr("shared.io_adapter.tencent_doc.urlopen", fake_urlopen)
    adapter = TencentDocAdapter(
        access_token="expired-access",
        client_id="client-id",
        open_id="open-id",
    )

    with pytest.raises(TencentDocError, match="400006"):
        adapter._request("GET", "/openapi/test")
    assert len(requests) == 1
