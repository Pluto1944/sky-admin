"""player 模块 · 玩家档案导出到表格（本地 xlsx / 腾讯在线文档）。

职责：把 accounts 表数据经 PlayerService 取出，按需筛选、排序后，通过 ExcelIO
写出到表格的一个 sheet。与 LeagueArranger.arrange_and_export 同构——业务层只依赖
ExcelIO 抽象，本地/腾讯适配器靠 config.IO_ADAPTER 切换，本类零改动。

筛选/排序双管齐下：
- 导出期（本类）：按 status / membership_status 过滤、按任意列排序，产出确定视图。
- 交互式（写出时开 auto_filter + freeze_header）：阅读者在文档里可直接按列筛选/排序。

单向写出：只从库导出到文档，不回读（读入库仍走报名/战绩导入链路）。
"""
from __future__ import annotations

from modules.player.config import (
    PLAYER_EXPORT_COLUMNS,
    PLAYER_EXPORT_DEFAULT_DESC,
    PLAYER_EXPORT_DEFAULT_SORT,
    PLAYER_EXPORT_SHEET,
)
from modules.player.service import PlayerService
from shared.io_adapter.base import ExcelIO


class PlayerExporter:
    def __init__(self, player_service: PlayerService, excel_io: ExcelIO):
        self.player_service = player_service
        self.excel_io = excel_io

    @staticmethod
    def _sort(rows: list[dict], sort_by: str | None, descending: bool) -> list[dict]:
        """按 sort_by 排序；值为 None 的行统一排到末尾（不受升/降序影响）。

        数据来自单一 DB 列、类型同质，故直接按原值比较；无该列或 sort_by 为空时
        保持原顺序。
        """
        if not sort_by:
            return rows
        present = [r for r in rows if r.get(sort_by) is not None]
        absent = [r for r in rows if r.get(sort_by) is None]
        present.sort(key=lambda r: r.get(sort_by), reverse=descending)
        return present + absent

    def build_rows(
        self,
        *,
        status: str | None = None,
        membership_status: str | None = None,
        sort_by: str | None = PLAYER_EXPORT_DEFAULT_SORT,
        descending: bool = PLAYER_EXPORT_DEFAULT_DESC,
    ) -> tuple[list[dict], list[str]]:
        """取账号 -> 筛选 -> 排序 -> 按导出列映射为中文表头行。

        返回 (rows, headers)：rows 的 key 已是中文表头，headers 为有序表头列表。
        """
        accounts = self.player_service.list_all(status=status)
        if membership_status:
            accounts = [
                a for a in accounts
                if (a.get("membership_status") or "member") == membership_status
            ]
        accounts = self._sort(accounts, sort_by, descending)

        headers = list(PLAYER_EXPORT_COLUMNS.values())
        rows = [
            {header: acc.get(field) for field, header in PLAYER_EXPORT_COLUMNS.items()}
            for acc in accounts
        ]
        return rows, headers

    def export(
        self,
        target: str,
        *,
        status: str | None = None,
        membership_status: str | None = None,
        sort_by: str | None = PLAYER_EXPORT_DEFAULT_SORT,
        descending: bool = PLAYER_EXPORT_DEFAULT_DESC,
        sheet: str | None = None,
    ) -> tuple[int, str]:
        """导出玩家档案到表格。返回 (导出行数, 实际写入的 sheet 名)。

        写出时开启自动筛选 + 冻结首行，便于在本地/在线文档里直接筛选、排序。
        """
        rows, headers = self.build_rows(
            status=status,
            membership_status=membership_status,
            sort_by=sort_by,
            descending=descending,
        )
        sheet_name = sheet or PLAYER_EXPORT_SHEET
        self.excel_io.write_sheet(
            target,
            rows,
            headers=headers,
            sheet=sheet_name,
            auto_filter=True,
            freeze_header=True,
        )
        return len(rows), sheet_name
