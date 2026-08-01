"""报名模块 · 功能②：根据报名快照 + 账号得分生成联赛名单（v3.0 基准重建方案）。

v3.0 数据流（基准升降级）：
1. 读本月报名快照（RegistrationRepository，自持 account_name/player_name/账号类型/
   匹配值等）。
2. 名字 -> tag -> 得分：优先用报名行缓存的 player_tag，没有则按 account_name 只读
   反查真实账号；命中则取其 history_score，未命中（"报名有 / COC 无"的新人）得 0 分。
3. 调用纯函数 sort_accounts 完成分组 + 排序（输入口径不变）。
4. 【基准重建】build_final_list：以上月名单为锚点，构建最终线性名单
   - 阶段0：黑名单过滤
   - 阶段1：构建7个临时名单
   - 阶段2：基准重建+升降级（上月队伍分组上配对交换）
   - 阶段3：删除缺失人员
   - 阶段4：插入战营新增（编号30）
   - 阶段5：插入普通营新增（编号45后二分插入）
   - 阶段6：追加壳子名单
5. 【队伍填充】build_teams：贪心填充队伍 + 白名单处理
6. 回写每条报名的 league_type / rank_order / team_name 到 registrations 表。
7. 通过 ExcelIO 输出名单表（Part1 排序名单 + Part2 队伍明细 + Part3 离队 + Part4 排布）。
"""
from __future__ import annotations

import sys

