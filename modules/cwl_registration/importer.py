"""报名模块 · 功能①：导入报名结果并更新到 player 模块。

真实报名表特点（见 DESIGN/数据勘察）：
- 一次提交可填多个账号：归属信息（主号/提交时间等）合并在首行，账号逐行排列，
  因此读取时需 fill_merged=True 把合并值向下填充。
- 没有稳定的"玩家Tag"列：过渡期用账号名（游戏昵称）临时充当 player_tag。
- 报名表本身不含账号类型：普通账号来自报名表，战营账号来自战营部落 #2QQ 的 COC
  成员（不再依赖报名表的战营名单 sheet）；两处可能重复（战营成员也报名到普通
  部落），此时以战营为准（combat 优先）。

流程：
1. 读报名表（合并填充）-> 解析多账号 -> 同名(tag)按提交时间取最新去重（打印告警）。
2. 从 accounts 表拉取战营部落（CAMP_CLAN_TAG）成员，经排除名单（EXCLUDED_CAMP_NAMES）
   过滤后得到战营账号集合。（导入前应先 coc-sync 该部落，保证成员与奖杯为最新。）
3. 合并：战营优先（combat、强制实战），普通账号来自报名表。
4. 账号档案通过 PlayerService 更新；报名快照写入 RegistrationRepository；最后刷新状态。

依赖通过构造函数注入（PlayerService + RegistrationRepository + ExcelIO），便于测试。
"""
from __future__ import annotations

import sys

from modules.cwl_registration.config import (
    CAMP_CLAN_TAG,
    EXCLUDED_CAMP_NAMES,
    JOIN_COMBAT_TRUE_TEXTS,
    REGISTRATION_COLUMN_KEYWORDS,
)
from modules.cwl_registration.repository import RegistrationRepository
from modules.player.service import PlayerService
from shared.columns import clean_str, resolve_columns, to_float
from shared.config.common import ACCOUNT_TYPE_COMBAT, ACCOUNT_TYPE_NORMAL
from shared.io_adapter.base import ExcelIO


