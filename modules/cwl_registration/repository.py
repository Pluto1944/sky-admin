"""cwl_registration 数据访问层：registrations 表。

只负责 registrations 表的读写，参数绑定 SQL，持有 shared.db 的共享连接。
B 方案下 registrations 是"报名事实的自包含源"：以 account_name（报名昵称）为主标识，
(account_name, period) 唯一，重复导入时覆盖更新；player_tag 仅为命中真实账号时的
关联缓存（可空、无 FK）。
"""
from __future__ import annotations

import sqlite3
from typing import Optional


class RegistrationRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_registration(self, reg: dict) -> int:
        """新增报名记录。(account_name, period) 唯一，重复导入时覆盖更新。

        account_name 为报名昵称（主标识，必填）；player_name 为主号归属（自持）；
        player_tag 为命中真实账号时缓存的关联（可空）。account_type 为本月账号分类。
        重复导入按 excluded 覆盖（player_tag 命中后也随之更新缓存）。
        """
        sql = """
        INSERT INTO registrations
            (account_name, player_name, period, match_value, join_combat,
             willing_to_manage, account_type, league_type, rank_order, player_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_name, period) DO UPDATE SET
            player_name        = excluded.player_name,
            match_value        = excluded.match_value,
            join_combat        = excluded.join_combat,
            willing_to_manage  = excluded.willing_to_manage,
            account_type       = excluded.account_type,
            player_tag         = COALESCE(excluded.player_tag, registrations.player_tag)
        """
        cur = self.conn.execute(
            sql,
            (
                reg["account_name"],
                reg.get("player_name"),
                reg["period"],
                reg.get("match_value"),
                1 if reg.get("join_combat") else 0,
                1 if reg.get("willing_to_manage") else 0,
                reg.get("account_type"),
                reg.get("league_type"),
                reg.get("rank_order"),
                reg.get("player_tag"),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_period(self, period: str) -> int:
        """删除指定月份的报名快照，避免完整导入后残留旧账号。"""
        cur = self.conn.execute("DELETE FROM registrations WHERE period = ?", (period,))
        self.conn.commit()
        return cur.rowcount

    def get_registrations(self, period: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM registrations WHERE period = ?", (period,)
        ).fetchall()
        return [dict(r) for r in rows]


    def last_period_of(self, account_name: str) -> Optional[str]:
        """该昵称报名过的最后月份（= 其报名记录的最大 period）；从未报名返回 None。

        报名维度状态推断的数据源（替代已废弃的 accounts.last_reg_period）。
        """
        if not account_name:
            return None
        row = self.conn.execute(
            "SELECT MAX(period) AS p FROM registrations WHERE account_name = ?",
            (account_name,),
        ).fetchone()
        return row["p"] if row and row["p"] else None

    def update_arrangement(
        self, reg_id: int, league_type: str, rank_order: int
    ) -> None:
        self.conn.execute(
            "UPDATE registrations SET league_type = ?, rank_order = ? WHERE id = ?",
            (league_type, rank_order, reg_id),
        )
        self.conn.commit()

    def update_team_info(self, reg_id: int, team_info: str) -> None:
        """回写该报名记录分配到哪个队伍。"""
        self.conn.execute(
            "UPDATE registrations SET team_info = ? WHERE id = ?",
            (team_info, reg_id),
        )
        self.conn.commit()

