import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import modules.coc_sync.service as service_module
from modules.coc_sync.cwl_live import normalize_cwl_group, normalize_cwl_war
from scripts.scheduler import _cwl_live_teams_for_period, _cwl_war_refresh_due, _run_cwl_live
from shared.db.connection import Database
from tests.coc_sync.cwl_live_fixtures import league_group, league_war_one, team


def _seed_team(db):
    item = team()
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category,
            member_count, league_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item["period"], item["team_index"], item["team_alias"], item["team_name"],
            item["clan_tag"], item["category"], item["member_count"], item["league_level"],
        ),
    )
    db.conn.commit()


def test_cwl_live_targets_include_confirmed_alliance_teams_and_deduplicate_legacy(db):
    db.conn.execute(
        """INSERT INTO alliance_plans
           (plan_code, display_name, max_clans, sync_tier, entitlements_json,
            status, created_at, updated_at)
           VALUES ('paid', '付费', 10, 'high', '{}', 'active', 'now', 'now')"""
    )
    alliance_id = db.conn.execute(
        """INSERT INTO alliances
           (alliance_key, name, status, plan_code, created_at, updated_at)
           VALUES ('a', 'A', 'active', 'paid', 'now', 'now')"""
    ).lastrowid
    season_id = db.conn.execute(
        """INSERT INTO alliance_cwl_seasons
           (alliance_id, period, status, created_at, updated_at)
           VALUES (?, '2026-09', 'active', 'now', 'now')""",
        (alliance_id,),
    ).lastrowid
    db.conn.executemany(
        """INSERT INTO alliance_cwl_teams
           (season_id, team_index, clan_tag, clan_name_snapshot, team_alias,
            category, sort_order, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'combat', ?, 'manual', 'now', 'now')""",
        [
            (season_id, 0, '#ABC', '共享队', '共享队', 0),
            (season_id, 1, '#NEW', '新增队', '新增队', 1),
        ],
    )
    db.conn.execute(
        """INSERT INTO league_teams
           (period, team_index, team_alias, team_name, clan_tag, category, member_count)
           VALUES ('2026-09', 0, '旧队', '旧队', '#ABC', 'combat', 15)"""
    )
    db.conn.commit()

    teams = _cwl_live_teams_for_period(db, '2026-09')

    assert {item['clan_tag'] for item in teams} == {'#ABC', '#NEW'}
    assert next(item for item in teams if item['clan_tag'] == '#ABC')['team_name'] == '旧队'
    assert next(item for item in teams if item['clan_tag'] == '#NEW')['team_name'] == '新增队'


