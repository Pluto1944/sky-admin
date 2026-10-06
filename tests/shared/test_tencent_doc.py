"""腾讯文档双后端适配器测试。"""
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
        backend="openapi",
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
    monkeypatch.delenv("TENCENT_DOC_ACCESS_TOKEN", raising=False)
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
        backend="openapi",
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
        backend="openapi",
        access_token="expired-access",
        client_id="client-id",
        open_id="open-id",
    )

    with pytest.raises(TencentDocError, match="400006"):
        adapter._request("GET", "/openapi/test")
    assert len(requests) == 1


def test_auto_backend_prefers_mcp_token(monkeypatch):
    monkeypatch.setenv("TENCENT_DOCS_TOKEN", "mcp-token")
    adapter = TencentDocAdapter(backend="auto")

    assert adapter._backend == "mcp"


def test_auto_backend_falls_back_to_openapi_without_mcp_token(monkeypatch):
    monkeypatch.delenv("TENCENT_DOCS_TOKEN", raising=False)
    monkeypatch.delenv("TENCENT_DOC_MCP_TOKEN", raising=False)
    adapter = TencentDocAdapter(backend="auto")

    assert adapter._backend == "openapi"


def test_mcp_read_sheet_fills_merged_cells(monkeypatch):
    adapter = TencentDocAdapter(backend="mcp", mcp_token="mcp-token")
    calls = []

    def fake_call(name, arguments):
        calls.append((name, arguments))
        if name == "sheet.get_sheet_info":
            return {
                "sheets": [
                    {
                        "sheet_id": "sheet-1",
                        "sheet_name": "报名",
                        "row_count": 3,
                        "col_count": 2,
                        "used_range": {"row_count": 3, "col_count": 2},
                    }
                ]
            }
        if name == "sheet.get_cell_data":
            return {
                "cells": [
                    {"row": 0, "col": 0, "value_type": "STRING", "string_value": "主号"},
                    {"row": 0, "col": 1, "value_type": "STRING", "string_value": "账号"},
                    {"row": 1, "col": 0, "value_type": "STRING", "string_value": "玩家A"},
                    {"row": 1, "col": 1, "value_type": "STRING", "string_value": "小号1"},
                    {"row": 2, "col": 1, "value_type": "STRING", "string_value": "小号2"},
                ]
            }
        if name == "sheet.get_merged_cells":
            return {"merged_cells": ["sheet-1$A2:A3"]}
        raise AssertionError(name)

    monkeypatch.setattr(adapter, "_mcp_call", fake_call)

    rows = adapter.read_sheet("file-1", "报名", fill_merged=True)

    assert rows == [
        {"主号": "玩家A", "账号": "小号1"},
        {"主号": "玩家A", "账号": "小号2"},
    ]
    assert [name for name, _ in calls] == [
        "sheet.get_sheet_info",
        "sheet.get_cell_data",
        "sheet.get_merged_cells",
    ]
    assert calls[1][1]["end_row"] == 2
    assert calls[1][1]["end_col"] == 1


def test_mcp_batch_update_maps_values_and_styles(monkeypatch):
    adapter = TencentDocAdapter(backend="mcp", mcp_token="mcp-token")
    calls = []

    def fake_call(name, arguments):
        calls.append((name, arguments))
        return {}

    monkeypatch.setattr(adapter, "_mcp_call", fake_call)
    red = {"fontColor": {"red": 255, "green": 0, "blue": 0, "alpha": 255}}

    adapter._batch_update(
        "file-1",
        [
            {
                "updateRangeRequest": {
                    "sheetId": "sheet-1",
                    "gridData": {
                        "startRow": 5,
                        "startColumn": 2,
                        "rows": [
                            {"values": [adapter._cell("昵称", red), adapter._cell(15)]}
                        ],
                    },
                }
            }
        ],
    )

    assert calls[0][0] == "sheet.set_range_value"
    assert calls[0][1]["values"] == [
        {"row": 5, "col": 2, "value_type": "STRING", "string_value": "昵称"},
        {"row": 5, "col": 3, "value_type": "NUMBER", "number_value": 15},
    ]
    assert calls[1] == (
        "sheet.set_cell_style",
        {
            "file_id": "file-1",
            "sheet_id": "sheet-1",
            "start_row": 5,
            "end_row": 5,
            "start_col": 2,
            "end_col": 2,
            "font_color": "FFFF0000",
        },
    )


