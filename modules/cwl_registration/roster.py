"""报名模块 · 功能②：根据报名快照 + 账号得分生成联赛名单（原 arrange_league 行为）。

B 方案数据流（报名不建行）：
1. 读本月报名快照（RegistrationRepository，自持 account_name/player_name/账号类型/
   匹配值等）。
2. 名字 -> tag -> 得分：优先用报名行缓存的 player_tag，没有则按 account_name 只读
   反查真实账号；命中则取其 history_score，未命中（"报名有 / COC 无"的新人）得 0 分。
3. 调用纯函数 sort_accounts 完成分组 + 排序（输入口径不变）。
4. 回写每条报名的 league_type / rank_order 到 registrations 表。
5. 通过 ExcelIO 输出名单表。
"""
from __future__ import annotations

from modules.cwl_registration.config import (
    ARRANGEMENT_OUTPUT_HEADERS,
    EXCLUDED_CAMP_NAMES,
    SORT_WEIGHTS,
)
from modules.cwl_registration.repository import RegistrationRepository
from modules.cwl_registration.sorter import sort_accounts
from modules.player.service import PlayerService
from shared.io_adapter.base import ExcelIO


def _prev_period(period: str) -> str | None:
    """把 "YYYY-MM" 推算为上一个月 "YYYY-MM"；格式非法时返回 None。"""
    try:
        year_s, month_s = period.split("-")
        year, month = int(year_s), int(month_s)
    except (ValueError, AttributeError):
        return None
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


class LeagueArranger:
    def __init__(
        self,
        player_service: PlayerService,
        reg_repo: RegistrationRepository,
        excel_io: ExcelIO,
    ):
        self.player_service = player_service
        self.reg_repo = reg_repo
        self.excel_io = excel_io

    def _load_accounts(self, period: str) -> list[dict]:
        """由报名快照构造排序所需列表，账号档案（得分/奖杯）为可选增强。

        额外注入：
        - trophies : 取自 accounts（COC 同步），战营排序的主排序键（阶段一）。
        - prev_rank: 该账号上月名单排名（反查上月 registrations.rank_order），供
          战营排序的微调预留接口使用。

        排除名单（EXCLUDED_CAMP_NAMES）在此阶段过滤：这些账号正常入库但不出现在
        最终联赛名单中。过滤在加载阶段完成，保证排序和导出都不含排除名单成员。
        """
        regs = self.reg_repo.get_registrations(period)
        prev_month = _prev_period(period)
        prev_rank_map = (
            self.reg_repo.rank_orders_of_period(prev_month) if prev_month else {}
        )
        merged = []
        for reg in regs:
            account_name = reg.get("account_name")
            # 排除名单过滤：命中则跳过，不参与排序/不出现在最终名单
            if account_name in EXCLUDED_CAMP_NAMES:
                continue
            # 优先用报名行缓存的 tag；没有则按昵称再解析一次（覆盖导入后才同步到的账号）
            tag = reg.get("player_tag") or self.player_service.resolve_tag_by_name(
                account_name
            )
            acc = self.player_service.get(tag) if tag else None
            merged.append(
                {
                    "reg_id": reg["id"],
                    "player_tag": tag,
                    "account_name": account_name,   # 报名表自持
                    "player_name": reg.get("player_name"),     # 报名表自持
                    "account_type": reg.get("account_type"),
                    # 上月排名：优先反查上月编排结果，回退到报名行缓存的 prev_rank
                    "prev_rank": prev_rank_map.get(account_name)
                    or reg.get("prev_rank"),
                    "match_value": reg.get("match_value"),
                    "join_combat": bool(reg.get("join_combat")),
                    # 命中真实账号取历史分/奖杯，未命中的新人得 0
                    "history_score": (acc.get("history_score") or 0.0) if acc else 0.0,
                    "trophies": (acc.get("trophies") or 0) if acc else 0,
                }
            )
        return merged

    def arrange(self, period: str, weights: dict | None = None) -> list[dict]:
        """生成排序后的名单，并回写数据库。返回排序结果列表。"""
        accounts = self._load_accounts(period)
        ordered = sort_accounts(accounts, weights or SORT_WEIGHTS)

        for item in ordered:
            if item.get("reg_id") is not None:
                self.reg_repo.update_arrangement(
                    item["reg_id"], item["league_type"], item["rank_order"]
                )
        return ordered

    def arrange_and_export(
        self,
        period: str,
        target: str,
        weights: dict | None = None,
        sheet: str | None = None,
    ) -> tuple[list[dict], str]:
        """生成名单并导出到表格的新 sheet。

        sheet 缺省按月份命名为 "名单_<period>"，写入时在目标工作簿中新建该
        sheet（若文件已存在则保留其余 sheet，同名 sheet 覆盖重建）。
        返回 (排序结果列表, 实际写入的 sheet 名)。
        """
        ordered = self.arrange(period, weights)
        rows = [
            {h: item.get(h) for h in ARRANGEMENT_OUTPUT_HEADERS} for item in ordered
        ]
        sheet_name = sheet or f"名单_{period}"
        self.excel_io.write_sheet(
            target, rows, headers=ARRANGEMENT_OUTPUT_HEADERS, sheet=sheet_name
        )
        return ordered, sheet_name
