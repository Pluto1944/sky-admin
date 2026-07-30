"""腾讯文档在线表格适配器（OpenAPI v3）。

实现 ExcelIO 抽象，把"行字典列表"读写到腾讯在线表格。业务层零改动：
只需把 shared/config/common.py 的 IO_ADAPTER 切为 "tencent"。

鉴权（B 方案 · 调试 token）：
    凭证只从**环境变量**读取，绝不写入代码或提交仓库（安全底线）：
      - TENCENT_DOC_ACCESS_TOKEN   访问令牌（约 30 天）
      - TENCENT_DOC_CLIENT_ID      应用 ID
      - TENCENT_DOC_OPEN_ID        用户标识
    因当前无 client_secret / refresh_token，**不做自动刷新**；token 过期后回
    开放平台"开发者信息"复制新 token 重新 export 即可。

安全设计：
    - SSRF 防护：**硬编码只允许** docs.qq.com，请求前再校验 scheme/host。
    - 所有请求设超时，避免挂起。
    - 返回体 ret/code != 0 抛出明确错误。

接口（v3，基础域名 https://docs.qq.com）：
    - 查子表列表：GET  /openapi/spreadsheet/v3/files/{fileId}?concise=1
    - 读区域：    GET  /openapi/spreadsheet/v3/files/{fileId}/{sheetId}/{range}
    - 写/批量更新：POST /openapi/spreadsheet/v3/files/{fileId}/batchUpdate
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from shared.io_adapter.base import ExcelIO

ALLOWED_HOST = "docs.qq.com"
BASE_URL = "https://docs.qq.com"
API_PREFIX = "/openapi/spreadsheet/v3/files"
DEFAULT_TIMEOUT = 30  # 秒

# v3 单次 batchUpdate 操作数上限、区域读取上限（官方约束）
_MAX_BATCH_OPS = 5
# v3 单次 updateRange 约束：行 <= 1000，单元格总数 <= 10000。
_MAX_UPDATE_ROWS = 1000
_MAX_UPDATE_CELLS = 10000


class TencentDocError(RuntimeError):
    """腾讯文档 API 调用失败（网络、鉴权、业务错误码等）。"""


class TencentDocAdapter(ExcelIO):
    """读写腾讯在线表格。target/source 传文档 fileId（形如 DUkNwTFhJTHJuQ1JD）。"""

    def __init__(
        self,
        access_token: str | None = None,
        client_id: str | None = None,
        open_id: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        # 凭证仅来自环境变量，绝不硬编码；构造时不强制读取，避免无凭证环境导入即失败
        self._access_token = access_token or os.environ.get("TENCENT_DOC_ACCESS_TOKEN")
        self._client_id = client_id or os.environ.get("TENCENT_DOC_CLIENT_ID")
        self._open_id = open_id or os.environ.get("TENCENT_DOC_OPEN_ID")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # ExcelIO 接口
    # ------------------------------------------------------------------
    def read_sheet(
        self, source: str, sheet: str | None = None, fill_merged: bool = False
    ) -> list[dict]:
        """读取在线表格的一个子表，返回行字典列表（首行为表头）。

        fill_merged 对在线表格不适用（v3 区域读取已返回展开值），此处忽略。
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
        if row_count <= 0 or col_count <= 0:
            return []

        rng = f"A1:{self._col_letter(col_count - 1)}{row_count}"
        grid = self._get_range(file_id, sheet_id, rng)
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

        v3 的硬限制（已实测确认，无法绕过）：
          - addSheet 单表 rowCount×columnCount <= 10000 且 rowCount <= 10000；
          - **不支持** insertDimension / appendDimension / updateSheet 等扩表请求，
            子表建成后无法再加行/列；
          - updateRange 不自动扩表，写入区域必须落在现有网格内。
        因此当 [表头]+数据 的单元格数超过 10000 时，单个子表装不下，只能把数据
        按行**分页**到多张子表：第 1 页用 sheet 名（缺省 "名单"），后续页用
        "{名}({页码})"。每页 = 表头 + 一段数据行，且行×列 <= 10000。

        每次写入都把目标子表**删表重建到精确尺寸**（幂等、无旧数据残留），并清理
        上一次多出来的分页子表。

        auto_filter / freeze_header：v3 无对应能力，忽略（数据照写）。
        highlight_rows: 需要红色字体+浅绿背景的数据行索引集合（0-based，不含表头行）。
        """
        file_id = self._require_file_id(target)
        title = sheet or "名单"

        if headers is None:
            headers = list(rows[0].keys()) if rows else []

        need_cols = max(len(headers), 1)
        header_row = [self._cell(h) for h in headers] if headers else None

        _highlight = highlight_rows or set()
        # 腾讯文档 v3 字体颜色用 RGBA 对象；v3 不支持背景填充色
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
        data = self._request(
            "GET", f"{API_PREFIX}/{quote(file_id, safe='')}"
        )
        payload = data.get("data", data)
        return payload.get("properties", []) or []

    def _get_range(self, file_id: str, sheet_id: str, rng: str) -> dict:
        """读取区域，返回 gridData。"""
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
        return self._request(
            "POST",
            f"{API_PREFIX}/{quote(file_id, safe='')}/batchUpdate",
            body={"requests": requests},
        )

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
        if not (self._access_token and self._client_id and self._open_id):
            raise TencentDocError(
                "缺少腾讯文档凭证，请先设置环境变量 TENCENT_DOC_ACCESS_TOKEN / "
                "TENCENT_DOC_CLIENT_ID / TENCENT_DOC_OPEN_ID（切勿硬编码）。"
            )

        url = f"{BASE_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        # SSRF 兜底校验：即便 BASE_URL 固定，也再确认 scheme/host 合法
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise TencentDocError(f"非法请求目标，仅允许 https://{ALLOWED_HOST}")

        headers = {
            "Access-Token": self._access_token,
            "Client-Id": self._client_id,
            "Open-Id": self._open_id,
            "Accept": "application/json",
        }
        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
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

        self._check_business_error(data)
        return data

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