def test_mcp_recreate_clears_and_resizes_existing_sheet(monkeypatch):
    adapter = TencentDocAdapter(backend="mcp", mcp_token="mcp-token")
    calls = []

    monkeypatch.setattr(
        adapter,
        "_list_sheets",
        lambda file_id: [
            {
                "sheetId": "sheet-1",
                "title": "名单",
                "rowCount": 200,
                "columnCount": 20,
            }
        ],
    )
    monkeypatch.setattr(
        adapter, "_mcp_call", lambda name, arguments: calls.append((name, arguments)) or {}
    )
    resized = []
    monkeypatch.setattr(
        adapter,
        "_resize_mcp_sheet",
        lambda file_id, sheet_id, row_count, col_count: resized.append(
            (file_id, sheet_id, row_count, col_count)
        ),
    )

    result = adapter._recreate_sheet("file-1", "sheet-1", "名单", 16, 4)

    assert result == "sheet-1"
    assert calls == [
        (
            "sheet.clear_range_cells",
            {
                "file_id": "file-1",
                "sheet_id": "sheet-1",
                "start_row": 0,
                "start_col": 0,
                "end_row": 199,
                "end_col": 19,
            },
        )
    ]
    assert resized == [("file-1", "sheet-1", 16, 4)]


def test_mcp_write_sheet_applies_freeze_and_filter(monkeypatch):
    adapter = TencentDocAdapter(backend="mcp", mcp_token="mcp-token")
    calls = []

    monkeypatch.setattr(
        adapter,
        "_list_sheets",
        lambda file_id: [
            {
                "sheetId": "sheet-1",
                "title": "名单",
                "rowCount": 2,
                "columnCount": 2,
            }
        ],
    )
    monkeypatch.setattr(adapter, "_recreate_sheet", lambda *args: "sheet-1")
    monkeypatch.setattr(
        adapter,
        "_write_range",
        lambda file_id, sheet_id, matrix: calls.append(("write", matrix)),
    )
    monkeypatch.setattr(
        adapter, "_mcp_call", lambda name, arguments: calls.append((name, arguments)) or {}
    )

    adapter.write_sheet(
        "file-1",
        [{"昵称": "玩家A", "星数": 15}],
        headers=["昵称", "星数"],
        sheet="名单",
        freeze_header=True,
        auto_filter=True,
    )

    assert [item[0] for item in calls] == [
        "write",
        "sheet.set_freeze",
        "sheet.set_filter",
    ]
    assert calls[2][1]["end_row"] == 1
    assert calls[2][1]["end_col"] == 1


class _MCPResponse(_Response):
    def __init__(self, data: dict | None, headers: dict | None = None):
        self._raw = b"" if data is None else json.dumps(data).encode("utf-8")
        self.headers = headers or {"Content-Type": "application/json"}


def test_mcp_initializes_once_and_reuses_session(monkeypatch):
    requests = []
    responses = iter(
        [
            _MCPResponse(
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}},
                {"Content-Type": "application/json", "Mcp-Session-Id": "session-1"},
            ),
            _MCPResponse(None),
            _MCPResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"structuredContent": {"sheets": []}},
                }
            ),
            _MCPResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {"structuredContent": {"sheets": []}},
                }
            ),
        ]
    )

    def fake_urlopen(request, timeout):
        requests.append(request)
        return next(responses)

    monkeypatch.setattr("shared.io_adapter.tencent_doc.urlopen", fake_urlopen)
    adapter = TencentDocAdapter(backend="mcp", mcp_token="mcp-token")

    assert adapter._mcp_call("sheet.get_sheet_info", {"file_id": "f"}) == {"sheets": []}
    assert adapter._mcp_call("sheet.get_sheet_info", {"file_id": "f"}) == {"sheets": []}
    assert len(requests) == 4
    headers = {key.lower(): value for key, value in requests[2].header_items()}
    assert headers["authorization"] == "mcp-token"
    assert headers["mcp-session-id"] == "session-1"
