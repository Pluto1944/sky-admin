"""报名模块 · 功能②：根据报名快照 + 账号得分生成联赛名单（原 arrange_league 行为）。

B 方案数据流（报名不建行）：
1. 读本月报名快照（RegistrationRepository，自持 account_name/player_name/账号类型/
   匹配值等）。
2. 名字 -> tag -> 得分：优先用报名行缓存的 player_tag，没有则按 account_name 只读
   反查真实账号；命中则取其 history_score，未命中（"报名有 / COC 无"的新人）得 0 分。
3. 调用纯函数 sort_accounts 完成分组 + 排序（输入口径不变）。
4. 调用 fill_teams 将排序结果分配到队伍中。
5. 【升降级】根据上月实战星数，在相邻实战队伍间交换人员（promotion.py）。
6. 回写每条报名的 league_type / rank_order / team_name 到 registrations 表。
7. 通过 ExcelIO 输出名单表（同一 sheet 含排序名单 + 队伍分配明细）。
"""
from __future__ import annotations

from modules.cwl_registration.config import (
    ARRANGEMENT_OUTPUT_HEADERS,
    COMBAT_MIN_MATCH_VALUE,
    EXCLUDED_CAMP_NAMES,
    PROMOTION_RELEGATION_CONFIG,
    SORT_WEIGHTS,
    TEAM_OUTPUT_HEADERS,
    TEAMS,
)
from modules.cwl_registration.promotion import (
    apply_promotion_relegation,
    rebuild_assignment_map,
)
from modules.cwl_registration.repository import RegistrationRepository
from modules.cwl_registration.sorter import sort_accounts
from modules.cwl_registration.team_filler import fill_teams
from modules.player.service import PlayerService
from modules.war_result.repository import ResultRepository
from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL
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


def _extract_total_stars(raw_metrics: dict) -> int | None:
    """从 raw_metrics 中提取总星数，兼容多种格式。

    优先级：
    1. {"total_stars": 18}                         → 直接取
    2. {"three_stars": 15, "two_stars": 4, ...}    → 3*15 + 2*4 + ...
    3. {"stars_1": 1, "stars_2": 2, "stars_3": 15} → 类似计算
    4. 无法解析 → None（该账号不参与升降级）
    """
    if not raw_metrics:
        return None

    if "total_stars" in raw_metrics:
        try:
            return int(raw_metrics["total_stars"])
        except (TypeError, ValueError):
            return None

    total = 0
    found = False
    for star_str, count in raw_metrics.items():
        if star_str in ("three_stars", "stars_3"):
            total += int(count) * 3
            found = True
        elif star_str in ("two_stars", "stars_2"):
            total += int(count) * 2
            found = True
        elif star_str in ("one_stars", "stars_1"):
            total += int(count) * 1
            found = True
    if found:
        return total

    return None


