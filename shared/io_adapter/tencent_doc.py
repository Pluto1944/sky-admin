"""腾讯文档在线表格适配器（官方 MCP + OpenAPI v3）。

实现 ExcelIO 抽象，把"行字典列表"读写到腾讯在线表格。业务层零改动：
只需把 config/settings.yaml 的 app.io_adapter 设为 "tencent"。

后端通过 TENCENT_DOC_BACKEND 切换：
    - mcp（默认）：官方托管 MCP，使用 TENCENT_DOCS_TOKEN；
    - openapi：保留原 OpenAPI v3，便于 MCP 故障时人工回退；
    - auto：存在 MCP Token 时用 MCP，否则使用 OpenAPI。

凭证只从**环境变量**读取，绝不写入代码或提交仓库（安全底线）：
      - TENCENT_DOCS_TOKEN        官方 MCP Token（有效期由腾讯文档管理）
      - TENCENT_DOC_ACCESS_TOKEN   访问令牌
      - TENCENT_DOC_CLIENT_ID      应用 ID
      - TENCENT_DOC_OPEN_ID        用户标识
      - TENCENT_DOC_CLIENT_SECRET  应用密钥（可选，与 refresh_token 成对配置）
      - TENCENT_DOC_REFRESH_TOKEN  刷新令牌（可选，官方有效期 1 年）
OpenAPI 配置 Refresh Token 后，Access Token 缺失或鉴权失效时自动刷新并重试一次。

安全设计：
    - SSRF 防护：**硬编码只允许** docs.qq.com，请求前再校验 scheme/host。
    - 所有请求设超时，避免挂起。
    - 返回体 ret/code != 0 抛出明确错误。

MCP 接口：https://docs.qq.com/openapi/mcp

OpenAPI v3 接口（基础域名 https://docs.qq.com）：
    - 查子表列表：GET  /openapi/spreadsheet/v3/files/{fileId}?concise=1
    - 读区域：    GET  /openapi/spreadsheet/v3/files/{fileId}/{sheetId}/{range}
    - 写/批量更新：POST /openapi/spreadsheet/v3/files/{fileId}/batchUpdate
"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from shared.io_adapter.base import ExcelIO

ALLOWED_HOST = "docs.qq.com"
BASE_URL = "https://docs.qq.com"
API_PREFIX = "/openapi/spreadsheet/v3/files"
MCP_ENDPOINT = "https://docs.qq.com/openapi/mcp"
MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT = 30  # 秒

# v3 单次 batchUpdate 操作数上限、区域读取上限（官方约束）
_MAX_BATCH_OPS = 5
# v3 单次 updateRange 约束：行 <= 1000，单元格总数 <= 10000。
_MAX_UPDATE_ROWS = 1000
_MAX_UPDATE_CELLS = 10000
_MCP_MAX_READ_CELLS = 20000
_MCP_WRITE_CHUNK_CELLS = 2000


class TencentDocError(RuntimeError):
    """腾讯文档 API 调用失败（网络、鉴权、业务错误码等）。"""


class TencentDocAdapter(ExcelIO):
    """读写腾讯在线表格。target/source 传文档 fileId（形如 DUkNwTFhJTHJuQ1JD）。"""

    def __init__(
        self,
        backend: str | None = None,
        mcp_token: str | None = None,
        access_token: str | None = None,
        client_id: str | None = None,
        open_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        # 凭证仅来自环境变量，绝不硬编码；构造时不联网，避免无凭证环境导入即失败。
        selected = (backend or os.environ.get("TENCENT_DOC_BACKEND") or "auto").strip().lower()
        self._mcp_token = (
            mcp_token
            or os.environ.get("TENCENT_DOCS_TOKEN")
            or os.environ.get("TENCENT_DOC_MCP_TOKEN")
        )
        if selected == "auto":
            selected = "mcp" if self._mcp_token else "openapi"
        if selected not in {"mcp", "openapi"}:
            raise TencentDocError(
                "TENCENT_DOC_BACKEND 仅支持 mcp、openapi 或 auto"
            )
        self._backend = selected
        self._mcp_endpoint = MCP_ENDPOINT
        self._mcp_session_id: str | None = None
        self._mcp_initialized = False
        self._mcp_request_id = 0
        self._access_token = access_token or os.environ.get("TENCENT_DOC_ACCESS_TOKEN")
        self._client_id = client_id or os.environ.get("TENCENT_DOC_CLIENT_ID")
        self._open_id = open_id or os.environ.get("TENCENT_DOC_OPEN_ID")
        self._client_secret = client_secret or os.environ.get(
            "TENCENT_DOC_CLIENT_SECRET"
        )
        self._refresh_token = refresh_token or os.environ.get(
            "TENCENT_DOC_REFRESH_TOKEN"
        )
        self._timeout = timeout

    # ------------------------------------------------------------------
    # ExcelIO 接口
    # ------------------------------------------------------------------
    def read_sheet(
        self, source: str, sheet: str | None = None, fill_merged: bool = False
    ) -> list[dict]:
        """读取在线表格的一个子表，返回行字典列表（首行为表头）。

        MCP 会返回合并区域；fill_merged=True 时把左上角值填充到整个合并区域。
        OpenAPI v3 已返回展开值，无需额外处理。
        """
        file_id = self._require_file_id(source)
        props = self._list_sheets(file_id)
        if not props:
            return []

        target = self._find_sheet(props, sheet)
        if target is None:
            raise TencentDocError(
                f"在文档 {file_id} 未找到子表 '{sheet}'，现有子表："
                f"{[p.get('title') for p in props]}"
            )

        sheet_id = target["sheetId"]
        row_count = int(target.get("rowCount") or 0)
        col_count = int(target.get("columnCount") or 0)
        used_range = target.get("usedRange")
        if self._backend == "mcp" and isinstance(used_range, dict):
            # MCP 会同时返回网格总尺寸和已用区域；优先只读取有内容的区域，
            # 避免新建表默认的空白行列产生无意义的大请求。
            row_count = min(row_count, int(used_range.get("row_count") or 0))
            col_count = min(col_count, int(used_range.get("col_count") or 0))
        if row_count <= 0 or col_count <= 0:
            return []

        rng = f"A1:{self._col_letter(col_count - 1)}{row_count}"
        grid = self._get_range(file_id, sheet_id, rng)
        if self._backend == "mcp" and fill_merged:
            self._fill_mcp_merged_cells(
                file_id, sheet_id, grid, row_count=row_count, col_count=col_count
            )
        return self._grid_to_rows(grid)

    def write_sheet(
        self,
        target: str,
        rows: list[dict],
        headers: list[str] | None = None,
        sheet: str | None = None,
        auto_filter: bool = False,
        freeze_header: bool = False,
        highlight_rows: set[int] | None = None,
    ) -> None:
        """把行字典列表覆盖写入在线表格；数据超单表容量时自动分页到多个子表。

        OpenAPI v3 的硬限制（已实测确认，无法绕过）：
          - addSheet 单表 rowCount×columnCount <= 10000 且 rowCount <= 10000；
          - **不支持** insertDimension / appendDimension / updateSheet 等扩表请求，
            子表建成后无法再加行/列；
          - updateRange 不自动扩表，写入区域必须落在现有网格内。
        因此当 [表头]+数据 的单元格数超过 10000 时，单个子表装不下，只能把数据
        按行**分页**到多张子表：第 1 页用 sheet 名（缺省 "名单"），后续页用
        "{名}({页码})"。每页 = 表头 + 一段数据行，且行×列 <= 10000。

        OpenAPI 每次写入都把目标子表删表重建到精确尺寸；MCP 后端原地清空并扩缩
        到精确尺寸，保留子表身份并降低重建失败造成数据丢失的风险。两者都会清理
        上一次多出来的分页子表。

        auto_filter / freeze_header：MCP 后端支持；OpenAPI v3 忽略（数据照写）。
        highlight_rows: 需要红色字体+浅绿背景的数据行索引集合（0-based，不含表头行）。
        """
        file_id = self._require_file_id(target)
        title = sheet or "名单"

        if headers is None:
            headers = list(rows[0].keys()) if rows else []

        need_cols = max(len(headers), 1)
        header_row = [self._cell(h) for h in headers] if headers else None

        _highlight = highlight_rows or set()
        # 内部仍使用 v3 的 RGBA 格式；MCP 写入时转换为 ARGB 字符串。
        _highlight_fmt = {"fontColor": {"red": 255, "green": 0, "blue": 0, "alpha": 255}}
        data_rows = [
            [self._cell(row.get(h), _highlight_fmt if idx in _highlight else None)
             for h in headers]
            for idx, row in enumerate(rows)
        ]

        # 每页容量：受 addSheet 单表单元格上限约束，行数（含表头）<= 10000/列数。
        rows_cap = max(_MAX_UPDATE_CELLS // need_cols, 1)
        data_per_page = max(rows_cap - (1 if header_row else 0), 1)

        if data_rows:
            pages = [
                data_rows[i:i + data_per_page]
                for i in range(0, len(data_rows), data_per_page)
            ]
        else:
            pages = [[]]  # 无数据也建一张（仅表头/空表）

        for idx, page in enumerate(pages):
            page_title = title if idx == 0 else f"{title}({idx + 1})"
            page_matrix = ([header_row] if header_row else []) + page
            page_rows = max(len(page_matrix), 1)
            props = self._list_sheets(file_id)
            existing = self._find_sheet(props, page_title)
            if existing is not None:
                sheet_id = self._recreate_sheet(
                    file_id, existing["sheetId"], page_title, page_rows, need_cols
                )
            else:
                sheet_id = self._add_sheet(
                    file_id, page_title,
                    row_count=page_rows, col_count=need_cols,
                )
            self._write_range(file_id, sheet_id, page_matrix)
            if self._backend == "mcp" and freeze_header and header_row:
                self._mcp_call(
                    "sheet.set_freeze",
                    {
                        "file_id": file_id,
                        "sheet_id": sheet_id,
                        "row_count": 1,
                        "col_count": 0,
                    },
                )
            if self._backend == "mcp" and auto_filter and header_row:
                self._mcp_call(
                    "sheet.set_filter",
                    {
                        "file_id": file_id,
                        "sheet_id": sheet_id,
                        "start_row": 0,
                        "start_col": 0,
                        "end_row": page_rows - 1,
                        "end_col": need_cols - 1,
                    },
                )

        # 清理上一次遗留的多余分页子表（本次页数变少时）。
        stale_idx = len(pages) + 1
        while True:
            stale_title = f"{title}({stale_idx})"
            stale = self._find_sheet(self._list_sheets(file_id), stale_title)
            if stale is None:
                break
            self._batch_update(
                file_id, [{"deleteSheetRequest": {"sheetId": stale["sheetId"]}}]
            )
            stale_idx += 1

    # ------------------------------------------------------------------
    # v3 接口封装
    # ------------------------------------------------------------------
    def _list_sheets(self, file_id: str) -> list[dict]:
        """查子表列表，返回 properties[]（含 sheetId/title/rowCount/columnCount）。

        注意：不能带 concise=1。精简模式下腾讯不返回 rowCount/columnCount（恒为 0），
        会导致 read_sheet 误判为空表而读到 0 行（数据全丢）。这里读完整属性以拿到
        真实网格尺寸。
        """
        if self._backend == "mcp":
            data = self._mcp_call("sheet.get_sheet_info", {"file_id": file_id})
            return [
                {
                    "sheetId": item.get("sheet_id"),
                    "title": item.get("sheet_name"),
                    "rowCount": int(item.get("row_count") or 0),
                    "columnCount": int(item.get("col_count") or 0),
                    "sheetType": item.get("sheet_type"),
                    "usedRange": item.get("used_range"),
                }
                for item in (data.get("sheets") or [])
                if isinstance(item, dict) and item.get("sheet_id")
            ]

        data = self._request(
            "GET", f"{API_PREFIX}/{quote(file_id, safe='')}"
        )
        payload = data.get("data", data)
        return payload.get("properties", []) or []

    def _get_range(self, file_id: str, sheet_id: str, rng: str) -> dict:
        """读取区域，返回 gridData。"""
        if self._backend == "mcp":
            start_row, start_col, end_row, end_col = self._parse_a1_range(rng)
            total_cols = end_col - start_col + 1
            rows_per_chunk = max(_MCP_MAX_READ_CELLS // max(total_cols, 1), 1)
            height = end_row - start_row + 1
            width = total_cols
            matrix: list[list[dict]] = [
                [{} for _ in range(width)] for _ in range(height)
            ]
            for chunk_start in range(start_row, end_row + 1, rows_per_chunk):
                chunk_end = min(chunk_start + rows_per_chunk - 1, end_row)
                data = self._mcp_call(
                    "sheet.get_cell_data",
                    {
                        "file_id": file_id,
                        "sheet_id": sheet_id,
                        "start_row": chunk_start,
                        "start_col": start_col,
                        "end_row": chunk_end,
                        "end_col": end_col,
                        "return_csv": False,
                    },
                )
                for cell in data.get("cells") or []:
                    if not isinstance(cell, dict):
                        continue
                    row = int(cell.get("row", -1)) - start_row
                    col = int(cell.get("col", -1)) - start_col
                    if 0 <= row < height and 0 <= col < width:
                        matrix[row][col] = self._mcp_cell_to_legacy(cell)
            return {"rows": [{"values": row} for row in matrix]}

        path = (
            f"{API_PREFIX}/{quote(file_id, safe='')}"
            f"/{quote(sheet_id, safe='')}/{quote(rng, safe=':')}"
        )
        data = self._request("GET", path)
        payload = data.get("data", data)
        return payload.get("gridData", {}) or {}

    def _add_sheet(
        self,
        file_id: str,
        title: str,
        row_count: int | None = None,
        col_count: int | None = None,
    ) -> str:
        """新建子表，返回新 sheetId。

        row_count/col_count 缺省时走腾讯默认（200 行 / 20 列）；数据量较大时应
        显式指定，否则 updateRange 会因超出默认尺寸报 400001。
        """
        if self._backend == "mcp":
            self._mcp_call(
                "sheet.add_sheet",
                {"file_id": file_id, "name": title, "append_index": True},
            )
            sheet = self._find_sheet(self._list_sheets(file_id), title)
            if sheet is None:
                raise TencentDocError(f"新建子表 '{title}' 后未能取得 sheetId")
            self._resize_mcp_sheet(
                file_id,
                sheet["sheetId"],
                row_count=max(int(row_count or sheet.get("rowCount") or 1), 1),
                col_count=max(int(col_count or sheet.get("columnCount") or 1), 1),
            )
            return sheet["sheetId"]

        add_req: dict = {"title": title}
        if row_count is not None:
            add_req["rowCount"] = int(row_count)
        if col_count is not None:
            add_req["columnCount"] = int(col_count)
        resp = self._batch_update(file_id, [{"addSheetRequest": add_req}])
        # 优先从回包解析新 sheetId
        sheet_id = self._extract_added_sheet_id(resp)
        if sheet_id:
            return sheet_id
        # 兜底：重新查列表按标题找
        for p in self._list_sheets(file_id):
            if p.get("title") == title:
                return p["sheetId"]
        raise TencentDocError(f"新建子表 '{title}' 后未能取得 sheetId")

    def _recreate_sheet(
        self, file_id: str, old_sheet_id: str, title: str,
        row_count: int, col_count: int,
    ) -> str:
        """删除旧子表并以精确尺寸重建，返回新 sheetId。

        用于现有子表行/列不足而 v3 又无插入维度能力的场景。删除与新增放在
        **同一批次顺序执行**，先删后建同名，避免中途出现同名冲突。
        注意：v3 约束不能删光文档全部子表（至少保留一个），本项目"总表+多个
        分表"的结构不会触发该边界。
        """
        if self._backend == "mcp":
            props = self._list_sheets(file_id)
            current = next(
                (item for item in props if item.get("sheetId") == old_sheet_id),
                None,
            )
            if current is None:
                raise TencentDocError(f"MCP 覆盖前未找到子表 {old_sheet_id}")
            current_rows = max(int(current.get("rowCount") or 0), 1)
            current_cols = max(int(current.get("columnCount") or 0), 1)
            self._mcp_call(
                "sheet.clear_range_cells",
                {
                    "file_id": file_id,
                    "sheet_id": old_sheet_id,
                    "start_row": 0,
                    "start_col": 0,
                    "end_row": current_rows - 1,
                    "end_col": current_cols - 1,
                },
            )
            self._resize_mcp_sheet(
                file_id,
                old_sheet_id,
                row_count=max(int(row_count), 1),
                col_count=max(int(col_count), 1),
            )
            return old_sheet_id

        resp = self._batch_update(
            file_id,
            [
                {"deleteSheetRequest": {"sheetId": old_sheet_id}},
                {
                    "addSheetRequest": {
                        "title": title,
                        "rowCount": int(row_count),
                        "columnCount": int(col_count),
                    }
                },
            ],
        )
        sheet_id = self._extract_added_sheet_id(resp)
        if sheet_id:
            return sheet_id
        for p in self._list_sheets(file_id):
            if p.get("title") == title:
                return p["sheetId"]
        raise TencentDocError(f"重建子表 '{title}' 后未能取得 sheetId")

    def _write_range(
        self, file_id: str, sheet_id: str, matrix: list[list[dict]]
    ) -> None:
        """从 (0,0) 起把 matrix 写入子表；按 v3 上限自动分片。matrix 为空则不发请求。

        v3 updateRange 单次约束：行 <= 1000 且单元格总数 <= 10000。列较多时
        （如 8 列 × 1000 行 = 8000... 甚至更宽）单元格数会先触顶，故这里按
        "每片行数 = min(1000, floor(10000/列数))" 切片，逐片按 startRow 偏移写入。
        """
        if not matrix:
            return

        if self._backend == "mcp":
            self._mcp_write_matrix(file_id, sheet_id, matrix, 0, 0)
            return

        cols = max((len(line) for line in matrix), default=1) or 1
        # 每片最多多少行：受行上限与单元格上限双重约束，至少 1 行。
        rows_per_chunk = min(_MAX_UPDATE_ROWS, max(_MAX_UPDATE_CELLS // cols, 1))

        for start in range(0, len(matrix), rows_per_chunk):
            chunk = matrix[start:start + rows_per_chunk]
            self._batch_update(
                file_id,
                [
                    {
                        "updateRangeRequest": {
                            "sheetId": sheet_id,
                            "gridData": {
                                "startRow": start,
                                "startColumn": 0,
                                "rows": [{"values": line} for line in chunk],
                            },
                        }
                    }
                ],
            )

    def _batch_update(self, file_id: str, requests: list[dict]) -> dict:
        """批量更新。requests 长度受 v3 单次 <= 5 约束。"""
        if len(requests) > _MAX_BATCH_OPS:
            raise TencentDocError(
                f"单次 batchUpdate 操作数 {len(requests)} 超过上限 {_MAX_BATCH_OPS}"
            )
        if self._backend == "mcp":
            replies: list[dict] = []
            for request in requests:
                if "deleteSheetRequest" in request:
                    sheet_id = request["deleteSheetRequest"]["sheetId"]
                    self._mcp_call(
                        "sheet.delete_sheet",
                        {"file_id": file_id, "sheet_id": sheet_id},
                    )
                    replies.append({})
                    continue
                if "addSheetRequest" in request:
                    item = request["addSheetRequest"]
                    sheet_id = self._add_sheet(
                        file_id,
                        item["title"],
                        row_count=item.get("rowCount"),
                        col_count=item.get("columnCount"),
                    )
                    replies.append({"addSheetResponse": {"sheetId": sheet_id}})
                    continue
                if "updateRangeRequest" in request:
                    item = request["updateRangeRequest"]
                    grid = item.get("gridData") or {}
                    matrix = [
                        row.get("values") or []
                        for row in (grid.get("rows") or [])
                        if isinstance(row, dict)
                    ]
                    self._mcp_write_matrix(
                        file_id,
                        item["sheetId"],
                        matrix,
                        int(grid.get("startRow") or 0),
                        int(grid.get("startColumn") or 0),
                    )
                    replies.append({})
                    continue
                raise TencentDocError(
                    f"MCP 后端不支持 batchUpdate 请求：{list(request)}"
                )
            return {"data": {"replies": replies}}

        return self._request(
            "POST",
            f"{API_PREFIX}/{quote(file_id, safe='')}/batchUpdate",
            body={"requests": requests},
        )

    # ------------------------------------------------------------------
    # 官方 MCP 封装
    # ------------------------------------------------------------------
    def _mcp_call(self, tool_name: str, arguments: dict) -> dict:
        """调用腾讯文档 MCP Tool，返回结构化结果。"""
        if self._backend != "mcp":
            raise TencentDocError("当前腾讯文档后端不是 MCP")
        if not self._mcp_token:
            raise TencentDocError(
                "缺少腾讯文档 MCP Token，请设置 TENCENT_DOCS_TOKEN；"
                "如需临时回退，请设置 TENCENT_DOC_BACKEND=openapi。"
            )

        if not self._mcp_initialized:
            response = self._mcp_post(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_mcp_request_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "sky-admin",
                            "version": "1.0",
                        },
                    },
                }
            )
            self._raise_mcp_rpc_error(response, "initialize")
            self._mcp_post(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
            self._mcp_initialized = True

        response = self._mcp_post(
            {
                "jsonrpc": "2.0",
                "id": self._next_mcp_request_id(),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )
        self._raise_mcp_rpc_error(response, tool_name)
        result = response.get("result") or {}
        if result.get("isError"):
            detail = self._mcp_content_text(result) or "未知工具错误"
            raise TencentDocError(f"腾讯文档 MCP 工具 {tool_name} 失败：{detail}")

        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            data = structured
        else:
            text = self._mcp_content_text(result)
            if not text:
                data = {}
            else:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise TencentDocError(
                        f"腾讯文档 MCP 工具 {tool_name} 返回非 JSON 文本"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise TencentDocError(
                        f"腾讯文档 MCP 工具 {tool_name} 返回结构异常"
                    )
                data = parsed

        error = data.get("error")
        if error:
            raise TencentDocError(f"腾讯文档 MCP 工具 {tool_name} 失败：{error}")
        return data

    def _mcp_post(self, payload: dict) -> dict:
        """发送一次 Streamable HTTP JSON-RPC 请求。"""
        parsed = urlparse(self._mcp_endpoint)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise TencentDocError(f"非法请求目标，仅允许 https://{ALLOWED_HOST}")

        headers = {
            "Authorization": self._mcp_token or "",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "User-Agent": "sky-admin-tencent-docs-mcp/1.0",
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        request = Request(
            self._mcp_endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                response_headers = getattr(response, "headers", None)
                if response_headers is not None:
                    session_id = response_headers.get("Mcp-Session-Id")
                    if session_id:
                        self._mcp_session_id = session_id
                    content_type = response_headers.get("Content-Type", "")
                else:
                    content_type = "application/json"
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 401:
                raise TencentDocError(
                    "腾讯文档 MCP Token 无效或已过期；请重置 TENCENT_DOCS_TOKEN，"
                    "或设置 TENCENT_DOC_BACKEND=openapi 临时回退。"
                ) from exc
            if exc.code == 429:
                raise TencentDocError("腾讯文档 MCP 已达到调用频率限制") from exc
            raise TencentDocError(
                f"腾讯文档 MCP 返回 HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", str(exc))
            raise TencentDocError(f"请求腾讯文档 MCP 失败：{reason}") from exc

        if not raw.strip():
            return {}
        try:
            if "text/event-stream" in content_type:
                messages = []
                for line in raw.splitlines():
                    if line.startswith("data:") and line[5:].strip():
                        messages.append(json.loads(line[5:].strip()))
                return messages[-1] if messages else {}
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TencentDocError("腾讯文档 MCP 响应不是合法 JSON") from exc

    def _next_mcp_request_id(self) -> int:
        self._mcp_request_id += 1
        return self._mcp_request_id

    @staticmethod
    def _raise_mcp_rpc_error(response: dict, operation: str) -> None:
        error = response.get("error") if isinstance(response, dict) else None
        if error:
            if isinstance(error, dict):
                code = error.get("code", "")
                message = error.get("message", "")
                detail = f"{code} {message}".strip()
            else:
                detail = str(error)
            raise TencentDocError(
                f"腾讯文档 MCP {operation} 调用失败：{detail}"
            )

    @staticmethod
    def _mcp_content_text(result: dict) -> str:
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text") or "")
        return ""

    def _resize_mcp_sheet(
        self, file_id: str, sheet_id: str, row_count: int, col_count: int
    ) -> None:
        sheet = next(
            (
                item
                for item in self._list_sheets(file_id)
                if item.get("sheetId") == sheet_id
            ),
            None,
        )
        if sheet is None:
            raise TencentDocError(f"MCP 扩缩表前未找到子表 {sheet_id}")

        current_rows = int(sheet.get("rowCount") or 0)
        current_cols = int(sheet.get("columnCount") or 0)
        for dimension, current, target in (
            ("row", current_rows, max(row_count, 1)),
            ("col", current_cols, max(col_count, 1)),
        ):
            if current < target:
                self._mcp_call(
                    "sheet.insert_dimension",
                    {
                        "file_id": file_id,
                        "sheet_id": sheet_id,
                        "dimension_type": dimension,
                        "index": max(current - 1, 0),
                        "direction": "after",
                        "count": target - current,
                    },
                )
            elif current > target:
                self._mcp_call(
                    "sheet.delete_dimension",
                    {
                        "file_id": file_id,
                        "sheet_id": sheet_id,
                        "dimension_type": dimension,
                        "index": target,
                        "count": current - target,
                    },
                )

    def _mcp_write_matrix(
        self,
        file_id: str,
        sheet_id: str,
        matrix: list[list[dict]],
        start_row: int,
        start_col: int,
    ) -> None:
        values: list[dict] = []
        style_runs: list[tuple[int, int, int, dict]] = []
        for row_offset, row in enumerate(matrix):
            run_start: int | None = None
            run_style: dict | None = None
            for col_offset, cell in enumerate(row):
                values.append(
                    self._legacy_cell_to_mcp(
                        cell,
                        row=start_row + row_offset,
                        col=start_col + col_offset,
                    )
                )
                style = self._legacy_format_to_mcp(cell.get("cellFormat"))
                if style != run_style:
                    if run_style is not None and run_start is not None:
                        style_runs.append(
                            (
                                start_row + row_offset,
                                start_col + run_start,
                                start_col + col_offset - 1,
                                run_style,
                            )
                        )
                    run_start = col_offset if style is not None else None
                    run_style = style
            if run_style is not None and run_start is not None:
                style_runs.append(
                    (
                        start_row + row_offset,
                        start_col + run_start,
                        start_col + len(row) - 1,
                        run_style,
                    )
                )

        for offset in range(0, len(values), _MCP_WRITE_CHUNK_CELLS):
            self._mcp_call(
                "sheet.set_range_value",
                {
                    "file_id": file_id,
                    "sheet_id": sheet_id,
                    "values": values[offset:offset + _MCP_WRITE_CHUNK_CELLS],
                },
            )

        for row, first_col, last_col, style in style_runs:
            self._mcp_call(
                "sheet.set_cell_style",
                {
                    "file_id": file_id,
                    "sheet_id": sheet_id,
                    "start_row": row,
                    "end_row": row,
                    "start_col": first_col,
                    "end_col": last_col,
                    **style,
                },
            )

    @staticmethod
    def _legacy_cell_to_mcp(cell: dict, row: int, col: int) -> dict:
        value = cell.get("cellValue", cell) if isinstance(cell, dict) else {}
        entry: dict = {"row": row, "col": col}
        if isinstance(value, dict) and value.get("number") is not None:
            entry.update(value_type="NUMBER", number_value=value["number"])
        elif isinstance(value, dict) and value.get("bool") is not None:
            entry.update(value_type="BOOL", bool_value=bool(value["bool"]))
        else:
            text = ""
            if isinstance(value, dict):
                if value.get("text") is not None:
                    text = str(value["text"])
                elif isinstance(value.get("link"), dict):
                    text = str(value["link"].get("text") or "")
            entry.update(value_type="STRING", string_value=text)
        return entry

    @classmethod
    def _legacy_format_to_mcp(cls, cell_format: dict | None) -> dict | None:
        if not isinstance(cell_format, dict):
            return None
        text_format = cell_format.get("textFormat") or {}
        result: dict = {}
        if "bold" in text_format:
            result["bold"] = bool(text_format["bold"])
        color = text_format.get("color")
        if isinstance(color, dict):
            result["font_color"] = cls._rgba_to_argb(color)
        return result or None

    @staticmethod
    def _rgba_to_argb(color: dict) -> str:
        def channel(name: str, default: int) -> int:
            value = int(color.get(name, default))
            return max(0, min(value, 255))

        return "{:02X}{:02X}{:02X}{:02X}".format(
            channel("alpha", 255),
            channel("red", 0),
            channel("green", 0),
            channel("blue", 0),
        )

    @staticmethod
    def _mcp_cell_to_legacy(cell: dict) -> dict:
        value_type = str(cell.get("value_type") or "").upper()
        if value_type == "NUMBER" and cell.get("number_value") is not None:
            return {"cellValue": {"number": cell["number_value"]}}
        if value_type == "BOOL" and cell.get("bool_value") is not None:
            return {"cellValue": {"text": "是" if cell["bool_value"] else "否"}}
        if cell.get("string_value") is not None:
            return {"cellValue": {"text": str(cell["string_value"])}}
        if cell.get("formula") is not None:
            return {"cellValue": {"text": str(cell["formula"])}}
        return {"cellValue": {"text": ""}}

    def _fill_mcp_merged_cells(
        self,
        file_id: str,
        sheet_id: str,
        grid: dict,
        row_count: int,
        col_count: int,
    ) -> None:
        data = self._mcp_call(
            "sheet.get_merged_cells",
            {
                "file_id": file_id,
                "sheet_id": sheet_id,
                "start_row": 0,
                "start_col": 0,
                "end_row": row_count - 1,
                "end_col": col_count - 1,
            },
        )
        rows = grid.get("rows") or []
        for merged in data.get("merged_cells") or []:
            try:
                cell_range = str(merged).split("$", 1)[-1]
                start_row, start_col, end_row, end_col = self._parse_a1_range(
                    cell_range
                )
                source = rows[start_row]["values"][start_col]
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            for row in range(start_row, min(end_row + 1, len(rows))):
                values = rows[row].get("values") or []
                for col in range(start_col, min(end_col + 1, len(values))):
                    values[col] = deepcopy(source)

    @classmethod
    def _parse_a1_range(cls, value: str) -> tuple[int, int, int, int]:
        raw = value.split("$", 1)[-1].replace("$", "").upper()
        parts = raw.split(":", 1)
        if len(parts) == 1:
            parts.append(parts[0])
        start = cls._parse_a1_cell(parts[0])
        end = cls._parse_a1_cell(parts[1])
        return start[0], start[1], end[0], end[1]

    @staticmethod
    def _parse_a1_cell(value: str) -> tuple[int, int]:
        match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", value.strip().upper())
        if not match:
            raise ValueError(f"非法 A1 单元格：{value}")
        col = 0
        for char in match.group(1):
            col = col * 26 + ord(char) - 64
        return int(match.group(2)) - 1, col - 1

    # ------------------------------------------------------------------
    # HTTP 与解析工具
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        query: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        if not (self._client_id and self._open_id):
            raise TencentDocError(
                "缺少腾讯文档凭证，请先设置 TENCENT_DOC_CLIENT_ID / "
                "TENCENT_DOC_OPEN_ID（切勿硬编码）。"
            )
        if not self._access_token:
            if self._can_refresh_token():
                self._refresh_access_token()
            else:
                raise TencentDocError(
                    "缺少腾讯文档 Access Token；请设置 TENCENT_DOC_ACCESS_TOKEN，"
                    "或同时设置 TENCENT_DOC_CLIENT_SECRET / "
                    "TENCENT_DOC_REFRESH_TOKEN 以自动刷新。"
                )

        url = f"{BASE_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        # SSRF 兜底校验：即便 BASE_URL 固定，也再确认 scheme/host 合法
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise TencentDocError(f"非法请求目标，仅允许 https://{ALLOWED_HOST}")

        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        for attempt in range(2):
            headers = {
                "Access-Token": self._access_token,
                "Client-Id": self._client_id,
                "Open-Id": self._open_id,
                "Accept": "application/json",
            }
            if body is not None:
                headers["Content-Type"] = "application/json"

            req = Request(url, data=data_bytes, headers=headers, method=method)
            try:
                with urlopen(req, timeout=self._timeout) as resp:
                    raw = resp.read().decode("utf-8")
            except HTTPError as e:
                if e.code == 401 and attempt == 0 and self._can_refresh_token():
                    self._refresh_access_token()
                    continue
                detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
                raise TencentDocError(
                    f"腾讯文档 API 返回 HTTP {e.code}: {detail}"
                ) from e
            except URLError as e:
                raise TencentDocError(f"请求腾讯文档 API 失败：{e.reason}") from e

            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise TencentDocError("腾讯文档 API 响应不是合法 JSON") from e

            if (
                self._is_auth_error(data)
                and attempt == 0
                and self._can_refresh_token()
            ):
                self._refresh_access_token()
                continue
            self._check_business_error(data)
            return data

        raise TencentDocError("腾讯文档 Access Token 刷新后仍未通过鉴权")

    def _can_refresh_token(self) -> bool:
        return bool(
            self._client_id and self._client_secret and self._refresh_token
        )

    def _refresh_access_token(self) -> None:
        """使用官方 OAuth refresh_token 流程刷新内存中的 Access Token。"""
        if not self._can_refresh_token():
            raise TencentDocError(
                "自动刷新需要 TENCENT_DOC_CLIENT_ID / "
                "TENCENT_DOC_CLIENT_SECRET / TENCENT_DOC_REFRESH_TOKEN"
            )

        query = urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }
        )
        url = f"{BASE_URL}/oauth/v2/token?{query}"
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise TencentDocError(f"非法请求目标，仅允许 https://{ALLOWED_HOST}")

        req = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
            raise TencentDocError(
                f"刷新腾讯文档 Access Token 失败：HTTP {e.code}"
            ) from e
        except URLError as e:
            raise TencentDocError(
                f"刷新腾讯文档 Access Token 失败：{e.reason}"
            ) from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise TencentDocError("腾讯文档刷新 Token 响应不是合法 JSON") from e
        self._check_business_error(data)

        access_token = data.get("access_token")
        if not access_token:
            raise TencentDocError("腾讯文档刷新 Token 响应缺少 access_token")
        self._access_token = access_token
        if data.get("user_id"):
            self._open_id = data["user_id"]

    @staticmethod
    def _is_auth_error(data: dict) -> bool:
        return str(data.get("code")) == "400006"

    @staticmethod
    def _check_business_error(data: dict) -> None:
        """腾讯风格业务错误码：ret/code 非 0 视为失败。"""
        for key in ("ret", "code"):
            if key in data and data[key] not in (0, "0", None):
                msg = data.get("msg") or data.get("message") or ""
                raise TencentDocError(
                    f"腾讯文档 API 业务错误 {key}={data[key]}: {msg}"
                )

    @staticmethod
    def _require_file_id(value: str) -> str:
        if not value or not value.strip():
            raise TencentDocError("腾讯文档 fileId 不能为空")
        return value.strip()

    @staticmethod
    def _find_sheet(props: list[dict], title: str | None) -> dict | None:
        """按标题找子表；title 为空时取第一个子表。"""
        if not props:
            return None
        if title is None:
            return props[0]
        for p in props:
            if p.get("title") == title:
                return p
        return None

    @staticmethod
    def _extract_added_sheet_id(resp: dict) -> str | None:
        """从 batchUpdate 回包里解析 addSheet 返回的新 sheetId（防御式）。"""
        payload = resp.get("data", resp)
        replies = payload.get("replies") or payload.get("responses") or []
        for r in replies:
            if not isinstance(r, dict):
                continue
            for k in ("addSheet", "addSheetResponse", "addSheetRequest"):
                node = r.get(k)
                if isinstance(node, dict):
                    sid = node.get("sheetId") or (
                        node.get("properties", {}) or {}
                    ).get("sheetId")
                    if sid:
                        return sid
        return None

    # ------------------------------------------------------------------
    # 值编解码
    # ------------------------------------------------------------------
    @staticmethod
    def _cell(value, fmt: dict | None = None) -> dict:
        """单元格值 -> cellValue：数字用 number，其余转文本。

        可选 fmt 字典设置 cellFormat（腾讯文档 v3 格式）：
          - {"fontColor": {"red":255,"green":0,"blue":0,"alpha":255}}
            字体颜色（RGBA）
          - {"bold": True}
            加粗
        注意：v3 API 不支持单元格背景填充色（fill/backgroundColor）。
        """
        if value is None:
            entry = {"cellValue": {"text": ""}}
        elif isinstance(value, bool):
            entry = {"cellValue": {"text": "是" if value else "否"}}
        elif isinstance(value, (int, float)):
            entry = {"cellValue": {"number": value}}
        else:
            entry = {"cellValue": {"text": str(value)}}

        if fmt:
            text_format: dict = {}
            if "fontColor" in fmt:
                text_format["color"] = fmt["fontColor"]
            if "bold" in fmt:
                text_format["bold"] = fmt["bold"]
            if text_format:
                entry["cellFormat"] = {"textFormat": text_format}

        return entry

    def _grid_to_rows(self, grid: dict) -> list[dict]:
        """gridData -> 行字典列表（首行表头，跳过全空行）。"""
        raw_rows = grid.get("rows") or []
        if not raw_rows:
            return []

        parsed: list[list] = []
        for r in raw_rows:
            values = r.get("values") if isinstance(r, dict) else None
            parsed.append([self._read_cell(v) for v in (values or [])])

        header_cells = parsed[0]
        headers = [
            (str(h).strip() if h not in (None, "") else f"col{i}")
            for i, h in enumerate(header_cells)
        ]
        result: list[dict] = []
        for raw in parsed[1:]:
            if all(v is None or str(v).strip() == "" for v in raw):
                continue
            row = {}
            for i, header in enumerate(headers):
                row[header] = raw[i] if i < len(raw) else None
            result.append(row)
        return result

    @staticmethod
    def _read_cell(value: dict):
        """cellValue -> Python 值（text / number / link.text）。"""
        if not isinstance(value, dict):
            return None
        cell = value.get("cellValue", value)
        if not isinstance(cell, dict):
            return None
        if "number" in cell and cell["number"] is not None:
            return cell["number"]
        if "text" in cell and cell["text"] is not None:
            return cell["text"]
        link = cell.get("link")
        if isinstance(link, dict):
            return link.get("text")
        return None

    @staticmethod
    def _col_letter(idx0: int) -> str:
        """0 基列索引 -> A1 列字母（0->A, 25->Z, 26->AA）。"""
        n = idx0 + 1
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s
