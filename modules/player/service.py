"""PlayerService —— 玩家中枢的统一对外接口（本次重构的核心）。

其他模块（报名 / 战绩 / coc_sync）**只能通过本服务**读写账号数据，不直接碰
accounts 表。好处：
- 账号状态推断（status_rule）内聚在此，账号状态本就是 player 的属性。
- 各业务模块互不感知，只认识 PlayerService，解耦彻底。
- 未来加"更新前校验 / 权限 / 审计"只需改这一处。

身份主键：走 A 后 player_tag = COC 真实 Tag（以 '#' 开头）。报名/战绩表只有昵称，
经 resolve_tag_by_name 反查真实 Tag 关联。

B 方案：报名导入**不再写 accounts**（registrations 自持报名事实、无 FK），因此不存在
"昵称临时建档 / 合并"这套复杂度——accounts 只由 coc_sync（COC 权威）与 war_result
（history_score）填充，报名侧只读。报名维度状态由 registrations 按昵称实时派生。
"""
from __future__ import annotations

import sys
from typing import Optional

from modules.player.config import MAYBE_LEFT_MONTHS
from modules.player.repository import PlayerRepository
from modules.player.status_rule import infer_status
from shared.config.common import MEMBERSHIP_LEFT, MEMBERSHIP_MEMBER
from shared.db.connection import now_iso


class PlayerService:
    def __init__(self, repo: PlayerRepository):
        self.repo = repo

    # ---- 查询（供 cwl 生成名单、coc_sync 比对、cli 展示用）----
    def get(self, player_tag: str) -> Optional[dict]:
        return self.repo.get(player_tag)

    def list_all(self, status: str | None = None) -> list[dict]:
        accounts = self.repo.list_all()
        if status:
            accounts = [a for a in accounts if a.get("status") == status]
        return accounts

    def resolve_tag_by_name(self, account_name: str) -> Optional[str]:
        """按游戏昵称反查 player_tag（报名/战绩关联真实账号的入口，只读）。

        命中一个真实账号返回其 tag；命中多个时取首个并告警（改名/重名边界，待真实
        Tag 列落地后消除）；再退化到"tag 直接等于该昵称"的历史/兼容账号；都没有返回
        None（B 方案下"报名有 / COC 无"的新人本就没有账号，返回 None 属正常）。
        """
        if not account_name:
            return None
        matches = self.repo.find_by_name(account_name)
        if matches:
            if len(matches) > 1:
                print(
                    f"[warn] 昵称 '{account_name}' 对应多个 COC 账号，取首个：{matches[0]['player_tag']}。",
                    file=sys.stderr,
                )
            return matches[0]["player_tag"]
        direct = self.repo.get(account_name)
        return direct["player_tag"] if direct else None

    def refresh_status(self, current_period: str, registered_names: set[str]) -> None:
        """按"本月是否报名"重新推断全体账号状态（报名维度）。

        registered_names: 本月已报名的账号昵称集合（registrations.account_name）。
        跟踪对象是真实账号（accounts）：以其昵称是否出现在报名/历史报名中来派生。
        "报名有 / COC 无"的新人不在 accounts 里，自然不参与状态推断（他还不是正式成员）。
        最后报名月份改由 registrations 按昵称实时派生（repo 的 last_reg_period）。
        """
        for acc in self.repo.list_all():
            name = acc.get("account_name")
            status = infer_status(
                last_reg_period=acc.get("last_reg_period"),
                current_period=current_period,
                registered_this_period=bool(name) and name in registered_names,
                maybe_left_months=MAYBE_LEFT_MONTHS,
            )
            if status != acc.get("status"):
                self.repo.update_status(acc["player_tag"], status)

    # ---- 战绩模块更新入口 ----
    def update_history_score(self, player_tag: str, score: float) -> None:
        self.repo.update_history_score(player_tag, score)

    # ---- coc_sync 模块更新入口 ----
    def update_from_coc(self, coc_fields: dict) -> None:
        """由 coc_sync 用 COC 官方 API 查得的信息更新账号（COC 为权威建档源）。

        coc_fields 含 player_tag(真实Tag) 及 account_name / exp_level / trophies /
        league_name / town_hall_level / clan_tag / clan_role / coc_raw 等。
        只写 COC 组字段（COALESCE 语义保证不覆盖报名/战绩组），并写入同步时间。
        """
        fields = dict(coc_fields)
        fields["last_synced_at"] = now_iso()
        self.repo.upsert(fields)

    def list_members_by_clan(self, clan_tags) -> list[dict]:
        """查当前归属于给定部落集合的真实账号（退部对账的候选来源）。"""
        return self.repo.list_by_clan_tags(clan_tags)

    def mark_left_alliance(
        self, player_tag: str, new_clan_tag: str | None = None,
        new_clan_role: str | None = None,
    ) -> None:
        """标记账号已退出联盟部落，并记录其新部落（若通过 COC API 查到）。

        membership_status 置 left；clan_tag/clan_role 显式改写为新部落（查不到则清空）。
        不改动 status（报名维度）与 COC 属性/历史分，两套体系互不干扰。
        """
        self.repo.set_clan_membership(
            player_tag, new_clan_tag, new_clan_role, MEMBERSHIP_LEFT
        )

    def relocate_within_alliance(
        self, player_tag: str, clan_tag: str | None, clan_role: str | None = None
    ) -> None:
        """账号仍在联盟内、但转入了本次未同步的部落时，更新其部落归属（仍视为 member）。"""
        self.repo.set_clan_membership(
            player_tag, clan_tag, clan_role, MEMBERSHIP_MEMBER
        )
