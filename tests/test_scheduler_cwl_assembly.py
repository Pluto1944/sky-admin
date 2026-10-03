import json
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from modules.coc_sync.service import CocSyncService
from scripts.scheduler import _run_cwl_assembly
from shared.db.connection import Database
from shared.io_adapter.tencent_doc import TencentDocAdapter


TZ = ZoneInfo("Asia/Shanghai")


def _seed_teams(path):
    db = Database(str(path))
    db.init_schema()
    for index, tag in enumerate(("#AAA", "#BBB")):
        db.conn.execute(
            """INSERT INTO league_teams
               (period, team_index, team_alias, team_name, clan_tag, category, member_count, leader)
               VALUES ('2026-10', ?, ?, ?, ?, 'combat', 5, ?)""",
            (index, f"队伍{index + 1}", f"部落{index + 1}", tag, f"首领简称{index + 1}"),
        )
    db.conn.commit()
    db.close()


def _published_rows():
    return [
        {"苍穹联赛报名": "实战:队伍1 5/5", "col1": "#AAA", "col2": "部落1", "col3": "首领:首领完整1", "col4": "管理:管A 开战/捐兵给一份额外"},
        {"苍穹联赛报名": "甲", "col1": "乙", "col2": "丙", "col3": "丁", "col4": "戊"},
        {"苍穹联赛报名": "实战:队伍2 5/5", "col1": "#BBB", "col2": "部落2", "col3": "", "col4": ""},
        {"苍穹联赛报名": "己", "col1": "庚", "col2": "辛", "col3": "壬", "col4": "癸"},
    ]


def test_assembly_scheduler_snapshots_once_freezes_started_and_preserves_cache(tmp_path, monkeypatch):
    db_path = tmp_path / "league.db"
    _seed_teams(db_path)
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    monkeypatch.setenv("PUBLISH_DOC_FILE_ID", "fake-file")
    reads = []
    monkeypatch.setattr(
        TencentDocAdapter,
        "read_sheet",
        lambda self, source, sheet: reads.append((source, sheet)) or _published_rows(),
    )

    fail_b = {"value": False}

    def fetch_members(self, clan_tag, clan_name=None):
        if clan_tag == "#BBB" and fail_b["value"]:
            raise RuntimeError("temporary")
        names = ["甲", "乙", "丙", "丁", "戊"] if clan_tag == "#AAA" else ["己", "庚", "辛", "壬", "额外"]
        return [
            {"account_name": name, "player_tag": f"#{clan_tag[-1]}{i}", "clan_role": "member", "town_hall_level": 17}
            for i, name in enumerate(names)
        ]

    monkeypatch.setattr(CocSyncService, "fetch_clan_members", fetch_members)
    monkeypatch.setattr(
        CocSyncService,
        "fetch_cwl_group",
        lambda self, team: {"season": "2026-10"} if team["clan_tag"] == "#AAA" else None,
    )

    first = _run_cwl_assembly(now=datetime(2026, 10, 2, 10, 0, tzinfo=TZ))
    assert first["status"] == "success"
    assert len(reads) == 1

    db = Database(str(db_path))
    rows = {
        row["clan_tag"]: dict(row)
        for row in db.conn.execute("SELECT * FROM cwl_assembly_cache ORDER BY clan_tag")
    }
    assert rows["#AAA"]["status"] == "started"
    assert rows["#AAA"]["locked_at"]
    assert rows["#BBB"]["status"] == "checking"
    before = json.loads(rows["#BBB"]["data_json"])
    assert before["missing_count"] == 1
    assert before["extra_count"] == 1
    first_locked_at = rows["#AAA"]["locked_at"]
    first_snapshot_id = rows["#AAA"]["roster_snapshot_id"]
    db.close()

    # 仅抬头元数据变化的强制 revision 不得清空或重算已经冻结的集结结果。
    refreshed = _run_cwl_assembly(force=True, now=datetime(2026, 10, 2, 10, 1, tzinfo=TZ))
    assert refreshed["status"] == "success"
    assert len(reads) == 2
    db = Database(str(db_path))
    assert db.conn.execute(
        "SELECT COUNT(*) FROM cwl_roster_snapshots WHERE period='2026-10'"
    ).fetchone()[0] == 2
    preserved = db.conn.execute(
        """SELECT locked_at, roster_snapshot_id FROM cwl_assembly_cache
           WHERE period='2026-10' AND clan_tag='#AAA'"""
    ).fetchone()
    assert preserved["locked_at"] == first_locked_at
    assert preserved["roster_snapshot_id"] == first_snapshot_id
    db.close()

    fail_b["value"] = True
    second = _run_cwl_assembly(now=datetime(2026, 10, 2, 10, 5, tzinfo=TZ))
    assert second["status"] == "failed"
    assert len(reads) == 2
    db = Database(str(db_path))
    after = db.conn.execute(
        "SELECT data_json, error FROM cwl_assembly_cache WHERE period='2026-10' AND clan_tag='#BBB'"
    ).fetchone()
    assert json.loads(after["data_json"]) == before
    assert after["error"] == "temporary"
    db.close()

    cutoff = _run_cwl_assembly(now=datetime(2026, 10, 3, 16, 0, tzinfo=TZ))
    assert cutoff["status"] == "skipped"
    db = Database(str(db_path))
    row = db.conn.execute(
        "SELECT status, locked_at FROM cwl_assembly_cache WHERE period='2026-10' AND clan_tag='#BBB'"
    ).fetchone()
    assert row["status"] == "cutoff"
    assert row["locked_at"]
    db.close()


def test_assembly_scheduler_does_not_start_before_business_window(tmp_path, monkeypatch):
    db_path = tmp_path / "league.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    result = _run_cwl_assembly(now=datetime(2026, 10, 1, 13, 59, tzinfo=TZ))
    assert result == {"status": "skipped", "reason": "2026-10 集结检查将在 1 日 14:00 开始"}
