"""战绩模块 · 导入战绩并更新到 player 历史分。

流程：
1. 通过 ExcelIO 读取战绩表。
2. 用**关键词映射**解析 tag / 联赛类型（与报名侧一致，修复 #3）；其余列作为
   raw_metrics 存 JSON。
3. 导入前用 PlayerService 校验账号是否存在：不存在则**跳过并告警**（修复 #2），
   不因外键约束整批失败。
4. 写入 results 表（upsert，修复 #1）。
5. 对涉及的账号重算 history_score（compute_history_score）并通过 PlayerService 回写。
"""
from __future__ import annotations

import sys

from modules.player.service import PlayerService
from config import RESULT_COLUMN_KEYWORDS, RESULT_TAG_SOURCE
from modules.war_result.history_score import compute_history_score
from modules.war_result.repository import ResultRepository
from shared.columns import clean_str, resolve_columns
from shared.io_adapter.base import ExcelIO


def parse_result_row(raw: dict, colmap: dict | None = None) -> dict | None:
    """解析一行战绩：按关键词取 tag / 联赛类型，其余列汇总为 raw_metrics。

    tag 取 RESULT_TAG_SOURCE 指定字段（当前=account_name，与报名侧一致）。
    取不到 tag 的行返回 None（跳过）。纯函数，便于测试。
    """
    if colmap is None:
        colmap = resolve_columns(list(raw.keys()), RESULT_COLUMN_KEYWORDS)

    def cell(field):
        col = colmap.get(field)
        return raw.get(col) if col else None

    tag = clean_str(cell(RESULT_TAG_SOURCE))
    if tag is None:
        return None

    # 被识别为固定字段的列不进 raw_metrics（其余全部作为指标保留）
    fixed_cols = {col for col in colmap.values()}
    metrics = {k: v for k, v in raw.items() if k not in fixed_cols}

    return {
        "player_tag": tag,
        "league_type": clean_str(cell("league_type")),
        "raw_metrics": metrics,
    }


class ResultImporter:
    def __init__(
        self,
        player_service: PlayerService,
        result_repo: ResultRepository,
        excel_io: ExcelIO,
        scoring_config: dict | None = None,
    ):
        self.player_service = player_service
        self.result_repo = result_repo
        self.excel_io = excel_io
        self.scoring_config = scoring_config or {}

    def import_from(self, source: str, period: str, sheet: str | None = None) -> int:
        """导入战绩表，返回导入条数，并更新相关账号历史分。

        未知账号（player 档案不存在）会被跳过并告警，不中断整批导入。
        """
        rows = self.excel_io.read_sheet(source, sheet)
        touched: set[str] = set()
        imported = 0
        for raw in rows:
            parsed = parse_result_row(raw)
            if parsed is None:
                continue

            # 走 A 后 player_tag = COC 真实 Tag；战绩表只有昵称，按昵称反查真实/临时账号。
            name = parsed["player_tag"]
            tag = self.player_service.resolve_tag_by_name(name)
            if tag is None:
                print(
                    f"[warn] 战绩表账号 '{name}' 在账号档案中不存在，已跳过该行"
                    f"（请先 coc-sync 同步或导入其报名）。",
                    file=sys.stderr,
                )
                continue

            self.result_repo.add_result(
                {
                    "player_tag": tag,
                    "period": period,
                    "league_type": parsed["league_type"],
                    "raw_metrics": parsed["raw_metrics"],
                }
            )
            touched.add(tag)
            imported += 1

        for tag in touched:
            history = self.result_repo.get_results(tag)
            score = compute_history_score(history, self.scoring_config)
            self.player_service.update_history_score(tag, score)

        return imported
