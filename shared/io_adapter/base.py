"""IO 适配层抽象接口。

业务模块只依赖 ExcelIO，不直接 import openpyxl / 腾讯文档 SDK。
- 当前实现：LocalXlsxAdapter（本地 xlsx）
- 预留实现：TencentDocAdapter（腾讯文档 API，待企业资质）
测试时可注入 FakeExcelIO（见 tests/fakes.py）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ExcelIO(ABC):
    """表格读写抽象接口。

    数据统一以 "行字典列表" 形式传递：list[dict]，每个 dict 的 key 为列名。
    """

    @abstractmethod
    def read_sheet(
        self, source: str, sheet: str | None = None, fill_merged: bool = False
    ) -> list[dict]:
        """读取表格，返回行字典列表。source 为文件路径或文档标识。

        fill_merged=True 时，把合并单元格的左上值填充到区内所有单元格
        （报名表主信息合并在首行、一次提交多账号跨行时需要）。
        """
        ...

    @abstractmethod
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
        """写出行字典列表到表格。headers 指定列顺序；为空则用首行的 keys。

        auto_filter=True：在表头行开启自动筛选（阅读者可直接按列筛选/排序）。
        freeze_header=True：冻结首行表头（滚动时表头常驻）。
        两者均为展示层可选项，不支持的适配器可忽略（默认 False 向后兼容）。
        highlight_rows: 需要红色字体的数据行索引集合（0-based，不含表头行）。
            背景填充色暂不支持（腾讯文档 v3 API 限制）。
        """
        ...
