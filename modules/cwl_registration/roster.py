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
from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL, MEMBERSHIP_LEFT
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

    def arrange(
        self,
        period: str,
        weights: dict | None = None,
        teams: list[dict] | None = None,
        combat_min_match_value: float | None = None,
        star_data: dict[str, int] | None = None,
    ) -> tuple[list[dict], list[dict], list[dict], dict[str, int]]:
        """生成排序名单 + 队伍分配（含升降级），并回写数据库。

        period 语义：**联赛时间**（实际打 CWL 的月份）。
        报名数据存于 registrations 表，period = 联赛时间（统一语义）。
        CWL 星数存于 results 表，period = CWL 实际发生月 = 联赛时间 - 1 月：
          - arrange("2026-08") → 读 registrations(2026-08) + results(2026-07)
          - arrange("2026-09") → 读 registrations(2026-09) + results(2026-08)

        参数:
            star_data: 实战星数 {account_name: total_stars}。
                显式传入时直接使用（冷启动场景）；为 None 时从 results 表
                按上月 CWL period 自动加载。

        返回:
            (含 team_name 的排序名单, 队伍分配结果列表, 升降级日志列表)
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

        # 升降级：根据上月 CWL 星数交换人员
        # CWL 实际发生月 = 联赛时间 - 1（results.period 语义）
        cwl_period = _prev_period(period)
        movements: list[dict] = []
        if star_data is None and cwl_period:
            star_data = self._load_combat_star_data(cwl_period)
        elif star_data is None:
            star_data = {}

        if star_data:
            team_results, movements = apply_promotion_relegation(
                team_results, star_data, PROMOTION_RELEGATION_CONFIG
            )
            # 交换后重建 ordered_with_team 的 team_name 映射
            rebuild_assignment_map(ordered_with_team, team_results)

            # 注入升降级 + 新人标识到成员数据（供导出展示）
            movement_map: dict[str, str] = {}
            if movements:
                for m in movements:
                    direction = "↑升级" if m["direction"] == "promotion" else "↓降级"
                    movement_map[m["account_name"]] = f"{direction}({m['total_stars']}★)"

            new_count = 0
            shell_count = 0
            for tr in team_results:
                for member in tr["members"]:
                    name = member.get("account_name")
                    if not name:
                        continue
                    if name in movement_map:
                        member["movement"] = movement_map[name]
                    elif tr["category"] == LEAGUE_COMBAT and name not in star_data:
                        member["movement"] = "新"
                        new_count += 1
                    elif tr["category"] == LEAGUE_SHELL and name in star_data:
                        member["movement"] = f"↓转壳({star_data[name]}★)"
                        shell_count += 1
            for item in ordered_with_team:
                name = item.get("account_name")
                if name and name in movement_map:
                    item["movement"] = movement_map[name]

            if movements:
                print("\n[升降级] 本月人员调整：")
                for m in movements:
                    print(
                        f"  {m['account_name']} ({m['total_stars']}星) "
                        f"{movement_map[m['account_name']]}: "
                        f"{m['from_team']} → {m['to_team']}"
                    )

            # 缺席分析：上月有星数但本月不在任何实战队
            combat_names = {
                m.get("account_name")
                for tr in team_results if tr["category"] == LEAGUE_COMBAT
                for m in tr["members"]
            }
            shell_names = {
                m.get("account_name")
                for tr in team_results if tr["category"] == LEAGUE_SHELL
                for m in tr["members"]
            }
            all_absent = [(n, star_data[n]) for n in sorted(star_data)
                          if n in star_data and n not in combat_names]
            to_shell = [(n, s) for n, s in all_absent if n in shell_names]
            absent_not_in_shell = [(n, s) for n, s in all_absent if n not in shell_names]

            # 区分"未报名" vs "离开"：查 accounts.membership_status
            not_registered: list[tuple[str, int]] = []
            left_camp: list[tuple[str, int]] = []
            for name, stars in absent_not_in_shell:
                tag = self.player_service.resolve_tag_by_name(name)
                if tag:
                    acc = self.player_service.get(tag)
                    if acc and acc.get("membership_status") == MEMBERSHIP_LEFT:
                        left_camp.append((name, stars))
                    else:
                        not_registered.append((name, stars))
                else:
                    left_camp.append((name, stars))

            if to_shell:
                print(f"\n[转壳] {len(to_shell)} 人从实战队转到壳子队：")
                for name, stars in to_shell:
                    print(f"  {name} ({stars}星)")
            if not_registered:
                print(f"\n[未报名] {len(not_registered)} 人仍在联盟但未报名：")
                for name, stars in not_registered:
                    print(f"  {name} ({stars}星)")
            if left_camp:
                print(f"\n[离开] {len(left_camp)} 人已退出联盟：")
                for name, stars in left_camp:
                    print(f"  {name} ({stars}星)")

            if new_count:
                print(f"\n[新人] {new_count} 名实战队员本月新进（上月未参赛）")

        # 回写 team_name（升降级后可能已变化）
        for item in ordered_with_team:
            if item.get("reg_id") is not None and item.get("team_name"):
                self.reg_repo.update_team_name(
                    item["reg_id"], item["team_name"]
                )

        return ordered_with_team, team_results, movements, star_data

    def _build_part4_grid(
        self, team_results: list[dict]
    ) -> tuple[list[list[str]], list[int]]:
        """构建 Part4 联赛名单排布网格（备份留底）。

        返回 (grid, title_row_indices):
          - grid: list[list[str]]，每行 5 列，可直接拼入 combined_rows
          - title_row_indices: 抬头行在 grid 中的行索引列表
        """
        grid: list[list[str]] = []
        title_indices: list[int] = []

        for i, tr in enumerate(team_results):
            cat = "实战" if tr["category"] == LEAGUE_COMBAT else "壳子"
            # 记录抬头行索引
            title_indices.append(len(grid))
            # 抬头拆成 3 列：队伍信息 | clan_tag | 空 | 空 | 管理
            cap_info = f"{tr['filled_count']}/{tr['member_count']}"
            col1 = f"{cat}: {tr['team_name']} {cap_info}"
            col2 = tr.get("clan_tag", "")
            col3 = f"管理:{tr.get('manager', '')}"
            grid.append([col1, col2, "", "", col3])

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

        # 第三部分：缺席老兵（上月有星数但本月未进实战队）
        if star_data:
            combat_names = {
                m.get("account_name")
                for tr in team_results if tr["category"] == LEAGUE_COMBAT
                for m in tr["members"]
            }
            shell_names = {
                m.get("account_name")
                for tr in team_results if tr["category"] == LEAGUE_SHELL
                for m in tr["members"]
            }
            all_absent = [(n, star_data[n]) for n in sorted(star_data) if n not in combat_names]
            to_shell = [(n, s) for n, s in all_absent if n in shell_names]
            absent_not_in_shell = [(n, s) for n, s in all_absent if n not in shell_names]

            # 区分"未报名" vs "离开"：查 accounts.membership_status
            not_registered: list[tuple[str, int]] = []
            left_camp: list[tuple[str, int]] = []
            for name, stars in absent_not_in_shell:
                tag = self.player_service.resolve_tag_by_name(name)
                if tag:
                    acc = self.player_service.get(tag)
                    if acc and acc.get("membership_status") == MEMBERSHIP_LEFT:
                        left_camp.append((name, stars))
                    else:
                        not_registered.append((name, stars))
                else:
                    left_camp.append((name, stars))

            if to_shell or not_registered or left_camp:
                # "未报名/离开"人员的原队直接从 results 表查（CWL 星数同源），
                # 替代反查 registrations（后者依赖 arrange 回写 team_name，冷启动易缺失）
                cwl_period = _prev_period(period)
                if cwl_period:
                    prev_teams, team_clan_tags = self._load_combat_team_map(cwl_period)
                else:
                    prev_teams, team_clan_tags = {}, {}
                team_order = [t["name"] for t in (teams or TEAMS)]

                # 构建队伍信息查找表：{name: "泰坦二 (大师一 #2QQ)"}
                _tcfg = teams or TEAMS
                team_info: dict[str, str] = {}
                for t in _tcfg:
                    name = t["name"]
                    parts = [name]
                    extras = [x for x in (t.get("league_level"), t.get("clan_tag")) if x]
                    if extras:
                        parts.append(f"({' '.join(extras)})")
                    info = " ".join(parts)
                    if name in team_info:
                        team_info[name] = f"{team_info[name]} | {info}"
                    else:
                        team_info[name] = info

                # 补充 results 中 TEAMS 配置未列出的队伍（如"大一 A/B/C"）的 clan_tag
                for tn, ct in team_clan_tags.items():
                    if tn not in team_info and ct:
                        team_info[tn] = f"{tn} ({ct})"

                combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})
                combined_rows.append({
                    **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                    "rank_order": f"=== 缺席老兵（共{len(all_absent)}人，上月有CWL星数，本月未进实战队）===",
                })

                tag_map = {"转壳": "↓转壳", "未报名": "未报名", "离开": "离开"}
                for label, group in [("转壳", to_shell), ("未报名", not_registered), ("离开", left_camp)]:
                    if not group:
                        continue

                    combined_rows.append({
                        **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                        "rank_order": f"  [{label}] {len(group)}人",
                    })

                    # 按原队分组
                    by_team: dict[str, list[tuple[str, int]]] = {}
                    for name, stars in group:
                        t = prev_teams.get(name, "未知")
                        by_team.setdefault(t, []).append((name, stars))

                    ordered_t = [t for t in team_order if t in by_team] + \
                                [t for t in sorted(by_team) if t not in team_order]
                    for t in ordered_t:
                        members = by_team[t]
                        t_display = team_info.get(t, t)
                        for name, stars in sorted(members, key=lambda x: -x[1]):
                            combined_rows.append({
                                **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
                                "account_name": name,
                                "player_tag": self.player_service.resolve_tag_by_name(name),
                                "movement": f"{tag_map[label]}({stars}★)",
                                "team_name": t_display,
                            })
                        # 队伍之间空行
                        combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

        # ===== Part 4: 联赛名单排布（备份留底） =====
        _PART4_COLS = ARRANGEMENT_OUTPUT_HEADERS[:5]
        combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})
        combined_rows.append({
            **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
            "rank_order": "=== 联赛名单排布（备份留底） ===",
        })

        grid, title_indices = self._build_part4_grid(team_results)
        # 计算抬头行在 combined_rows 中的绝对索引（Part4 标题占 2 行 + grid 偏移）
        part4_start = len(combined_rows)
        highlight_rows = {part4_start + idx for idx in title_indices}

        for row in grid:
            combined_rows.append({
                **{h: "" for h in ARRANGEMENT_OUTPUT_HEADERS},
                **{_PART4_COLS[k]: row[k] for k in range(min(5, len(row)))},
            })

        sheet_name = sheet or f"名单_{period}"
        self.excel_io.write_sheet(
            target,
            combined_rows,
            headers=ARRANGEMENT_OUTPUT_HEADERS,
            sheet=sheet_name,
            highlight_rows=highlight_rows,
        )
        return ordered, team_results, movements, sheet_name

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

        # 3. 生成 Part4 网格
        grid, _title_indices = self._build_part4_grid(team_results)

        # 4. 拼接：前 20 行固定文字 + Part4 网格
        combined_rows = self.PUBLISH_FIXED_ROWS + grid

        # 5. 计算需要的行列数
        need_cols = max((len(row) for row in combined_rows), default=1) or 1
        need_rows = len(combined_rows)

        # 6. 写入目标文档
        self._write_publish_sheet(
            publish_doc_id, sheet_name, combined_rows, need_rows, need_cols
        )

        return sheet_name

    def _write_publish_sheet(
        self,
        doc_id: str,
        sheet_name: str,
        combined_rows: list[list[str]],
        row_count: int,
        col_count: int,
    ) -> None:
        """直接将 2D 数据写入腾讯文档（跳过 write_sheet 的 dict 转换）。

        直接使用 TencentDocAdapter 的底层 API，避免 dict 格式转换的开销。
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
        matrix = [
            [adapter._cell(v) for v in row]
            for row in combined_rows
        ]
        adapter._write_range(doc_id, sheet_id, matrix)
