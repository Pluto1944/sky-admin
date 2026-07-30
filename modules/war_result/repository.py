"""war_result 数据访问层：results 表。

只负责 results 表读写，参数绑定 SQL，持有 shared.db 的共享连接。
add_result 走 upsert：(player_tag, period, league_type) 唯一，同月同类型战绩
重复导入时覆盖而非累积（修复隐患 #1）。
"""
from __future__ import annotations

import json
import sqlite3


class ResultRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_result(self, result: dict) -> int:
        """插入/更新一条战绩。(player_tag, period, league_type) 唯一，重复导入覆盖。

        注意：league_type 为 NULL 时，SQLite 的 UNIQUE 不把多个 NULL 视为冲突，
        因此同账号同月多条"无联赛类型"战绩会各自保留——这符合"类型未知先都留着"
        的直觉；一旦填了具体类型即按类型去重覆盖。
        """
        metrics = result.get("raw_metrics", {})
        sql = """
        INSERT INTO results (player_tag, period, league_type, raw_metrics)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_tag, period, league_type) DO UPDATE SET
            raw_metrics = excluded.raw_metrics
        """
        cur = self.conn.execute(
            sql,
            (
                result["player_tag"],
                result["period"],
                result.get("league_type"),
                json.dumps(metrics, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_results(self, player_tag: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM results WHERE player_tag = ?", (player_tag,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_results_by_period(
        self, period: str, league_type: str | None = None
    ) -> list[dict]:
        """按月份（+ 可选联赛类型）批量查战绩，供升降级读取上月星数。

        league_type=None 时返回该月全部战绩；指定时按类型过滤。
        """
        if league_type is not None:
            rows = self.conn.execute(
                "SELECT * FROM results WHERE period = ? AND league_type = ?",
                (period, league_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM results WHERE period = ?", (period,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["raw_metrics"] = json.loads(d["raw_metrics"]) if d["raw_metrics"] else {}
        return d
