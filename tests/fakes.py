"""测试替身与辅助：假的 ExcelIO + 报名种子数据助手。

FakeExcelIO：读返回预置行、写记录到内存以供断言，脱离真实文件。
seed_registrations：通过 PlayerService + RegistrationRepository 预置账号与报名，
便于名单编排等集成测试。
"""
from __future__ import annotations

import copy
from typing import Optional


class FakeExcelIO:
    """假的 ExcelIO：读返回预置行，写记录到内存以供断言。

    - 单 sheet 模式：FakeExcelIO(rows)。默认表（sheet=None）返回这批行，命名 sheet 返回 []。
    - 多 sheet 模式：FakeExcelIO(sheets={"报名": [...], "战营名单": [...]})。
      按 sheet 名返回对应行；未配置的 sheet 返回 []。
    """

    def __init__(
        self,
        rows_to_read: Optional[list[dict]] = None,
        sheets: Optional[dict[str, list[dict]]] = None,
    ):
        self._rows_to_read = rows_to_read or []
        self._sheets = sheets
        self.last_written_rows: Optional[list[dict]] = None
        self.last_written_headers: Optional[list[str]] = None
        self.last_written_target: Optional[str] = None
        self.last_written_sheet: Optional[str] = None
        self.last_written_auto_filter: bool = False
        self.last_written_freeze_header: bool = False

    def read_sheet(
        self, source: str, sheet: str | None = None, fill_merged: bool = False
    ) -> list[dict]:
        if self._sheets is not None:
            return copy.deepcopy(self._sheets.get(sheet, []))
        # 单 sheet 模式：仅默认表（sheet=None）返回数据，命名 sheet（如战营名单）返回 []
        return copy.deepcopy(self._rows_to_read) if sheet is None else []

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
        self.last_written_target = target
        self.last_written_rows = copy.deepcopy(rows)
        self.last_written_headers = headers
        self.last_written_sheet = sheet
        self.last_written_auto_filter = auto_filter
        self.last_written_freeze_header = freeze_header


class FakeCocApiClient:
    """假的 COC API 客户端：按部落 tag 返回预置成员，可指定失败部落。

    members_by_clan: {clan_tag: [member_dict, ...]}
    fail_clans:      抓取时抛 CocApiError 的部落集合（测失败隔离）。
    players_by_tag:  {player_tag: player_dict}，供 get_player 退部对账查询新部落用。
    """

    def __init__(
        self,
        members_by_clan: Optional[dict[str, list[dict]]] = None,
        fail_clans: Optional[set[str]] = None,
        players_by_tag: Optional[dict[str, dict]] = None,
    ):
        self._members = members_by_clan or {}
        self._fail = set(fail_clans or ())
        self._players = players_by_tag or {}

    def get_clan_members(self, clan_tag: str) -> list[dict]:
        if clan_tag in self._fail:
            from modules.coc_sync.api_client import CocApiError

            raise CocApiError(f"模拟部落 {clan_tag} 抓取失败")
        return copy.deepcopy(self._members.get(clan_tag, []))

    def get_player(self, player_tag: str) -> dict:
        """按玩家 Tag 返回预置资料；未预置则视为"当前无部落"（已退部/未知）。"""
        return copy.deepcopy(self._players.get(player_tag, {"tag": player_tag}))


def coc_member(tag, name, role="member", exp=100, trophies=3000, th=15, league="传奇"):
    """构造一个 COC 成员原始 dict（贴近官方 /clans/{tag}/members 结构）。"""
    return {
        "tag": tag,
        "name": name,
        "role": role,
        "expLevel": exp,
        "trophies": trophies,
        "townHallLevel": th,
        "league": {"name": league},
    }


def seed_registrations(player_service, reg_repo, period: str, items: list[dict]) -> None:
    """预置账号 + 报名，便于集成测试（B 方案）。

    accounts 只由 COC 权威建档，故用 update_from_coc 建真实账号（供排序阶段按昵称
    反查 tag、读 history_score / trophies）；报名事实写入 registrations（自持
    account_name/player_name/账号类型等），并把真实 tag 缓存到 player_tag。

    items: [{player_tag, account_name, account_type, prev_rank, match_value,
             join_combat, history_score, trophies, clan_tag, player_name}, ...]
    """
    for it in items:
        tag = it["player_tag"]
        coc_fields = {"player_tag": tag, "account_name": it.get("account_name")}
        if "trophies" in it:
            coc_fields["trophies"] = it["trophies"]
        if "clan_tag" in it:
            coc_fields["clan_tag"] = it["clan_tag"]
        player_service.update_from_coc(coc_fields)
        if "history_score" in it:
            player_service.update_history_score(tag, it["history_score"])
        reg_repo.add_registration(
            {
                "account_name": it.get("account_name"),
                "player_name": it.get("player_name"),
                "period": period,
                "match_value": it.get("match_value"),
                "join_combat": it.get("join_combat", False),
                "account_type": it.get("account_type"),
                "prev_rank": it.get("prev_rank"),
                "player_tag": tag,
            }
        )
