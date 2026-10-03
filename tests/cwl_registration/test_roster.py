"""集成测试：生成名单（roster，v3.1 基准重建方案）。"""
from __future__ import annotations

from config import ARRANGEMENT_OUTPUT_HEADERS, LEAGUE_COMBAT, LEAGUE_SHELL
from modules.cwl_registration.roster import LeagueArranger
from tests.fakes import FakeExcelIO, seed_registrations


def _teams(combat_capacity: int = 2) -> list[dict]:
    """返回与生产容量解耦的小型测试队伍。"""
    return [
        {
            "name": "实战测试队",
            "clan_tag": "#TEST1",
            "leader": "leader1",
            "member_count": combat_capacity,
            "league_level": "Champion League III",
            "manager": "",
            "category": LEAGUE_COMBAT,
            "reserved_slots": 0,
        },
        {
            "name": "壳子测试队",
            "clan_tag": "#TEST2",
            "leader": "leader2",
            "member_count": 2,
            "league_level": "Master League I",
            "manager": "",
            "category": LEAGUE_SHELL,
            "reserved_slots": 0,
        },
    ]


def _arranger(player_service, reg_repo, excel_io=None) -> LeagueArranger:
    """构造不访问 COC 网络的编排器，并提供稳定的官方部落展示名。"""
    arranger = LeagueArranger(player_service, reg_repo, excel_io or FakeExcelIO())
    arranger._fetch_clan_info = lambda tags: {
        tag: (f"官方部落{tag[-1]}", f"官方首领{tag[-1]}") for tag in tags
    }
    return arranger


def _seed(player_service, reg_repo):
    seed_registrations(player_service, reg_repo, "2026-08", [
        # 普通实战，高分
        {"player_tag": "#A", "account_name": "甲", "account_type": "normal",
         "match_value": 90, "join_combat": True, "history_score": 90},
        # 战营，低分（应排最前）
        {"player_tag": "#B", "account_name": "乙", "account_type": "combat",
         "match_value": 10, "join_combat": True, "history_score": 10},
        # 壳子
        {"player_tag": "#C", "account_name": "丙", "account_type": "normal",
         "match_value": 100, "join_combat": False, "history_score": 100},
    ])


def test_arrange_assigns_teams(player_service, reg_repo):
    """容量充足时，每人应按线性名单落入对应的实战或壳子队。"""
    _seed(player_service, reg_repo)
    arranger = _arranger(player_service, reg_repo)
    teams = _teams()

    ordered, team_results, _movements, _star_data = arranger.arrange(
        "2026-08", teams=teams, combat_min_match_value=0
    )

    # cur_team / team_alias 表示编排归属；team_name 是 COC 官方展示名。
    assigned = [x for x in ordered if x.get("player_tag")]
    assert all(x.get("cur_team") and x.get("team_alias") for x in assigned)
    assert all(x.get("team_name") for x in assigned)

    # 应有 combat 和 shell 两种 league_type
    assert {x["league_type"] for x in assigned} == {
        LEAGUE_COMBAT,
        LEAGUE_SHELL,
    }

    assert len(team_results) == len(teams)


def test_arrange_fills_combat_shortage_from_shell_pool(player_service, reg_repo):
    """现行规则：统一线性名单填队，实战容量有缺口时壳子成员向前补位。"""
    _seed(player_service, reg_repo)
    arranger = _arranger(player_service, reg_repo)

    ordered, team_results, _movements, _star_data = arranger.arrange(
        "2026-08", teams=_teams(combat_capacity=3), combat_min_match_value=0
    )

    assert [m["account_name"] for m in team_results[0]["members"]] == [
        "乙",
        "甲",
        "丙",
    ]
    assert team_results[1]["members"] == []
    assigned = {item["account_name"]: item for item in ordered}
    assert assigned["丙"]["league_type"] == LEAGUE_COMBAT
    assert assigned["丙"]["team_alias"] == "实战测试队"


def test_arrange_writes_back_to_repo(player_service, reg_repo):
    """验证回写 league_type / rank_order / team_info 到 registrations。"""
    _seed(player_service, reg_repo)
    arranger = _arranger(player_service, reg_repo)
    arranger.arrange("2026-08", teams=_teams(), combat_min_match_value=0)

    regs = {r["player_tag"]: r for r in reg_repo.get_registrations("2026-08")}
    # 战营账号应为 combat
    assert regs["#B"]["league_type"] == LEAGUE_COMBAT
    assert regs["#B"]["team_info"] is not None
    # 壳子账号应为 shell
    assert regs["#C"]["league_type"] == LEAGUE_SHELL
    assert regs["#C"]["team_info"] is not None