from modules.cwl_registration.config import (
    ARRANGEMENT_OUTPUT_HEADERS,
    BLACK_LIST,
    EXCLUDED_CAMP_NAMES,
    MANAGER_CANDIDATES,
    NEW_COMBAT_INSERT_START,
    NEW_NORMAL_INSERT_START,
    PROMOTION_RELEGATION_CONFIG,
    SORT_WEIGHTS,
    TEAMS,
    WHITE_LIST,
)
from modules.cwl_registration.baseline_rebuilder import build_final_list
from modules.cwl_registration.team_builder import build_teams
from modules.cwl_registration.repository import RegistrationRepository
from modules.cwl_registration.sorter import sort_accounts
from modules.coc_sync.api_client import CocApiClient, CocApiError
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
        self._coc_client: CocApiClient | None = None
        self._clan_info_cache: dict[str, tuple[str, str]] = {}

    def _get_coc_client(self) -> CocApiClient:
        if self._coc_client is None:
            self._coc_client = CocApiClient()
        return self._coc_client

    def _fetch_clan_info(self, clan_tags: set[str]) -> dict[str, tuple[str, str]]:
        """批量通过 COC API 获取部落名称和首领昵称。

        返回 {clan_tag: (clan_name, leader_name)}。
        查询失败的部落值设为 ("", "")。
        已缓存的 tag 不会重复请求。
        """
        result: dict[str, tuple[str, str]] = {}
        # 过滤非法 tag（如多个 # 号、空字符串等），避免无效 API 调用
        def _valid_tag(t: str) -> bool:
            return bool(t) and t.count("#") == 1 and len(t) > 2

        tags_to_fetch = [
            t for t in clan_tags
            if _valid_tag(t) and t not in self._clan_info_cache
        ]

        if not tags_to_fetch:
            # 全部命中缓存
            for t in clan_tags:
                if t:
                    result[t] = self._clan_info_cache.get(t, ("", ""))
            return result

        client = self._get_coc_client()
        for tag in tags_to_fetch:
            try:
                clan = client.get_clan(tag)
                name = clan.get("name", "")
                # 从 memberList 中找到 role=leader 的首领
                leader = ""
                for m in clan.get("memberList", []) or []:
                    if m.get("role") == "leader":
                        leader = m.get("name", "")
                        break
                self._clan_info_cache[tag] = (name, leader)
                result[tag] = (name, leader)
            except CocApiError as e:
                print(f"[warn] 查询部落 {tag} 信息失败：{e}", file=sys.stderr)
                self._clan_info_cache[tag] = ("", "")
                result[tag] = ("", "")

        # 补充缓存中已有的
        for t in clan_tags:
            if t and t not in result:
                result[t] = self._clan_info_cache.get(t, ("", ""))

        return result

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
                    "willing_to_manage": bool(reg.get("willing_to_manage")),
                    # 命中真实账号取历史分/奖杯，未命中的新人得 0
                    "history_score": (acc.get("history_score") or 0.0) if acc else 0.0,
                    "trophies": (acc.get("trophies") or 0) if acc else 0,
                }
            )
        return merged

    def _load_combat_star_data(self, cwl_period: str) -> dict[str, int]:
        """从 results 表加载指定月份 CWL 实战星数，返回 {account_name: total_stars}。

        cwl_period 语义：**CWL 实际发生月**（即 results.period）。
        编排 N 月联赛时，需要的 CWL 星数来自 N-1 月，调用方应传入
        `_prev_period(league_period)`。

        数据路径：
        1. results 表按 cwl_period + league_type='combat' 查询
        2. raw_metrics 中提取 total_stars
        3. player_tag → account_name（通过 accounts 表反查）
        4. 返回 {account_name: total_stars}

        若 result_repo 未注入或无数据，返回空 dict（升降级自动跳过）。
        """
        if self.result_repo is None:
            return {}

        rows = self.result_repo.get_results_by_period(cwl_period, league_type=LEAGUE_COMBAT)
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

    def _load_combat_team_map(
        self, cwl_period: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        """从 results 表加载 CWL 队伍归属。

        cwl_period 语义：**CWL 实际发生月**（即 results.period），与
        _load_combat_star_data 同源。编排 N 月联赛时传入
        `_prev_period(league_period)` 获取上月 CWL 队伍信息。

        返回 (prev_teams, team_clan_tags):
          - prev_teams: {account_name: team_name}，用于"未报名/离开"人员原队查找。
          - team_clan_tags: {team_name: clan_tag}，用于显示层补充 clan_tag
            （覆盖 TEAMS 配置中未单独列出的队伍名，如"大一 A/B/C"）。

        team_name / clan_tag 存储在 raw_metrics 中（由 fetch_cwl_data 导入时写入）。
        替代反查 registrations（后者依赖 arrange 回写 team_name，冷启动场景容易缺失）。
        """
        if self.result_repo is None:
            return {}, {}

        rows = self.result_repo.get_results_by_period(cwl_period, league_type=LEAGUE_COMBAT)
        team_map: dict[str, str] = {}
        team_clan_tags: dict[str, str] = {}
        for r in rows:
            tag = r.get("player_tag")
            metrics = r.get("raw_metrics") or {}
            team_name = metrics.get("team_name")
            clan_tag = metrics.get("clan_tag")
            if tag and team_name:
                account_name = self.player_service.resolve_name_by_tag(tag)
                if account_name:
                    team_map[account_name] = team_name
                if clan_tag:
                    team_clan_tags.setdefault(team_name, clan_tag)
        return team_map, team_clan_tags

    def _load_prev_combat_from_results(self, cwl_period: str) -> list[dict]:
        """从 results 表构建上月实战名单（名单1 的数据源）。

        results 表的 raw_metrics 含 team_name / clan_tag / total_stars / team_index，
        可同时提供成员、队伍归属和星数——比 registrations 表更可靠
        （registrations 依赖 arrange 回写，冷启动场景可能缺失）。

        team_index 是队伍编号（combat 队伍在 TEAMS 配置中的顺序索引），
        作为队伍的唯一身份标识用于升降级分组——team_name 可能重名（如"大一"），
        clan_tag 仅用于展示，都不能可靠地做分组 key。

        返回列表，每项含:
          - account_name: 账号昵称
          - player_tag: COC Tag
          - team_name: 上月所属队伍（展示用）
          - clan_tag: 上月所属部落 tag（展示用）
          - team_index: 队伍编号（分组用，可能为 None 表示旧数据）
          - stars: 上月总星数（无则为 None）
          - rank_order: None（results 无此字段，分组排序靠 team_index + stars）
        """
        if self.result_repo is None:
            return []

        rows = self.result_repo.get_results_by_period(cwl_period, league_type=LEAGUE_COMBAT)
        result: list[dict] = []
        for r in rows:
            tag = r.get("player_tag")
            metrics = r.get("raw_metrics") or {}
            team_name = metrics.get("team_name")
            if not tag or not team_name:
                continue
            account_name = self.player_service.resolve_name_by_tag(tag)
            if not account_name:
                continue
            stars = _extract_total_stars(metrics)
            result.append({
                "account_name": account_name,
                "player_tag": tag,
                "team_name": team_name,
                "clan_tag": metrics.get("clan_tag"),
                "team_index": metrics.get("team_index"),
                "stars": stars,
                "rank_order": None,  # results 表无此字段
            })
        return result

    def arrange(
        self,
        period: str,
        weights: dict | None = None,
        teams: list[dict] | None = None,
        combat_min_match_value: float | None = None,
        star_data: dict[str, int] | None = None,
    ) -> tuple[list[dict], list[dict], list[dict], dict[str, int]]:
        """生成排序名单 + 队伍分配（含升降级），并回写数据库。

        v3.0 基准重建流程：
          阶段 0：前置过滤（黑名单）
          阶段 1：构建 7 个临时名单
          阶段 2：基准重建 + 升降级（在上月队伍分组上配对交换）
          阶段 3：删除实战缺失人员
          阶段 4：插入战营实战新增（编号30）
          阶段 5：插入普通营实战新增（编号45后二分插入）
          阶段 6：追加壳子名单
          阶段 7：贪心填充队伍
          阶段 8：白名单处理

        period 语义：**联赛时间**（实际打 CWL 的月份）。
        报名数据存于 registrations 表，period = 联赛时间（统一语义）。
        CWL 星数存于 results 表，period = CWL 实际发生月 = 联赛时间 - 1 月：
          - arrange("2026-08") → 读 registrations(2026-08) + results(2026-07)

        参数:
            star_data: 实战星数 {account_name: total_stars}。
                显式传入时直接使用（冷启动场景）；为 None 时从 results 表
                按上月 CWL period 自动加载。

        返回:
            (含 team_name 的排序名单, 队伍分配结果列表, 升降级日志列表, star_data)
            升降级日志可能为空列表（无星数数据或无候选）。
        """
        # registrations.period = 联赛时间，直接查询
        accounts = self._load_accounts(period)
        ordered = sort_accounts(accounts, weights or SORT_WEIGHTS)

        # 回写 league_type / rank_order
        for item in ordered:
            if item.get("reg_id") is not None:
                self.reg_repo.update_arrangement(
                    item["reg_id"], item["league_type"], item["rank_order"]
                )

        teams_cfg = teams if teams is not None else TEAMS

        # CWL 实际发生月 = 联赛时间 - 1（results.period 语义）
        cwl_period = _prev_period(period)
        if star_data is None and cwl_period:
            star_data = self._load_combat_star_data(cwl_period)
        elif star_data is None:
            star_data = {}

        # 加载上月实战名单（名单1 的成员+队伍归属，从 results 表获取）
        prev_combat_regs: list[dict] = []
        if cwl_period:
            prev_combat_regs = self._load_prev_combat_from_results(cwl_period)

        # === 阶段 0~6：基准重建，构建最终线性名单 ===
        final_list, removed_list, movements, black_hits = build_final_list(
            accounts=ordered,
            prev_combat_regs=prev_combat_regs,
            star_data=star_data,
            teams=teams_cfg,
            black_list=BLACK_LIST,
            prev_teams_config=teams_cfg,  # 上月配置暂用当月配置
            promotion_config=PROMOTION_RELEGATION_CONFIG,
            new_combat_insert_start=NEW_COMBAT_INSERT_START,
            new_normal_insert_start=NEW_NORMAL_INSERT_START,
        )

        # === 阶段 7~9：贪心填充队伍 + 白名单处理 + 管理员分配 ===
        team_results = build_teams(
            final_list=final_list,
            teams=teams_cfg,
            white_list=WHITE_LIST,
            manager_candidates=MANAGER_CANDIDATES,
        )

        # 注入 movement 标识 + 修正 league_type（供导出展示）
        # 优先用 player_tag 匹配（稳定唯一），回退到 account_name（兼容无 tag 场景）
        # 避免 results 表反查的 account_name（最新昵称）与 registrations 表的
        # account_name（报名时昵称）因改名不一致导致 movement 标记丢失
        movement_map: dict[str, str] = {}
        movement_map_by_name: dict[str, str] = {}
        if movements:
            for m in movements:
                direction = "↑升级" if m["direction"] == "promotion" else "↓降级"
                label = f"{direction}({m['total_stars']}★)"
                tag = m.get("player_tag")
                if tag:
                    movement_map[tag] = label
                movement_map_by_name[m["account_name"]] = label

        for tr in team_results:
            for member in tr["members"]:
                name = member.get("account_name")
                if not name:
                    continue
                # 修正 league_type：老兵来自 results 表无 league_type，按队伍 category 设置
                if member.get("league_type") is None:
                    member["league_type"] = tr["category"]
                # 优先按 player_tag 匹配，回退到 account_name
                tag = member.get("player_tag")
                label = movement_map.get(tag) if tag else None
                if label is None and name in movement_map_by_name:
                    label = movement_map_by_name[name]
                if label:
                    member["movement"] = label
                elif member.get("movement") is None:
                    # 未标记的成员补充标识
                    if tr["category"] == LEAGUE_SHELL and name in star_data:
                        member["movement"] = f"↓转壳({star_data[name]}★)"
                    elif tr["category"] == LEAGUE_COMBAT and name not in star_data:
                        member["movement"] = "新"

        # 构建 ordered_with_team（含 team_name 的排序名单）
        # 从 final_list 和 team_results 重建
        assignment_map: dict[str, tuple[str, str]] = {}
        cur_team_map: dict[str, str] = {}
        for tr in team_results:
            tn = tr["team_name"]
            cat = tr["category"]
            cur_team = f"{tr.get('team_index')} {tn}" if tr.get("team_index") is not None else tn
            for m in tr["members"]:
                key = m.get("account_name") or ""
                if key:
                    assignment_map[key] = (tn, cat)
                    # 优先用成员自带的 cur_team（白名单/后移可能已更新）
                    cur_team_map[key] = m.get("cur_team") or cur_team

        ordered_with_team: list[dict] = []
        # final_list 的顺序就是输出顺序
        for item in final_list:
            item = dict(item)
            name = item.get("account_name") or ""
            if name in assignment_map:
                item["team_name"], item["league_type"] = assignment_map[name]
                item["cur_team"] = cur_team_map.get(name, "")
            else:
                item["team_name"] = None
                item["cur_team"] = None
            # prev_team 来自 baseline_rebuilder（上月老兵有值，新报名为空）
            if not item.get("prev_team"):
                item["prev_team"] = None
            # 注入 movement
            if name in movement_map:
                item["movement"] = movement_map[name]
            ordered_with_team.append(item)

        # 回写 team_name
        for item in ordered_with_team:
            if item.get("reg_id") is not None and item.get("team_name"):
                self.reg_repo.update_team_name(
                    item["reg_id"], item["team_name"]
                )

        # 打印升降级日志
        if movements:
            print("\n[升降级] 本月人员调整：")
            for m in movements:
                direction = "↑升级" if m["direction"] == "promotion" else "↓降级"
                print(
                    f"  {m['account_name']} ({m['total_stars']}星) "
                    f"{direction}: slot {m['from_slot']} → {m['to_slot']}"
                )

        # 打印离队情况
        if removed_list:
            print(f"\n[离队/缺失] {len(removed_list)} 人本月未参加实战：")
            for m in removed_list:
                stars = star_data.get(m["account_name"])
                star_str = f" ({stars}星)" if stars is not None else ""
                print(f"  {m['account_name']}{star_str}")

        if black_hits:
            print(f"\n[黑名单] {len(black_hits)} 人被黑名单过滤：")
            for name in black_hits:
                print(f"  {name}")

        # 保存离队信息供 arrange_and_export 使用
        self._last_removed_list = removed_list
        self._last_black_hits = black_hits

        return ordered_with_team, team_results, movements, star_data

    def _build_part4_grid(
        self, team_results: list[dict]
    ) -> tuple[list[list[str]], list[int]]:
        """构建 Part4 联赛名单排布网格（备份留底）。

        返回 (grid, title_row_indices):
          - grid: list[list[str]]，每行 5 列，可直接拼入 combined_rows
          - title_row_indices: 抬头行在 grid 中的行索引列表
        """
        # 先收集所有 clan_tag，批量获取部落名称和首领
        all_tags = {tr.get("clan_tag", "") for tr in team_results}
        all_tags.discard("")
        clan_info = self._fetch_clan_info(all_tags)

        grid: list[list[str]] = []
        title_indices: list[int] = []

        for i, tr in enumerate(team_results):
            cat = "实战" if tr["category"] == LEAGUE_COMBAT else "壳子"
            # 记录抬头行索引
            title_indices.append(len(grid))
            # 抬头 5 列：队伍信息 | clan_tag | 部落名 | 首领 | 管理
            cap_info = f"{tr['filled_count']}/{tr['member_count']}"
            col1 = f"{cat}: {tr['team_name']} {cap_info}"
            col2 = tr.get("clan_tag", "")
            clan_name, leader_name = clan_info.get(col2, ("", ""))
            col3 = clan_name
            col4 = f"首领:{leader_name}" if leader_name else ""
            col5 = f"管理:{tr.get('manager', '')} 开战/捐兵给一份额外"
            grid.append([col1, col2, col3, col4, col5])

            members = tr["members"]
            is_shell = tr["category"] == LEAGUE_SHELL
            for j in range(0, len(members), 5):
                chunk = members[j:j + 5]
                row: list[str] = []
                for m in chunk:
                    name = m.get("account_name", "")
                    if is_shell:
                        mv = int(m.get("match_value") or 0)
                        row.append(f"{name} {mv}")
                    else:
                        row.append(name)
                row.extend([""] * (5 - len(row)))
                grid.append(row)

            if i < len(team_results) - 1:
                grid.append(["", "", "", "", ""])

        return grid, title_indices

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
        ordered, team_results, movements, star_data = self.arrange(
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
        # 先获取所有部落名称和首领（如果 _build_part4_grid 还没调用过的话）
        all_tags = {tr.get("clan_tag", "") for tr in team_results}
        all_tags.discard("")
        clan_info = self._fetch_clan_info(all_tags)

        combat_label = {LEAGUE_COMBAT: "实战", LEAGUE_SHELL: "壳子"}
        for tr in team_results:
            cat = combat_label.get(tr["category"], tr["category"])
            if tr["reserved_empty"] > 0:
                cap_info = f"{tr['filled_count']}/{tr['member_count'] - tr['reserved_empty']}+{tr['reserved_empty']}"
            else:
                cap_info = f"{tr['filled_count']}/{tr['member_count']}"
            clan_tag = tr.get("clan_tag", "")
            clan_name, leader_name = clan_info.get(clan_tag, ("", ""))
            league_info = f"({tr.get('league_level')}) " if tr.get("league_level") else ""
            config_leader = f"领队:{tr.get('leader', '')} " if tr.get("leader") else ""
            clan_leader = f"首领:{leader_name} " if leader_name else ""
            title = (
                f"{cat}: {tr['team_name']} "
                f"{league_info}"
                f"{clan_tag} "
                f"{clan_name} "
                f"{config_leader}"
                f"{clan_leader}"
                f"管理:{tr.get('manager', '')} 开战/捐兵给一份额外 "
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

        # 第三部分：离队情况（名单4 + 黑名单命中）
        removed_list = getattr(self, "_last_removed_list", [])
        black_hits = getattr(self, "_last_black_hits", [])

        if removed_list or black_hits:
            combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})
            total_absent = len(removed_list) + len(black_hits)
            combined_rows.append({
                **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                "rank_order": f"=== 离队情况（共{total_absent}人）===",
            })

            # 离队/缺失人员（名单4）
            if removed_list:
                combined_rows.append({
                    **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                    "rank_order": f"  [实战缺失] {len(removed_list)}人（上月实战，本月未参加）",
                })
                for m in removed_list:
                    stars = star_data.get(m["account_name"])
                    star_str = f"({stars}★)" if stars is not None else ""
                    prev_ti = m.get("team_index")
                    prev_tn = m.get("team_name", "")
                    prev_team = f"{prev_ti} {prev_tn}" if (prev_ti is not None and prev_tn) else prev_tn
                    combined_rows.append({
                        **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                        "account_name": m["account_name"],
                        "player_tag": self.player_service.resolve_tag_by_name(m["account_name"]),
                        "movement": f"缺失{star_str}",
                        "team_name": m.get("team_name", ""),
                        "prev_team": prev_team,
                    })
                combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

            # 黑名单命中
            if black_hits:
                combined_rows.append({
                    **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                    "rank_order": f"  [黑名单] {len(black_hits)}人",
                })
                for name in black_hits:
                    combined_rows.append({
                        **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                        "account_name": name,
                        "player_tag": self.player_service.resolve_tag_by_name(name),
                        "movement": "黑名单",
                    })
                combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

        # ===== Part 4: 联赛名单排布（备份留底） =====
        # Part4 独立写入（5 列 grid），不混入 combined_rows 的 dict，
        # 避免 ARRANGEMENT_OUTPUT_HEADERS 中多余列在 Part4 区域产生空列。
        # 在 combined_rows 末尾追加空行占位，让 write_sheet 预留空间，
        # 然后用 updateRangeRequest 覆盖写入 Part4 数据。
        grid, title_indices = self._build_part4_grid(team_results)
        part4_row_count = 2 + len(grid)  # 空行 + 标题 + grid

        # 追加空行占位
        for _ in range(part4_row_count):
            combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

        sheet_name = sheet or f"名单_{period}"
        self.excel_io.write_sheet(
            target,
            combined_rows,
            headers=ARRANGEMENT_OUTPUT_HEADERS,
            sheet=sheet_name,
        )

        # 追加 Part4（5 列 grid，覆盖空行占位）
        self._append_part4_to_sheet(target, sheet_name, grid, title_indices)

        return ordered, team_results, movements, sheet_name

    def _append_part4_to_sheet(
        self,
        target: str,
        sheet_name: str,
        grid: list[list[str]],
        title_indices: list[int],
    ) -> None:
        """将 Part4 网格追加到已有 sheet 末尾（5 列，不经过 header 映射）。

        在 write_sheet 调用前已预留行数，这里直接用 updateRangeRequest
        从已有数据末尾写入 Part4，不删表重建，保持原有格式不变。
        """
        from shared.io_adapter.tencent_doc import TencentDocAdapter
        if not isinstance(self.excel_io, TencentDocAdapter):
            return

        adapter = self.excel_io
        file_id = adapter._require_file_id(target)
        props = adapter._list_sheets(file_id)
        target_sheet = adapter._find_sheet(props, sheet_name)
        if target_sheet is None:
            return

        sheet_id = target_sheet["sheetId"]
        total_rows = int(target_sheet.get("rowCount") or 0)
        # Part4 行数：空行 + 标题 + grid
        part4_total = 2 + len(grid)
        start_row = total_rows - part4_total

        # 构建 Part4 矩阵
        matrix: list[list[dict]] = []
        # 空行
        matrix.append([adapter._cell("") for _ in range(5)])
        # 标题行
        matrix.append([adapter._cell("=== 联赛名单排布（备份留底） ===")] + [adapter._cell("") for _ in range(4)])
        # grid 行
        for i, row in enumerate(grid):
            fmt = {"fontColor": {"red": 255, "green": 0, "blue": 0, "alpha": 255}} if i in title_indices else None
            cells = [adapter._cell(v, fmt) for v in row]
            while len(cells) < 5:
                cells.append(adapter._cell(""))
            matrix.append(cells)

        # 分片写入
        from shared.io_adapter.tencent_doc import _MAX_UPDATE_ROWS, _MAX_UPDATE_CELLS
        rows_per_chunk = min(_MAX_UPDATE_ROWS, max(_MAX_UPDATE_CELLS // 5, 1))
        for chunk_start in range(0, len(matrix), rows_per_chunk):
            chunk = matrix[chunk_start:chunk_start + rows_per_chunk]
            adapter._batch_update(
                file_id,
                [{
                    "updateRangeRequest": {
                        "sheetId": sheet_id,
                        "gridData": {
                            "startRow": start_row + chunk_start,
                            "startColumn": 0,
                            "rows": [{"values": line} for line in chunk],
                        },
                    }
                }],
            )

    # 公示文档前 20 行固定文字（不随月份变化）
    PUBLISH_FIXED_ROWS: list[list[str]] = [
        ["苍穹联赛报名", "", "", "", ""],
        ["联赛开始，各部落暗号为999，加盟部落暗号找自己首领", "", "", "", ""],
        ["惑音天城 群英殿 火星 souls Avalon默认不开联赛", "", "", "", ""],
        ["1号下午4点～晚上10点开联赛，从上往下开，人够就发车，早点到", "", "", "", ""],
        ["miss想念香香", "", "", "", ""],
        ["打壳子的规则：前12小时打对位，后12小时随意打。", "", "", "", ""],
        ["额外规则：冠二、冠三保级和大一定级管理捐联赛防守援兵给一份额外，壳子管理给一份额外", "", "", "", ""],
        ["额外规则：混营日常捐 部落战防守援兵给一份额外：天下恶魔 Ik8888 日界定", "", "", "", ""],
        ["额外规则：其余按排行榜从上往下分配，壳子中多次向下偷星的跳过", "", "", "", ""],
        ["", "", "", "", ""],
        ["报名填以下收集表", "", "", "", ""],
        ["【腾讯文档】苍穹联盟联赛报名表（正式）", "", "", "", ""],
        ["https://docs.qq.com/form/page/DUnlNeWlyQ21RVElX", "", "", "", ""],
        ["", "", "", "", ""],
        ["这里仅展示最终报名结果", "", "", "", ""],
        ["月底30号这里展示联赛安排，等群里通知", "", "", "", ""],
        ["", "", "", "", ""],
        ["Excel工作薄", "", "", "", ""],
        ["sheet名称", "\"公式一\"", "", "", ""],
        ["", "", "", "", ""],
    ]

    def publish_part4_to_doc(
        self,
        period: str,
        publish_doc_id: str,
    ) -> str:
        """将 Part4（联赛名单排布网格）发布到最终报名结果公示文档。

        文档结构：前 20 行固定文字 + 第 21 行起为 Part4 队伍编排网格。
        数据来源：与 arrange_and_export 一致，走 arrange() → 排序/填充/升降级。

        Args:
            period: 联赛月份，如 "2026-08"
            publish_doc_id: 目标腾讯文档 fileId

        Returns:
            实际创建的 sheet 名称
        """
        from shared.io_adapter.tencent_doc import TencentDocAdapter
        if not isinstance(self.excel_io, TencentDocAdapter):
            raise RuntimeError("publish_part4_to_doc 仅支持腾讯文档适配器")

        # 1. 计算目标 sheet 名
        y, m = period.split("-")
        short_year = y[2:]
        month_num = str(int(m))
        sheet_name = f"{short_year}.{month_num}月联赛 报名结果"

        # 2. 走完整编排流程（排序/填充/升降级），与 arrange_and_export 数据一致
        _ordered, team_results, _movements, _star_data = self.arrange(period)

        # 3. 生成 Part4 网格（5 列）
        grid, title_indices = self._build_part4_grid(team_results)

        # 4. 拼接：前 20 行固定文字 + Part4 网格
        combined_rows = self.PUBLISH_FIXED_ROWS + grid

        # 5. 计算需要的行列数
        need_cols = max((len(row) for row in combined_rows), default=1) or 1
        need_rows = len(combined_rows)

        # 6. 写入目标文档（队伍抬头行红色字体）
        fixed_count = len(self.PUBLISH_FIXED_ROWS)
        highlight_rows = {fixed_count + idx for idx in title_indices}
        self._write_publish_sheet(
            publish_doc_id, sheet_name, combined_rows, need_rows, need_cols,
            highlight_rows=highlight_rows,
        )

        return sheet_name

    def _write_publish_sheet(
        self,
        doc_id: str,
        sheet_name: str,
        combined_rows: list[list[str]],
        row_count: int,
        col_count: int,
        highlight_rows: set[int] | None = None,
    ) -> None:
        """直接将 2D 数据写入腾讯文档（跳过 write_sheet 的 dict 转换）。

        highlight_rows: 需要红色字体的行索引集合（0-based）。
        """
        from shared.io_adapter.tencent_doc import TencentDocAdapter
        adapter = self.excel_io

        # 先查是否已有同名 sheet，有则删后重建
        props = adapter._list_sheets(doc_id)
        existing = adapter._find_sheet(props, sheet_name)
        if existing is not None:
            sheet_id = adapter._recreate_sheet(
                doc_id, existing["sheetId"], sheet_name, row_count, col_count
            )
        else:
            sheet_id = adapter._add_sheet(
                doc_id, sheet_name, row_count=row_count, col_count=col_count
            )

        # 转换为腾讯文档 cell 格式并写入
        _highlight = highlight_rows or set()
        red_fmt = {"fontColor": {"red": 255, "green": 0, "blue": 0, "alpha": 255}}
        matrix = [
            [adapter._cell(v, red_fmt if i in _highlight else None) for v in row]
            for i, row in enumerate(combined_rows)
        ]
        adapter._write_range(doc_id, sheet_id, matrix)