def test_cwl_live_scheduler_writes_group_and_war_cache_incrementally(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cwl-live.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    db = Database(db_path)
    db.init_schema()
    _seed_team(db)
    db.close()

    calls = {"group": 0, "war": 0}
    state = {"fail_group": False}

    class FakeService:
        def fetch_cwl_group(self, selected_team):
            calls["group"] += 1
            if state["fail_group"]:
                raise RuntimeError("模拟联赛组失败")
            raw_group = league_group()
            raw_group["season"] = "2026-09-01"
            return normalize_cwl_group(
                raw_group, selected_team, "2026-09-03T00:00:00+00:00"
            )

        def fetch_cwl_war(self, war_tag):
            calls["war"] += 1
            return normalize_cwl_war(
                league_war_one(state="warEnded"), war_tag, "2026-09-03T00:00:00+00:00"
            )

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    now = datetime(2026, 9, 3, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    result = _run_cwl_live(now=now)
    assert result["status"] == "success"
    assert calls == {"group": 1, "war": 2}

    db = Database(db_path)
    groups = db.conn.execute("SELECT * FROM cwl_live_group_cache").fetchall()
    wars = db.conn.execute("SELECT * FROM cwl_live_war_cache ORDER BY war_tag").fetchall()
    assert len(groups) == 1
    assert json.loads(groups[0]["data_json"])["season"] == "2026-09"
    assert [(row["war_tag"], row["state"]) for row in wars] == [
        ("#W1", "warEnded"), ("#W2", "warEnded")
    ]
    db.close()

    second = _run_cwl_live(now=now)
    assert second["status"] == "success"
    assert calls == {"group": 1, "war": 2}

    state["fail_group"] = True
    failed_refresh = _run_cwl_live(now=now + timedelta(minutes=31))
    assert failed_refresh["status"] == "success"
    db = Database(db_path)
    cached = db.conn.execute("SELECT data_json, error FROM cwl_live_group_cache").fetchone()
    assert json.loads(cached["data_json"])["season"] == "2026-09"
    assert cached["error"] == "模拟联赛组失败"
    db.close()


def test_cwl_live_scheduler_skips_outside_month_window(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "cwl-live.sqlite3"))
    now = datetime(2026, 9, 13, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _run_cwl_live(now=now) == {
        "status": "skipped",
        "reason": "2026-09 已过联赛实时窗口（今天13号）",
    }


def test_cwl_live_scheduler_labels_not_in_war_as_waiting(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cwl-waiting.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    db = Database(db_path)
    db.init_schema()
    _seed_team(db)
    db.close()

    class FakeService:
        def fetch_cwl_group(self, selected_team):
            return normalize_cwl_group(
                {"state": "notInWar"},
                selected_team,
                "2026-09-01T00:00:00+00:00",
            )

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    result = _run_cwl_live(
        force=True,
        now=datetime(2026, 9, 1, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result == {
        "status": "success",
        "reason": "2026-09 队伍 1（更新 0、等待 1），战争更新 0、跳过 0，完整分组 0、投影 0 行",
    }
    db = Database(db_path)
    row = db.conn.execute(
        "SELECT status, error FROM cwl_live_group_cache WHERE period='2026-09'"
    ).fetchone()
    assert dict(row) == {"status": "waiting", "error": "等待联赛开启"}
    db.close()


def test_cwl_live_refreshes_next_round_when_previous_round_ends(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cwl-round-transition.sqlite3")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    db = Database(db_path)
    db.init_schema()
    _seed_team(db)
    db.close()

    calls = {"#W1": 0, "#W2": 0}
    state = {
        "previous_ended": False,
        "synced_at": "2026-09-03T04:00:00+00:00",
    }

    class FakeService:
        def fetch_cwl_group(self, selected_team):
            raw_group = league_group()
            raw_group["season"] = "2026-09-01"
            return normalize_cwl_group(raw_group, selected_team, state["synced_at"])

        def fetch_cwl_war(self, war_tag):
            calls[war_tag] += 1
            if war_tag == "#W1":
                war_state = "warEnded" if state["previous_ended"] else "inWar"
            else:
                war_state = "inWar" if state["previous_ended"] else "preparation"
            return normalize_cwl_war(
                league_war_one(state=war_state), war_tag, state["synced_at"]
            )

    monkeypatch.setattr(service_module, "CocSyncService", FakeService)
    now = datetime(2026, 9, 3, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    _run_cwl_live(now=now)
    assert calls == {"#W1": 1, "#W2": 1}

    state["synced_at"] = "2026-09-03T04:03:00+00:00"
    _run_cwl_live(now=now + timedelta(minutes=3))
    assert calls == {"#W1": 2, "#W2": 1}

    state["previous_ended"] = True
    state["synced_at"] = "2026-09-03T04:06:00+00:00"
    _run_cwl_live(now=now + timedelta(minutes=6))
    assert calls == {"#W1": 3, "#W2": 2}

    db = Database(db_path)
    states = dict(db.conn.execute(
        "SELECT war_tag, state FROM cwl_live_war_cache ORDER BY war_tag"
    ).fetchall())
    assert states == {"#W1": "warEnded", "#W2": "inWar"}
    db.close()


def test_first_cwl_preparation_only_accelerates_near_start():
    now = datetime(2026, 9, 1, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    cache = {
        "state": "preparation",
        "attempted_at": (now - timedelta(minutes=3)).isoformat(),
        "data_json": json.dumps({"start_time": "20260901T130000.000Z"}),
    }
    assert not _cwl_war_refresh_due(
        cache,
        round_number=1,
        previous_war_tags=(),
        cached_by_war_tag={"#W1": cache},
        now=now,
    )

    cache["data_json"] = json.dumps({"start_time": "20260901T043000.000Z"})
    assert _cwl_war_refresh_due(
        cache,
        round_number=1,
        previous_war_tags=(),
        cached_by_war_tag={"#W1": cache},
        now=now,
    )


def test_later_cwl_preparation_handles_round_transition_only_once():
    now = datetime(2026, 9, 4, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    previous = {
        "state": "warEnded",
        "updated_at": (now - timedelta(minutes=1)).isoformat(),
    }
    preparing = {
        "state": "preparation",
        "attempted_at": (now - timedelta(minutes=10)).isoformat(),
        "updated_at": (now - timedelta(minutes=10)).isoformat(),
        "data_json": "{}",
    }
    caches = {"#W1": previous, "#W2": preparing}
    assert _cwl_war_refresh_due(
        preparing,
        round_number=2,
        previous_war_tags=("#W1",),
        cached_by_war_tag=caches,
        now=now,
    )

    preparing["updated_at"] = now.isoformat()
    assert not _cwl_war_refresh_due(
        preparing,
        round_number=2,
        previous_war_tags=("#W1",),
        cached_by_war_tag=caches,
        now=now,
    )