def test_rerun_clears_stale_assignment_for_new_blacklist(
    player_service, reg_repo, monkeypatch
):
    """重跑新增黑名单时，被过滤账号不应保留上一次的队伍信息。"""
    _seed(player_service, reg_repo)
    arranger = _arranger(player_service, reg_repo)
    arranger.arrange("2026-08", teams=_teams(), combat_min_match_value=0)

    before = {
        r["player_tag"]: r for r in reg_repo.get_registrations("2026-08")
    }
    assert before["#B"]["team_info"] is not None

    monkeypatch.setattr("modules.cwl_registration.roster.BLACK_LIST", {"乙"})
    ordered, _teams_result, _movements, _stars = arranger.arrange(
        "2026-08", teams=_teams(), combat_min_match_value=0
    )

    after = {
        r["player_tag"]: r for r in reg_repo.get_registrations("2026-08")
    }
    assert "乙" not in {item["account_name"] for item in ordered}
    assert after["#B"]["league_type"] is None
    assert after["#B"]["rank_order"] is None
    assert after["#B"]["team_info"] is None


def test_load_previous_combat_includes_final_rank_order(
    player_service, reg_repo
):
    """同战绩候选应能读取上月最终顺序作为稳定决胜项。"""
    seed_registrations(
        player_service,
        reg_repo,
        "2026-07",
        [
            {
                "player_tag": "#A",
                "account_name": "甲",
                "account_type": "normal",
                "match_value": 90,
                "join_combat": True,
            },
            {
                "player_tag": "#B",
                "account_name": "乙",
                "account_type": "normal",
                "match_value": 80,
                "join_combat": True,
            },
        ],
    )
    regs = {r["player_tag"]: r for r in reg_repo.get_registrations("2026-07")}
    reg_repo.update_arrangement(regs["#A"]["id"], LEAGUE_COMBAT, 1)
    reg_repo.update_arrangement(regs["#B"]["id"], LEAGUE_COMBAT, 2)
    reg_repo.conn.executemany(
        """
        INSERT INTO league_results
            (period, team_index, team_alias, category, player_tag,
             account_name, total_stars, attacks, appearances, missed_attacks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("2026-07", 0, "T0", LEAGUE_COMBAT, "#B", "乙", 15, 5, 7, 2),
            ("2026-07", 0, "T0", LEAGUE_COMBAT, "#A", "甲", 15, 5, 6, 1),
        ],
    )
    reg_repo.conn.commit()

    previous = _arranger(player_service, reg_repo)._load_prev_combat_from_league_results(
        "2026-07"
    )

    ranks = {member["player_tag"]: member["rank_order"] for member in previous}
    assert ranks == {"#A": 1, "#B": 2}
    attendance = {
        member["player_tag"]: (member["appearances"], member["missed_attacks"])
        for member in previous
    }
    assert attendance == {"#A": (6, 1), "#B": (7, 2)}


def test_arrange_and_export_writes_sheet(player_service, reg_repo):
    """验证 arrange_and_export 写入 sheet。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = _arranger(player_service, reg_repo, fake_io)

    ordered, team_results, _movements, sheet_name = arranger.arrange_and_export(
        "2026-08", "名单.xlsx", teams=_teams(), combat_min_match_value=0
    )

    assert sheet_name == "名单_2026-08"
    assert fake_io.last_written_target == "名单.xlsx"
    assert fake_io.last_written_sheet == "名单_2026-08"
    assert fake_io.last_written_headers == ARRANGEMENT_OUTPUT_HEADERS
    # 导出行应包含排序名单部分
    written_rows = fake_io.last_written_rows
    assert written_rows is not None
    # 前 3 行应为排序名单（3 个报名成员）
    written_tags = [r["player_tag"] for r in written_rows[:3]]
    assert set(written_tags) == {"#A", "#B", "#C"}


def test_arrange_and_export_contains_team_sections(player_service, reg_repo):
    """导出应包含队伍分配区域。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = _arranger(player_service, reg_repo, fake_io)

    arranger.arrange_and_export(
        "2026-08", "名单.xlsx", teams=_teams(), combat_min_match_value=0
    )

    written_rows = fake_io.last_written_rows
    # 应有"=== 战队分配 ==="分隔行
    titles = [r["rank_order"] for r in written_rows]
    assert any("战队分配" in str(t) for t in titles if t)


def test_arrange_and_export_appends_part4_grid(player_service, reg_repo):
    """Part4 应通过独立网格写入接口追加，而不是混入字典行。"""
    _seed(player_service, reg_repo)
    fake_io = FakeExcelIO()
    arranger = _arranger(player_service, reg_repo, fake_io)
    captured: dict = {}

    def capture_part4(target, sheet_name, grid, title_indices):
        captured.update(
            target=target,
            sheet_name=sheet_name,
            grid=grid,
            title_indices=title_indices,
        )

    arranger._append_part4_to_sheet = capture_part4

    arranger.arrange_and_export(
        "2026-08", "名单.xlsx", teams=_teams(), combat_min_match_value=0
    )

    assert captured["target"] == "名单.xlsx"
    assert captured["sheet_name"] == "名单_2026-08"
    assert captured["title_indices"]
    assert all(len(row) == 5 for row in captured["grid"])
    titles = [captured["grid"][i][0] for i in captured["title_indices"]]
    assert any("实战: 实战测试队" in title for title in titles)
    assert any("壳子: 壳子测试队" in title for title in titles)
