"""coc_sync 服务：唯一的 COC API 编排出口。

职责边界（满足"所有 API 调用全部经 coc_sync 封装"）：
- api_client 只被本服务内部调用，其它任何模块/脚本不直接 import CocApiClient。
- 本服务负责：遍历多部落、逐部落抓取成员、经 mapper 标准化、按真实 Tag 汇总去重、
  写入 PlayerService（COC 为权威建档源），并对本次成功同步的部落做"退部对账"
  （成员列表里消失的人 -> 查其新部落并标记退部）。
- fetch_clan_members 提供只读预览（探测脚本用），不落库。

注：B 方案下报名导入不再产生"昵称临时账号"，故 coc_sync 无需再做临时账号合并/残留
告警——accounts 完全由 COC 权威建档，报名侧与其解耦。
"""
from __future__ import annotations

import sys

from modules.coc_sync import config as coc_config
from modules.coc_sync.api_client import CocApiClient, CocApiError
from modules.coc_sync.mapper import map_member, normalize_tag
from modules.player.service import PlayerService


class CocSyncService:
    def __init__(
        self,
        player_service: PlayerService | None = None,
        api_client: CocApiClient | None = None,
    ):
        # player_service 仅在写库(sync_*)时必需；只读预览(fetch_*)可不传。
        self.player_service = player_service
        self.api_client = api_client or CocApiClient()

    # ------------------------------------------------------------------
    # 只读预览（探测脚本用，不落库）
    # ------------------------------------------------------------------
    def fetch_clan_members(self, clan_tag: str, clan_name: str | None = None) -> list[dict]:
        """拉取并标准化某部落全部成员（不写库）。"""
        members = self.api_client.get_clan_members(clan_tag)
        return [map_member(m, clan_tag, clan_name) for m in members]

    # ------------------------------------------------------------------
    # 同步落库
    # ------------------------------------------------------------------
    def sync_clans(self, clans: list | None = None) -> dict:
        """遍历部落 -> 抓取成员 -> 标准化 -> 按真实 Tag 汇总去重 -> 写入 player 档案，
        并对本次成功同步的部落做"退部对账"。

        clans: None 时读 config.CLANS（仅 enabled）；也可传 ['#aaa', '#bbb'] 或
        [{'tag','name'}] 覆盖配置（命令行临时指定）。
        返回统计：{clans, members, created, updated, duplicates, left, failed_clans}。
        """
        if self.player_service is None:
            raise ValueError("sync_clans 需要 player_service（只读预览请用 fetch_clan_members）")

        clan_list = self._resolve_clans(clans)
        stats = {
            "clans": 0,
            "members": 0,
            "created": 0,
            "updated": 0,
            "duplicates": 0,
            "left": 0,
            "failed_clans": [],
        }
        seen: dict[str, str] = {}  # 真实 Tag -> 首次出现的部落 tag（跨部落去重）
        synced_clan_tags: set[str] = set()  # 本次成功抓取的部落（规范化 tag），仅对它们对账

        for clan in clan_list:
            tag, name = clan["tag"], clan.get("name")
            try:
                members = self.api_client.get_clan_members(tag)
            except (CocApiError, ValueError) as e:
                print(f"[warn] 部落 {name or tag} 同步失败：{e}", file=sys.stderr)
                stats["failed_clans"].append(tag)
                if coc_config.FAIL_FAST:
                    raise
                continue

            stats["clans"] += 1
            synced_clan_tags.add(normalize_tag(tag))
            for member in members:
                fields = map_member(member, tag, name)
                real_tag = fields["player_tag"]
                if not real_tag:
                    continue
                if real_tag in seen:
                    stats["duplicates"] += 1
                    if coc_config.DUP_ACROSS_CLANS == "warn":
                        print(
                            f"[warn] {fields.get('account_name')}({real_tag}) 同时出现在 "
                            f"{seen[real_tag]} 与 {tag}，已取首个。",
                            file=sys.stderr,
                        )
                    continue
                seen[real_tag] = tag

                existed = self.player_service.get(real_tag) is not None
                self.player_service.update_from_coc(fields)
                stats["updated" if existed else "created"] += 1
                stats["members"] += 1

        # 退部对账：只针对本次成功同步的部落，避免抓取失败的部落误伤其成员
        self._reconcile_left_members(set(seen.keys()), synced_clan_tags, stats)
        return stats

    def _reconcile_left_members(
        self, present_tags: set[str], synced_clan_tags: set[str], stats: dict
    ) -> None:
        """对本次成功同步的部落做退部对账。

        候选 = "上次 clan_tag 属于这些部落、但本轮未出现在成员列表"的真实账号。
        对每个候选调 /players/{tag} 查其当前部落：
        - 新部落仍属联盟（含本次未同步/enabled=False 的部落）-> 只更新归属，不判退部；
        - 新部落非联盟部落或已无部落 -> 标记 membership_status=left，并记录新部落。
        查询失败（网络/限流）时本轮跳过、不改判定，避免误伤，下次同步再对账。
        """
        if not synced_clan_tags:
            return
        alliance = {normalize_tag(t) for t in coc_config.alliance_clan_tags()}
        alliance.discard(None)

        for acc in self.player_service.list_members_by_clan(synced_clan_tags):
            tag = acc["player_tag"]
            if tag in present_tags:
                continue  # 本轮仍在成员列表 -> 未退部
            try:
                player = self.api_client.get_player(tag)
            except (CocApiError, ValueError) as e:
                print(
                    f"[warn] 退部对账查询 {acc.get('account_name')}({tag}) 失败，本轮跳过：{e}",
                    file=sys.stderr,
                )
                continue

            new_clan_tag = normalize_tag((player.get("clan") or {}).get("tag"))
            new_clan_role = player.get("role") if new_clan_tag else None

            if new_clan_tag and new_clan_tag in alliance:
                # 仍在联盟内（转入本次未同步/失败的部落）-> 更新归属，保持 member
                self.player_service.relocate_within_alliance(tag, new_clan_tag, new_clan_role)
                continue

            self.player_service.mark_left_alliance(tag, new_clan_tag, new_clan_role)
            stats["left"] += 1
            where = f"，现所在部落 {new_clan_tag}" if new_clan_tag else "（当前无部落）"
            print(
                f"[info] {acc.get('account_name')}({tag}) 已退出联盟部落{where}。",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_clans(clans: list | None) -> list[dict]:
        """把入参统一成 [{'tag','name'}]。None -> config.CLANS(仅 enabled)。"""
        if clans is None:
            return [
                {"tag": c["tag"], "name": c.get("name")}
                for c in coc_config.CLANS
                if c.get("enabled", True)
            ]
        normalized = []
        for c in clans:
            if isinstance(c, str):
                normalized.append({"tag": c, "name": None})
            else:
                normalized.append({"tag": c["tag"], "name": c.get("name")})
        return normalized
