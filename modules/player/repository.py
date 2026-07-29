"""player 数据访问层：accounts 表。

只负责 accounts 表的 CRUD，所有 SQL 参数绑定。持有 shared.db 的共享连接。
业务模块不直接用本类，而是通过 PlayerService。

字段分组（COC 权威组 vs 报名/战绩组）互不覆盖，靠 upsert 的 COALESCE 语义实现：
更新时只有"本次传入的非 NULL 字段"才覆盖旧值，未传入的字段（None）保持原样。
因此 coc_sync 只传 COC 组、报名只传报名组，各写各的、互不清零。
（代价：无法把某列显式清空为 NULL；本域无此需求。history_score 仍走独立方法。）
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from shared.db.connection import now_iso

# upsert 覆盖的列（不含主键 player_tag / history_score / updated_at，另行处理）
# 瘦身后：account_type/camp_order/latest_match_value/join_combat 已下沉 registrations，
# last_reg_period 改由 registrations 实时派生，均不再经 accounts upsert。
_UPSERT_COLS = (
    "account_name",
    "exp_level",
    "trophies",
    "league_name",
    "town_hall_level",
    "clan_tag",
    "clan_role",
    "coc_raw",
    "last_synced_at",
    "membership_status",
    "player_name",
    "status",
)

# 读取账号时实时派生"最后报名月份"= 该账号报名记录的最大 period（不再落列）。
# B 方案下 registrations 以 account_name 为主标识（无 FK），故按昵称关联而非 player_tag。
_LAST_REG_PERIOD = (
    "(SELECT MAX(period) FROM registrations r "
    "WHERE r.account_name = accounts.account_name) AS last_reg_period"
)
_SELECT_ACCOUNT = f"SELECT accounts.*, {_LAST_REG_PERIOD} FROM accounts"


class PlayerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, account: dict) -> None:
        """插入或更新账号档案（以 player_tag 为主键）。

        字段分组更新：ON CONFLICT 时每列取 COALESCE(excluded.col, 旧值)，
        即只有本次传入的非 NULL 值才覆盖，未传入的字段保持原样。这样：
        - coc_sync 只传 COC 组字段，不会清空报名/战绩字段；
        - 报名只传报名组字段，不会清空 COC 字段。
        history_score 不在此覆盖（由战绩模块单独更新），避免报名/同步把历史分清零。
        """
        raw = account.get("coc_raw")
        if isinstance(raw, (dict, list)):
            raw = json.dumps(raw, ensure_ascii=False)

        values = {
            "account_name": account.get("account_name"),
            "exp_level": account.get("exp_level"),
            "trophies": account.get("trophies"),
            "league_name": account.get("league_name"),
            "town_hall_level": account.get("town_hall_level"),
            "clan_tag": account.get("clan_tag"),
            "clan_role": account.get("clan_role"),
            "coc_raw": raw,
            "last_synced_at": account.get("last_synced_at"),
            "membership_status": account.get("membership_status"),
            "player_name": account.get("player_name"),
            "status": account.get("status"),
        }

        insert_cols = ["player_tag", *_UPSERT_COLS, "updated_at"]
        # UPDATE 覆盖：每列取 COALESCE(excluded.col, 旧值)，只有本次传入的非 NULL 值才覆盖。
        set_clause = ", ".join(
            f"{c} = COALESCE(excluded.{c}, accounts.{c})" for c in _UPSERT_COLS
        )
        sql = f"""
        INSERT INTO accounts ({", ".join(insert_cols)})
        VALUES ({", ".join("?" for _ in insert_cols)})
        ON CONFLICT(player_tag) DO UPDATE SET
            {set_clause},
            updated_at = excluded.updated_at
        """
        # 参数顺序须与 SQL 中 ? 出现顺序一致：player_tag + 各列 + updated_at。
        params = [
            account["player_tag"],
            *(values[c] for c in _UPSERT_COLS),
            now_iso(),
        ]
        self.conn.execute(sql, params)
        self.conn.commit()

    def get(self, player_tag: str) -> Optional[dict]:
        row = self.conn.execute(
            f"{_SELECT_ACCOUNT} WHERE player_tag = ?", (player_tag,)
        ).fetchone()
        return dict(row) if row else None

    def find_by_name(self, account_name: str) -> list[dict]:
        """按游戏昵称查账号（可能有多个：改名/重名/临时+真实并存）。"""
        if not account_name:
            return []
        rows = self.conn.execute(
            f"{_SELECT_ACCOUNT} WHERE account_name = ?", (account_name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(_SELECT_ACCOUNT).fetchall()
        return [dict(r) for r in rows]

    def list_by_clan_tags(self, clan_tags) -> list[dict]:
        """按当前所在部落批量查真实账号（退部对账用）。

        clan_tags 需为已规范化的 tag 可迭代对象；空集合返回 []（避免 IN () 语法错误）。
        """
        tags = [t for t in dict.fromkeys(clan_tags) if t]
        if not tags:
            return []
        placeholders = ", ".join("?" for _ in tags)
        rows = self.conn.execute(
            f"{_SELECT_ACCOUNT} WHERE clan_tag IN ({placeholders})",
            tags,
        ).fetchall()
        return [dict(r) for r in rows]

    def set_clan_membership(
        self, player_tag: str, clan_tag: Optional[str],
        clan_role: Optional[str], membership_status: str,
    ) -> None:
        """显式更新玩家的部落归属与联盟成员身份（退部对账用）。

        与 upsert 的 COALESCE 语义不同：此处为显式 SET，允许把 clan_tag/clan_role
        清空为 NULL（玩家已无部落）。仅动这三列，不触碰 COC 属性(等级/奖杯)、
        报名/战绩组与 history_score。
        """
        self.conn.execute(
            "UPDATE accounts SET clan_tag = ?, clan_role = ?, "
            "membership_status = ?, updated_at = ? WHERE player_tag = ?",
            (clan_tag, clan_role, membership_status, now_iso(), player_tag),
        )
        self.conn.commit()

    def update_status(self, player_tag: str, status: str) -> None:
        self.conn.execute(
            "UPDATE accounts SET status = ?, updated_at = ? WHERE player_tag = ?",
            (status, now_iso(), player_tag),
        )
        self.conn.commit()

    def update_history_score(self, player_tag: str, score: float) -> None:
        self.conn.execute(
            "UPDATE accounts SET history_score = ?, updated_at = ? WHERE player_tag = ?",
            (score, now_iso(), player_tag),
        )
        self.conn.commit()