class LeagueArranger:
    def __init__(
        self,
        player_service: PlayerService,
        reg_repo: RegistrationRepository,
        excel_io: ExcelIO,
        result_repo: ResultRepository | None = None,
    ):
        self.player_service = player_service
        self.reg_repo = reg_repo
        self.excel_io = excel_io
        self.result_repo = result_repo

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

    def _load_combat_star_data(self, period: str) -> dict[str, int]:
        """从 results 表加载本月实战星数，返回 {account_name: total_stars}。

        CWL 时间线：每月第 1 周 CWL 战争，随后几周为下月报名。
        因此报名和历史星数属于同一个 period（同为报名所在月）：
          - 7 月报名 → period="2026-07"
          - 7 月 CWL 星数 → period="2026-07"（同期，非上月）

        数据路径：
        1. results 表按 period + league_type='combat' 查询
        2. raw_metrics 中提取 total_stars
        3. player_tag → account_name（通过 accounts 表反查）
        4. 返回 {account_name: total_stars}

        若 result_repo 未注入或无数据，返回空 dict（升降级自动跳过）。
        """
        if self.result_repo is None:
            return {}

        rows = self.result_repo.get_results_by_period(period, league_type=LEAGUE_COMBAT)
        star_data: dict[str, int] = {}
        for r in rows:
            tag = r.get("player_tag")
            metrics = r.get("raw_metrics") or {}
            stars = _extract_total_stars(metrics)
            if tag and stars is not None:
                account_name = self.player_service.resolve_name_by_tag(tag)
                if account_name:
                    star_data[account_name] = stars
        return star_data

    def arrange(
        self,
        period: str,
        weights: dict | None = None,
        teams: list[dict] | None = None,
        combat_min_match_value: float | None = None,
        star_data: dict[str, int] | None = None,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """生成排序名单 + 队伍分配（含升降级），并回写数据库。

        period 语义：**联赛时间**（实际打 CWL 的月份）。
        报名在联赛前一个月进行，故内部自动推算报名时间 = period - 1 月：
          - arrange("2026-08") → 读 "2026-07" 的报名 + "2026-07" 的 CWL 星数
          - arrange("2026-09") → 读 "2026-08" 的报名 + "2026-08" 的 CWL 星数

        参数:
            star_data: 实战星数 {account_name: total_stars}。
                显式传入时直接使用（冷启动场景）；为 None 时从 results 表
                按报名时间自动加载。

        返回:
            (含 team_name 的排序名单, 队伍分配结果列表, 升降级日志列表)
            升降级日志可能为空列表（无星数数据或无候选）。
        """
        # 联赛时间 → 报名时间（前一个月）
        reg_period = _prev_period(period)
        if not reg_period:
            raise ValueError(f"无法从联赛时间 '{period}' 推算报名时间")

        accounts = self._load_accounts(reg_period)
        ordered = sort_accounts(accounts, weights or SORT_WEIGHTS)

        # 回写 league_type / rank_order
        for item in ordered:
            if item.get("reg_id") is not None:
                self.reg_repo.update_arrangement(
                    item["reg_id"], item["league_type"], item["rank_order"]
                )

        # 队伍填充
        teams_cfg = teams if teams is not None else TEAMS
        threshold = (
            combat_min_match_value
            if combat_min_match_value is not None
            else COMBAT_MIN_MATCH_VALUE
        )
        ordered_with_team, team_results = fill_teams(
            ordered, teams_cfg, threshold
        )

        # 升降级：根据同期（报名时间所在月）CWL 星数交换人员
        movements: list[dict] = []
        if star_data is None:
            star_data = self._load_combat_star_data(reg_period)

        if star_data:
            team_results, movements = apply_promotion_relegation(
                team_results, star_data, PROMOTION_RELEGATION_CONFIG
            )
            # 交换后重建 ordered_with_team 的 team_name 映射
            rebuild_assignment_map(ordered_with_team, team_results)

            # 注入升降级标识到成员数据（供导出展示）
            if movements:
                movement_map: dict[str, str] = {}
                for m in movements:
                    direction = "↑升级" if m["direction"] == "promotion" else "↓降级"
                    movement_map[m["account_name"]] = f"{direction}({m['total_stars']}★)"
                for tr in team_results:
                    for member in tr["members"]:
                        name = member.get("account_name")
                        if name and name in movement_map:
                            member["movement"] = movement_map[name]
                for item in ordered_with_team:
                    name = item.get("account_name")
                    if name and name in movement_map:
                        item["movement"] = movement_map[name]

                print("\n[升降级] 本月人员调整：")
                for m in movements:
                    print(
                        f"  {m['account_name']} ({m['total_stars']}星) "
                        f"{movement_map[m['account_name']]}: "
                        f"{m['from_team']} → {m['to_team']}"
                    )

        # 回写 team_name（升降级后可能已变化）
        for item in ordered_with_team:
            if item.get("reg_id") is not None and item.get("team_name"):
                self.reg_repo.update_team_name(
                    item["reg_id"], item["team_name"]
                )

        return ordered_with_team, team_results, movements

    def arrange_and_export(
        self,
        period: str,
        target: str,
        weights: dict | None = None,
        sheet: str | None = None,
        teams: list[dict] | None = None,
        combat_min_match_value: float | None = None,
        star_data: dict[str, int] | None = None,
    ) -> tuple[list[dict], list[dict], list[dict], str]:
        """生成名单并导出到表格的新 sheet。

        同一 sheet 包含两部分：上半部分为排序名单（含 team_name 列），
        下半部分按队伍分组展示分配明细。
        sheet 缺省按月份命名为 "名单_<period>"。
        返回 (含 team_name 排序名单, 队伍分配结果, 升降级日志, 实际 sheet 名)。
        """
        ordered, team_results, movements = self.arrange(
            period, weights, teams, combat_min_match_value, star_data
        )

        # 拼接输出行：排序名单 + 空白分隔 + 队伍明细
        # 第一部分：排序名单（使用排序名单表头）
        combined_rows: list[dict] = [
            {h: item.get(h) for h in ARRANGEMENT_OUTPUT_HEADERS}
            for item in ordered
        ]

        # 分隔符：两行空白 + 标题行
        for _ in range(2):
            combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})
        combined_rows.append(
            {
                **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                "rank_order": "=== 战队分配 ===",
            }
        )

        # 第二部分：逐队展示
        combat_label = {LEAGUE_COMBAT: "实战", LEAGUE_SHELL: "壳子"}
        for tr in team_results:
            cat = combat_label.get(tr["category"], tr["category"])
            if tr["reserved_empty"] > 0:
                cap_info = f"{tr['filled_count']}/{tr['member_count'] - tr['reserved_empty']}+{tr['reserved_empty']}"
            else:
                cap_info = f"{tr['filled_count']}/{tr['member_count']}"
            league_info = f"({tr.get('league_level')}) " if tr.get("league_level") else ""
            leader_info = f"领队:{tr.get('leader', '')} " if tr.get("leader") else ""
            title = (
                f"{cat}: {tr['team_name']} "
                f"{league_info}"
                f"{tr.get('clan_tag', '')} "
                f"{leader_info}"
                f"管理:{tr.get('manager', '')} "
                f"满员:{cap_info}"
            )
            # 队伍标题行
            combined_rows.append(
                {
                    **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                    "rank_order": title,
                }
            )
            # 队伍成员行
            for m in tr["members"]:
                combined_rows.append(
                    {h: m.get(h) for h in ARRANGEMENT_OUTPUT_HEADERS}
                )
            # 队伍之间空一行
            combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

        sheet_name = sheet or f"名单_{period}"
        self.excel_io.write_sheet(
            target,
            combined_rows,
            headers=ARRANGEMENT_OUTPUT_HEADERS,
            sheet=sheet_name,
        )
        return ordered, team_results, movements, sheet_name