def _parse_join_combat(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in JOIN_COMBAT_TRUE_TEXTS


def parse_registration_row(raw: dict, colmap: dict | None = None) -> dict | None:
    """把一行原始报名数据解析为标准报名记录（纯函数，便于测试）。

    colmap 为 None 时自动按关键词从 raw 的表头解析列。
    缺少账号名（报名事实主标识）的行返回 None（跳过）。真实账号 Tag 的关联缓存
    不在解析阶段处理，统一由 _save 经 resolve_tag_by_name 反查回填。
    """
    if colmap is None:
        colmap = resolve_columns(list(raw.keys()), REGISTRATION_COLUMN_KEYWORDS)

    def cell(field):
        col = colmap.get(field)
        return raw.get(col) if col else None

    account_name = clean_str(cell("account_name"))
    if account_name is None:
        return None

    return {
        "account_name": account_name,
        "player_name": clean_str(cell("player_name")),
        "match_value": to_float(cell("match_value")),
        "join_combat": _parse_join_combat(cell("join_combat")),
        "submit_time": cell("submit_time"),
        "account_type": ACCOUNT_TYPE_NORMAL,
        "prev_rank": None,
    }


def _submit_key(record: dict):
    """去重排序键：提交时间越大越新；None 视为最早。"""
    st = record.get("submit_time")
    return (st is not None, str(st) if st is not None else "")


def _fill_player_name_forward(records: list[dict]) -> list[dict]:
    """兜底：主号列未按真·合并单元格展开时，按物理行顺序把空主号向前填充为
    最近一个非空主号。

    真实报名表「一次提交的多账号连续排列」，同组账号在物理行上相邻，因此空主号
    会被填充为紧邻上一有值行的主号，对齐"一对多"归属关系。此逻辑源无关，同时覆盖
    本地 xlsx 没真合并、腾讯文档 API 未展开两种情形。

    仅对"紧邻上一有值行"的空行填充；若某组首行本身就漏填主号，会错误并入上一组
    （纯数据问题，概率低，且原 fill_merged 同此局限）。
    """
    last_name = None
    for r in records:
        name = r.get("player_name")
        if name:
            last_name = name
        elif last_name:
            r["player_name"] = last_name
    return records


class RegistrationImporter:
    def __init__(
        self,
        player_service: PlayerService,
        reg_repo: RegistrationRepository,
        excel_io: ExcelIO,
    ):
        self.player_service = player_service
        self.reg_repo = reg_repo
        self.excel_io = excel_io

    def import_from(
        self,
        source: str,
        period: str,
        sheet: str | None = None,
    ) -> int:
        """导入报名表并合并战营名单（从战营部落 DB 拉取），返回落库的账号数。

        战营名单不再从 Excel sheet 读取，而是从 accounts 表按 CAMP_CLAN_TAG 拉取当前
        成员（导入前应先 coc-sync 该部落刷新成员与奖杯）。
        """
        reg_rows = self.excel_io.read_sheet(source, sheet, fill_merged=True)
        parsed = [r for r in (parse_registration_row(raw) for raw in reg_rows) if r]
        # 兜底：源表未真正使用合并单元格（仅视觉留空）时，按物理行向前填充主号
        parsed = _fill_player_name_forward(parsed)

        deduped = self._dedup_latest(parsed)
        camp_names = self._read_camp()
        accounts = self._merge_camp(deduped, camp_names)

        for acc in accounts:
            self._save(acc, period)

        registered_names = {
            r["account_name"] for r in self.reg_repo.get_registrations(period)
        }
        self.player_service.refresh_status(period, registered_names)
        return len(accounts)

    def _dedup_latest(self, records: list[dict]) -> list[dict]:
        """同一账号名重复时保留提交时间最新的一条，并打印告警。"""
        best: dict[str, dict] = {}
        dup_names: dict[str, int] = {}
        for rec in records:
            name = rec["account_name"]
            if name in best:
                dup_names[name] = dup_names.get(name, 1) + 1
                if _submit_key(rec) >= _submit_key(best[name]):
                    best[name] = rec
            else:
                best[name] = rec
        for name, cnt in dup_names.items():
            print(
                f"[warn] 报名表存在重复账号名 '{name}'（{cnt} 条），已按提交时间保留最新一条。",
                file=sys.stderr,
            )
        return list(best.values())

    def _read_camp(self) -> set[str]:
        """从战营部落（CAMP_CLAN_TAG）拉取成员昵称集合，经排除名单过滤。

        数据源为 accounts 表（COC 权威建档）：导入前应先 coc-sync 该部落，保证成员
        列表与奖杯为最新。命中 EXCLUDED_CAMP_NAMES 的成员不计入战营名单。
        部落为空时返回空集合并告警（多半是尚未同步）。
        """
        members = self.player_service.list_members_by_clan([CAMP_CLAN_TAG])
        names: set[str] = set()
        for m in members:
            name = clean_str(m.get("account_name"))
            if not name:
                continue
            if name in EXCLUDED_CAMP_NAMES:
                continue
            names.add(name)
        if not names:
            print(
                f"[warn] 战营部落 {CAMP_CLAN_TAG} 未查到成员，战营名单为空"
                f"（是否尚未 coc-sync？）。",
                file=sys.stderr,
            )
        return names

    def _merge_camp(
        self, reg_accounts: list[dict], camp_names: set[str]
    ) -> list[dict]:
        """合并报名账号与战营名单：战营优先（combat、强制实战）。"""
        by_name: dict[str, dict] = {}
        for acc in reg_accounts:
            acc = dict(acc)
            name = acc["account_name"]
            if name in camp_names:
                acc["account_type"] = ACCOUNT_TYPE_COMBAT
                acc["join_combat"] = True
            by_name[name] = acc

        # 战营成员但本月没报名的账号：仍纳入（战营全部实战），无匹配值来源
        for name in camp_names:
            if name in by_name:
                continue
            by_name[name] = {
                "account_name": name,
                "player_name": None,
                "match_value": None,
                "join_combat": True,
                "submit_time": None,
                "account_type": ACCOUNT_TYPE_COMBAT,
                "prev_rank": None,
            }
        return list(by_name.values())

    def _save(self, acc: dict, period: str) -> None:
        """把一条报名账号落库到 registrations（B 方案：报名不建行、不写 accounts）。

        registrations 自持报名事实（account_name / player_name 等），以 account_name 为
        主标识。resolve_tag_by_name 只读反查真实账号：命中就把真实 Tag 缓存到
        registrations.player_tag（供排序阶段直接取分）；查不到（"报名有 / COC 无"的新人）
        也照常落库，player_tag 留空——绝不因此在 accounts 建临时行。coc-sync 后续同步到
        这个人后，下次排序按昵称即可命中真实得分。
        """
        tag = self.player_service.resolve_tag_by_name(acc["account_name"])
        self.reg_repo.add_registration(
            {
                "account_name": acc["account_name"],
                "player_name": acc.get("player_name"),
                "period": period,
                "match_value": acc.get("match_value"),
                "join_combat": acc.get("join_combat"),
                "account_type": acc.get("account_type"),
                "prev_rank": acc.get("prev_rank"),
                "player_tag": tag,
            }
        )
