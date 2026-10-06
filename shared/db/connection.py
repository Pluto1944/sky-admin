"""SQLite 连接管理 + 建表 + 幂等迁移。

设计要点：
- 整个进程共享**同一个** sqlite3 连接（内存库必须单连接才能共享数据；文件库
  单连接也简化了事务与外键行为）。各业务模块的 Repository 都持有这个连接，
  因此外键约束可以在关联数据表之间保持一致。
- 建表脚本集中在此，业务模块不各自建表，避免 schema 分散。

db_path 传 ":memory:" 用于测试。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# accounts 建表模板（{table} 便于重建迁移时先建新表再改名）。
# 瘦身后只保留"账号级事实"：COC 权威组 + player_name/status/history_score。
# 按月维度的 account_type/camp_order/match_value/join_combat 全部下沉到 registrations；
# last_reg_period 改由 registrations 实时派生，不再落列。
_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    player_tag         TEXT PRIMARY KEY,   -- COC 真实 Tag（走 A 后名实相符）
    -- COC 权威组（由 coc_sync 更新）
    account_name       TEXT,               -- 游戏昵称（COC 为主）
    exp_level          INTEGER,            -- 等级
    trophies           INTEGER,            -- 奖杯
    league_name        TEXT,               -- 联赛段位
    town_hall_level    INTEGER,            -- 大本营等级
    clan_tag           TEXT,               -- 当前所在部落（多部落汇总区分来源）
    clan_role          TEXT,               -- 部落职位
    coc_raw            TEXT,               -- COC 原始成员数据全量快照(JSON)，扩展字段零改表
    last_synced_at     TEXT,               -- 最近一次 COC 同步时间
    season_attack_wins INTEGER,            -- 当前赛季主世界进攻胜场（玩家详情）
    last_activity_at   TEXT,               -- 最近检测到公开数据有效变化时间
    last_activity_reason TEXT,              -- 有效变化原因 JSON 数组
    activity_observed_since TEXT,           -- 开始观察公开数据变化的时间
    membership_status  TEXT DEFAULT 'member', -- 联盟部落身份：member=在联盟部落 / left=已退部
    -- 账号级事实（非 COC，但描述账号本身；按月维度已下沉子表）
    player_name        TEXT,               -- 归属人（主号）
    status             TEXT,               -- 报名维度状态 active/missed/...
    history_score      REAL DEFAULT 0,     -- 历史分（战绩组）
    updated_at         TEXT
);
"""

# registrations 表（B 方案：报名事实的自包含源，不依赖 accounts）。
# - 自持 account_name（报名昵称，报名事实主标识）与 player_name（主号归属），
#   展示/派生不再依赖 accounts join。
# - player_tag 降为"命中真实账号时缓存的关联"：可空、无 FK；命中不了就留空。
# - 唯一键为 (account_name, period)：过渡期靠昵称去重，且 player_tag 多为 NULL 不能做唯一键。
# - 去掉 FOREIGN KEY(player_tag) REFERENCES accounts：解除"报名必须先在主表建行"的硬约束。
# {table} 便于重建迁移时先建新表再改名。
_REGISTRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name      TEXT NOT NULL,           -- 报名昵称：报名事实主标识（报名表必有）
    player_name       TEXT,                    -- 主号归属（报名表自持，不再从 accounts join）
    period            TEXT NOT NULL,
    match_value       REAL,
    join_combat       INTEGER,
    willing_to_manage INTEGER,                 -- 是否愿意做联赛管理员（报名表字段）
    account_type      TEXT,                    -- 本月账号分类 combat / normal
    league_type       TEXT,                    -- 编排产物
    rank_order        INTEGER,                 -- 编排产物
    player_tag        TEXT,                    -- 可空：命中的真实账号 tag，作关联缓存（无 FK）
    team_info         TEXT,                    -- 分配到哪个队伍（如"0 泰坦二 苍穹·天空之城 #2QQ"），NULL=未分配
    UNIQUE(account_name, period)
);
"""

_LEAGUE_TEAMS_DDL = """
CREATE TABLE IF NOT EXISTS league_teams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,
    team_index      INTEGER NOT NULL,
    team_alias      TEXT NOT NULL,
    team_name       TEXT,
    clan_tag        TEXT,
    category        TEXT NOT NULL,
    member_count    INTEGER NOT NULL,
    leader          TEXT,
    league_level    TEXT,
    reserved_slots  INTEGER DEFAULT 0,
    UNIQUE(period, team_index)
);
"""

_LEAGUE_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS league_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,
    team_index      INTEGER NOT NULL,
    team_alias      TEXT NOT NULL,
    team_name       TEXT,
    clan_tag        TEXT,
    category        TEXT NOT NULL,
    player_tag      TEXT NOT NULL,
    account_name    TEXT,
    total_stars     INTEGER,
    attacks         INTEGER,
    appearances     INTEGER,
    missed_attacks  INTEGER,
    offense_1stars  INTEGER,
    offense_3stars  INTEGER DEFAULT 0,
    defense_3stars  INTEGER DEFAULT 0,
    defense_total   INTEGER DEFAULT 0,
    fetched_at      TEXT,
    raw_metrics     TEXT,
    UNIQUE(period, team_index, player_tag),
    FOREIGN KEY(player_tag) REFERENCES accounts(player_tag)
);
"""

_WECHAT_USERS_DDL = """
CREATE TABLE IF NOT EXISTS wechat_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    openid        TEXT NOT NULL UNIQUE,
    nickname      TEXT,
    avatar_url    TEXT,
    role          TEXT DEFAULT 'member',
    account_name  TEXT,
    player_tag    TEXT,
    created_at    TEXT,
    updated_at    TEXT
);
"""

_FARM_STATS_DDL = """
CREATE TABLE IF NOT EXISTS farm_stats (
    clan_tag     TEXT PRIMARY KEY,
    clan_name    TEXT,
    category     TEXT DEFAULT 'farm',
    member_count INTEGER DEFAULT 0,
    stats_json   TEXT NOT NULL,
    updated_at   TEXT
);
"""

_FARM_FILL_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS farm_fill_accounts (
    account_number           TEXT PRIMARY KEY,
    player_tag               TEXT NOT NULL,
    account_name_snapshot    TEXT,
    town_hall_level_snapshot INTEGER,
    source_clan_text         TEXT,
    source_clan_tag          TEXT,
    source_checked_text      TEXT,
    status                   TEXT NOT NULL DEFAULT 'active',
    source_doc_id            TEXT NOT NULL,
    source_sheet_id          TEXT NOT NULL,
    source_sheet_title       TEXT,
    imported_at              TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    note                     TEXT
);

CREATE INDEX IF NOT EXISTS idx_farm_fill_accounts_player_tag
ON farm_fill_accounts(player_tag);
"""

_CURRENT_WAR_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS current_war_cache (
    clan_tag     TEXT PRIMARY KEY,
    clan_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    data_json    TEXT NOT NULL,
    error        TEXT,
    updated_at   TEXT NOT NULL,
    attempted_at TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    war_key TEXT,
    expected_end_at TEXT,
    payload_version INTEGER NOT NULL DEFAULT 1,
    payload_hash TEXT,
    last_success_at TEXT,
    history_sealed_at TEXT
);
"""

_WAR_HISTORY_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS war_history_cache (
    clan_tag               TEXT NOT NULL,
    war_key                TEXT NOT NULL,
    clan_name              TEXT NOT NULL,
    category               TEXT NOT NULL,
    opponent_tag           TEXT,
    opponent_name          TEXT,
    status                 TEXT NOT NULL,
    result                 TEXT,
    preparation_start_time TEXT,
    start_time             TEXT,
    end_time               TEXT,
    source                 TEXT NOT NULL DEFAULT 'official_currentwar',
    finalized_at           TEXT,
    payload_version        INTEGER NOT NULL DEFAULT 1,
    payload_hash           TEXT,
    data_json              TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    PRIMARY KEY(clan_tag, war_key)
);

CREATE INDEX IF NOT EXISTS idx_war_history_clan_end
ON war_history_cache(clan_tag, end_time DESC);
"""

_MEMBER_WAR_FACTS_DDL = """
CREATE TABLE IF NOT EXISTS member_war_facts (
    clan_tag         TEXT NOT NULL,
    war_key          TEXT NOT NULL,
    player_tag       TEXT NOT NULL,
    end_time         TEXT NOT NULL,
    status           TEXT NOT NULL,
    category         TEXT,
    available_attacks INTEGER NOT NULL DEFAULT 0,
    actual_attacks   INTEGER NOT NULL DEFAULT 0,
    observed_attacks INTEGER NOT NULL DEFAULT 0,
    three_stars      INTEGER NOT NULL DEFAULT 0,
    town_hall_level_at_war INTEGER,
    map_position INTEGER,
    offense_observed_attacks INTEGER NOT NULL DEFAULT 0,
    offense_effective_attacks INTEGER NOT NULL DEFAULT 0,
    offense_effective_3stars INTEGER NOT NULL DEFAULT 0,
    defense_observed_attacks INTEGER NOT NULL DEFAULT 0,
    defense_effective_attacks INTEGER NOT NULL DEFAULT 0,
    defense_effective_3stars INTEGER NOT NULL DEFAULT 0,
    metric_version INTEGER NOT NULL DEFAULT 1,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY(clan_tag, war_key, player_tag)
);

CREATE INDEX IF NOT EXISTS idx_member_war_facts_player_end
ON member_war_facts(player_tag, end_time DESC);

CREATE INDEX IF NOT EXISTS idx_member_war_facts_clan_end
ON member_war_facts(clan_tag, end_time DESC);
"""

_CAPITAL_RAID_MEMBER_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS capital_raid_member_results (
    clan_tag                 TEXT NOT NULL,
    start_time               TEXT NOT NULL,
    end_time                 TEXT,
    player_tag               TEXT NOT NULL,
    player_name              TEXT,
    attack_limit             INTEGER NOT NULL DEFAULT 0,
    bonus_attack_limit       INTEGER NOT NULL DEFAULT 0,
    attacks                  INTEGER NOT NULL DEFAULT 0,
    capital_resources_looted INTEGER NOT NULL DEFAULT 0,
    fetched_at               TEXT NOT NULL,
    PRIMARY KEY(clan_tag, start_time, player_tag)
);

CREATE INDEX IF NOT EXISTS idx_capital_member_start
ON capital_raid_member_results(player_tag, start_time DESC);
"""

_CAPITAL_RAID_STATUS_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS capital_raid_status_cache (
    clan_tag       TEXT PRIMARY KEY,
    clan_name      TEXT NOT NULL,
    status         TEXT NOT NULL,
    raid_state     TEXT,
    weekend_start  TEXT NOT NULL,
    weekend_end    TEXT NOT NULL,
    error          TEXT,
    updated_at     TEXT,
    attempted_at   TEXT NOT NULL,
    failure_count  INTEGER NOT NULL DEFAULT 0
);
"""

_CLAN_GAMES_MEMBER_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS clan_games_member_snapshots (
    period           TEXT NOT NULL,
    player_tag       TEXT NOT NULL,
    player_name      TEXT,
    clan_tag         TEXT,
    cumulative_value INTEGER NOT NULL DEFAULT 0,
    points           INTEGER,
    complete         INTEGER NOT NULL DEFAULT 0,
    fetched_at       TEXT NOT NULL,
    PRIMARY KEY(period, player_tag)
);

CREATE INDEX IF NOT EXISTS idx_clan_games_member_period
ON clan_games_member_snapshots(player_tag, period DESC);
"""

_CLAN_PROFILE_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS clan_profile_cache (
    clan_tag     TEXT PRIMARY KEY,
    clan_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    data_json    TEXT,
    error        TEXT,
    updated_at   TEXT,
    attempted_at TEXT NOT NULL
);
"""

_CWL_LIVE_GROUP_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS cwl_live_group_cache (
    period        TEXT NOT NULL,
    clan_tag      TEXT NOT NULL,
    team_index    INTEGER NOT NULL,
    team_alias    TEXT NOT NULL,
    team_name     TEXT,
    category      TEXT NOT NULL,
    league_level  TEXT,
    season        TEXT,
    state         TEXT,
    status        TEXT NOT NULL,
    data_json     TEXT,
    error         TEXT,
    updated_at    TEXT,
    attempted_at  TEXT NOT NULL,
    raw_status    TEXT NOT NULL DEFAULT 'collecting',
    raw_complete_at TEXT,
    source        TEXT,
    payload_version INTEGER NOT NULL DEFAULT 1,
    payload_hash  TEXT,
    PRIMARY KEY(period, clan_tag)
);
"""

_CWL_LIVE_WAR_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS cwl_live_war_cache (
    war_tag       TEXT PRIMARY KEY,
    season        TEXT,
    state         TEXT NOT NULL,
    status        TEXT NOT NULL,
    data_json     TEXT,
    error         TEXT,
    updated_at    TEXT,
    attempted_at  TEXT NOT NULL,
    source        TEXT,
    finalized_at  TEXT,
    payload_version INTEGER NOT NULL DEFAULT 1,
    payload_hash  TEXT
);
"""

_CWL_ROSTER_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS cwl_roster_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    period       TEXT NOT NULL,
    revision     INTEGER NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 1,
    source_sheet TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    data_json    TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE(period, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cwl_roster_active_period
ON cwl_roster_snapshots(period) WHERE is_active = 1;
"""

_CWL_ASSEMBLY_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS cwl_assembly_cache (
    period             TEXT NOT NULL,
    clan_tag           TEXT NOT NULL,
    roster_snapshot_id INTEGER NOT NULL,
    team_index          INTEGER NOT NULL,
    team_alias          TEXT NOT NULL,
    team_name           TEXT,
    category            TEXT NOT NULL,
    status              TEXT NOT NULL,
    data_json           TEXT,
    error               TEXT,
    updated_at          TEXT,
    attempted_at        TEXT NOT NULL,
    locked_at           TEXT,
    PRIMARY KEY(period, clan_tag),
    FOREIGN KEY(roster_snapshot_id) REFERENCES cwl_roster_snapshots(id)
);
"""

# sync_jobs 表：周期调度器（scripts/scheduler.py）的任务状态。
# last_status 取值：success / failed / skipped / running / never
_SYNC_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS sync_jobs (
    job_id        TEXT PRIMARY KEY,
    job_name      TEXT,
    interval_min  INTEGER DEFAULT 1440,
    enabled       INTEGER DEFAULT 1,
    last_run_at   TEXT,
    next_run_at   TEXT,
    last_status   TEXT,
    last_error    TEXT,
    last_duration REAL,
    run_count     INTEGER DEFAULT 0,
    fail_count    INTEGER DEFAULT 0,
    extra         TEXT
);
"""

# 常驻组件运行身份。与 sync_jobs 的业务任务状态分离，避免混淆进程版本和任务结果。
_SERVICE_RUNTIME_DDL = """
CREATE TABLE IF NOT EXISTS service_runtime (
    component      TEXT PRIMARY KEY,
    release_version TEXT NOT NULL,
    git_commit     TEXT NOT NULL,
    git_describe   TEXT NOT NULL,
    tracked_dirty  INTEGER NOT NULL DEFAULT 0,
    started_at     TEXT NOT NULL,
    heartbeat_at   TEXT NOT NULL
);
"""

_CHILDREN_DDL = (
    _REGISTRATIONS_DDL.format(table="registrations")
    + _LEAGUE_TEAMS_DDL
    + _LEAGUE_RESULTS_DDL
    + _WECHAT_USERS_DDL
    + _FARM_STATS_DDL
    + _FARM_FILL_ACCOUNTS_DDL
    + _CURRENT_WAR_CACHE_DDL
    + _WAR_HISTORY_CACHE_DDL
    + _MEMBER_WAR_FACTS_DDL
    + _CAPITAL_RAID_MEMBER_RESULTS_DDL
    + _CAPITAL_RAID_STATUS_CACHE_DDL
    + _CLAN_GAMES_MEMBER_SNAPSHOTS_DDL
    + _CLAN_PROFILE_CACHE_DDL
    + _CWL_LIVE_GROUP_CACHE_DDL
    + _CWL_LIVE_WAR_CACHE_DDL
    + _CWL_ROSTER_SNAPSHOTS_DDL
    + _CWL_ASSEMBLY_CACHE_DDL
    + _SYNC_JOBS_DDL
    + _SERVICE_RUNTIME_DDL
)

_SCHEMA = _ACCOUNTS_DDL.format(table="accounts") + _CHILDREN_DDL

# accounts 瘦身后的完整列清单（重建迁移按此拷贝存量数据；子表下沉/派生列不在其中）
_ACCOUNTS_COLS = (
    "player_tag", "account_name", "exp_level", "trophies", "league_name",
    "town_hall_level", "clan_tag", "clan_role", "coc_raw", "last_synced_at",
    "season_attack_wins", "last_activity_at", "last_activity_reason",
    "activity_observed_since",
    "membership_status", "player_name", "status",
    "history_score", "updated_at",
)

# accounts 上已废弃的旧列（新库不再有；旧库检测到即触发重建物理删除）
_OBSOLETE_ACCOUNT_COLS = (
    "account_type", "camp_order", "latest_match_value", "join_combat",
    "last_reg_period", "is_provisional",
)


class Database:
    """持有单一 SQLite 连接，负责建表与迁移。"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        if db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """幂等迁移：把旧库 schema 拉齐到瘦身后的目标结构。

        1) registrations 若还是"依赖 accounts"的旧形态（缺 account_name 列），重建为
           B 方案的自包含表：自持 account_name/player_name、去 FK、唯一键改
           (account_name, period)；account_name 由旧 player_tag（过渡期=昵称）回填，
           player_name 从 accounts 按旧 player_tag join 回填；
        2) 把旧 accounts 上的 account_type 回填到该账号的报名行；
        3) accounts 若仍含已废弃列，重建表物理删除（SQLite 老版本无 DROP COLUMN，
           且用户要求彻底删净，故走"建新表→拷数据→改名"）。
        新库由 _SCHEMA 直接建全，本方法对其为无害的空操作。
        """
        # 先提交，确保 PRAGMA 在事务外生效
        self.conn.commit()
        self.conn.execute("PRAGMA legacy_alter_table = ON")
        self.conn.execute("PRAGMA foreign_keys = OFF")

        reg_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(registrations)")}

        # registrations 解绑 accounts（B 方案）：旧表无 account_name 列即视为旧形态，先重建
        if "account_name" not in reg_cols:
            self._rebuild_registrations()
            reg_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(registrations)")}

        # account_type 下沉列补齐
        if "account_type" not in reg_cols:
            self.conn.execute("ALTER TABLE registrations ADD COLUMN account_type TEXT")

        # 队伍分配列
        if "team_info" not in reg_cols:
            self.conn.execute("ALTER TABLE registrations ADD COLUMN team_info TEXT")

        # 管理意愿列（报名表"是否愿意做联赛管理员"）
        if "willing_to_manage" not in reg_cols:
            self.conn.execute("ALTER TABLE registrations ADD COLUMN willing_to_manage INTEGER")

        acc_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(accounts)")}
        # 回填下沉列：仅当报名行 account_type 为空时，取该账号旧 accounts 上的值补入
        # （camp_order 语义已废弃为上月排名，不再从旧 accounts 回填）
        if "account_type" in acc_cols:
            self.conn.execute(
                "UPDATE registrations SET account_type = COALESCE("
                "account_type, (SELECT a.account_type FROM accounts a "
                "WHERE a.player_tag = registrations.player_tag))"
            )

        if any(c in acc_cols for c in _OBSOLETE_ACCOUNT_COLS):
            self._rebuild_accounts(acc_cols)
            acc_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(accounts)")}

        for column, column_type in (
            ("season_attack_wins", "INTEGER"),
            ("last_activity_at", "TEXT"),
            ("last_activity_reason", "TEXT"),
            ("activity_observed_since", "TEXT"),
        ):
            if column not in acc_cols:
                self.conn.execute(f"ALTER TABLE accounts ADD COLUMN {column} {column_type}")

        # league_results 新增列迁移（league-stats 功能）
        lr_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(league_results)")}
        if "offense_3stars" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN offense_3stars INTEGER DEFAULT 0")
        if "defense_3stars" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN defense_3stars INTEGER DEFAULT 0")
        if "defense_total" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN defense_total INTEGER DEFAULT 0")
        if "fetched_at" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN fetched_at TEXT")
        if "appearances" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN appearances INTEGER")
        if "missed_attacks" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN missed_attacks INTEGER")
        if "offense_1stars" not in lr_cols:
            self.conn.execute("ALTER TABLE league_results ADD COLUMN offense_1stars INTEGER")

        # farm_stats 表迁移（互刷部落缓存）
        fs_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(farm_stats)")}
        if not fs_cols:
            self.conn.execute(_FARM_STATS_DDL)

        # 互刷填坑号长期身份表；无 accounts 外键，允许尚未进入联盟的已登记账号。
        fill_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(farm_fill_accounts)")
        }
        if not fill_cols:
            self.conn.executescript(_FARM_FILL_ACCOUNTS_DDL)

        # current_war_cache 表迁移（全部自有部落当前战争缓存）
        cw_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(current_war_cache)")}
        if not cw_cols:
            self.conn.execute(_CURRENT_WAR_CACHE_DDL)
        else:
            if "attempted_at" not in cw_cols:
                self.conn.execute("ALTER TABLE current_war_cache ADD COLUMN attempted_at TEXT")
            if "failure_count" not in cw_cols:
                self.conn.execute(
                    "ALTER TABLE current_war_cache ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0"
                )
            for column, definition in (
                ("war_key", "TEXT"),
                ("expected_end_at", "TEXT"),
                ("payload_version", "INTEGER NOT NULL DEFAULT 1"),
                ("payload_hash", "TEXT"),
                ("last_success_at", "TEXT"),
                ("history_sealed_at", "TEXT"),
            ):
                if column not in cw_cols:
                    self.conn.execute(f"ALTER TABLE current_war_cache ADD COLUMN {column} {definition}")

        # 普通部落战逐场历史归档（每个部落保留最近 45 场已结束战争）
        wh_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(war_history_cache)")}
        if not wh_cols:
            self.conn.executescript(_WAR_HISTORY_CACHE_DDL)
        else:
            for column, definition in (
                ("source", "TEXT NOT NULL DEFAULT 'official_currentwar'"),
                ("finalized_at", "TEXT"),
                ("payload_version", "INTEGER NOT NULL DEFAULT 1"),
                ("payload_hash", "TEXT"),
            ):
                if column not in wh_cols:
                    self.conn.execute(f"ALTER TABLE war_history_cache ADD COLUMN {column} {definition}")

        fact_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(member_war_facts)")}
        if not fact_cols:
            self.conn.executescript(_MEMBER_WAR_FACTS_DDL)
        else:
            for column, definition in (
                ("town_hall_level_at_war", "INTEGER"),
                ("map_position", "INTEGER"),
                ("offense_observed_attacks", "INTEGER NOT NULL DEFAULT 0"),
                ("offense_effective_attacks", "INTEGER NOT NULL DEFAULT 0"),
                ("offense_effective_3stars", "INTEGER NOT NULL DEFAULT 0"),
                ("defense_observed_attacks", "INTEGER NOT NULL DEFAULT 0"),
                ("defense_effective_attacks", "INTEGER NOT NULL DEFAULT 0"),
                ("defense_effective_3stars", "INTEGER NOT NULL DEFAULT 0"),
                ("metric_version", "INTEGER NOT NULL DEFAULT 1"),
            ):
                if column not in fact_cols:
                    self.conn.execute(f"ALTER TABLE member_war_facts ADD COLUMN {column} {definition}")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_member_war_facts_clan_end "
                "ON member_war_facts(clan_tag, end_time DESC)"
            )
        if not {row[1] for row in self.conn.execute("PRAGMA table_info(capital_raid_member_results)")}:
            self.conn.executescript(_CAPITAL_RAID_MEMBER_RESULTS_DDL)
        if not {row[1] for row in self.conn.execute("PRAGMA table_info(capital_raid_status_cache)")}:
            self.conn.execute(_CAPITAL_RAID_STATUS_CACHE_DDL)
        if not {row[1] for row in self.conn.execute("PRAGMA table_info(clan_games_member_snapshots)")}:
            self.conn.executescript(_CLAN_GAMES_MEMBER_SNAPSHOTS_DDL)

        # clan_profile_cache 表迁移（自有部落官方资料缓存）
        cp_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(clan_profile_cache)")}
        if not cp_cols:
            self.conn.execute(_CLAN_PROFILE_CACHE_DDL)

        # CWL 实时联赛组与逐场战争缓存
        cwl_group_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(cwl_live_group_cache)")
        }
        if not cwl_group_cols:
            self.conn.execute(_CWL_LIVE_GROUP_CACHE_DDL)
        else:
            for column, definition in (
                ("attempted_at", "TEXT"),
                ("raw_status", "TEXT NOT NULL DEFAULT 'collecting'"),
                ("raw_complete_at", "TEXT"),
                ("source", "TEXT"),
                ("payload_version", "INTEGER NOT NULL DEFAULT 1"),
                ("payload_hash", "TEXT"),
            ):
                if column not in cwl_group_cols:
                    self.conn.execute(f"ALTER TABLE cwl_live_group_cache ADD COLUMN {column} {definition}")
        cwl_war_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(cwl_live_war_cache)")
        }
        if not cwl_war_cols:
            self.conn.execute(_CWL_LIVE_WAR_CACHE_DDL)
        else:
            for column, definition in (
                ("attempted_at", "TEXT"),
                ("source", "TEXT"),
                ("finalized_at", "TEXT"),
                ("payload_version", "INTEGER NOT NULL DEFAULT 1"),
                ("payload_hash", "TEXT"),
            ):
                if column not in cwl_war_cols:
                    self.conn.execute(f"ALTER TABLE cwl_live_war_cache ADD COLUMN {column} {definition}")

        # CWL 正式名单快照与集结检查缓存
        roster_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(cwl_roster_snapshots)")
        }
        if not roster_cols:
            self.conn.executescript(_CWL_ROSTER_SNAPSHOTS_DDL)
        assembly_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(cwl_assembly_cache)")
        }
        if not assembly_cols:
            self.conn.execute(_CWL_ASSEMBLY_CACHE_DDL)

        # sync_jobs 表迁移（周期调度器状态）
        sj_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(sync_jobs)")}
        if not sj_cols:
            self.conn.execute(_SYNC_JOBS_DDL)

        runtime_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(service_runtime)")
        }
        if not runtime_cols:
            self.conn.execute(_SERVICE_RUNTIME_DDL)

        # 普通战旧聚合任务已随旧表物理退役；清理历史运行状态，避免 --list
        # 显示一个不再存在且无法调度的任务。
        self.conn.execute("DELETE FROM sync_jobs WHERE job_id = 'war_results'")

        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA legacy_alter_table = OFF")

    def _rebuild_accounts(self, existing_cols: set[str]) -> None:
        """建新表→拷存量→改名，物理删除 accounts 上的已废弃列。

        须在 foreign_keys=OFF 且 legacy_alter_table=ON 下调用（子表 FK 按名引用
        accounts，重建期间不改动子表 schema，改名后引用自然复位）。
        """
        keep = [c for c in _ACCOUNTS_COLS]
        select_cols = ", ".join(c if c in existing_cols else "NULL" for c in keep)
        self.conn.execute("DROP TABLE IF EXISTS accounts_new")
        self.conn.execute(_ACCOUNTS_DDL.format(table="accounts_new"))
        self.conn.execute(
            f"INSERT INTO accounts_new ({', '.join(keep)}) "
            f"SELECT {select_cols} FROM accounts"
        )
        self.conn.execute("DROP TABLE accounts")
        self.conn.execute("ALTER TABLE accounts_new RENAME TO accounts")

    def _rebuild_registrations(self) -> None:
        """把旧 registrations（依赖 accounts、唯一键 (player_tag,period)、带 FK）重建为
        B 方案的自包含表（自持 account_name/player_name、去 FK、唯一键 (account_name,period)）。

        须在 foreign_keys=OFF 且 legacy_alter_table=ON 下调用。回填规则：
        - account_name：过渡期旧 player_tag 即昵称，故直接取旧 player_tag；
        - player_name：从 accounts 按旧 player_tag join 取（旧库把归属人存在 accounts）；
        - player_tag：保留旧值作为关联缓存（过渡期=昵称，后续 coc-sync 命中可覆盖）。
        同 (account_name, period) 若冲突（理论上不会，过渡期 1:1）以先到者为准。
        """
        self.conn.execute("DROP TABLE IF EXISTS registrations_new")
        self.conn.execute(_REGISTRATIONS_DDL.format(table="registrations_new"))
        self.conn.execute(
            """
            INSERT OR IGNORE INTO registrations_new
                (id, account_name, player_name, period, match_value, join_combat,
                 willing_to_manage, account_type, league_type, rank_order, player_tag, team_info)
            SELECT r.id,
                   COALESCE(a.account_name, r.player_tag),
                   a.player_name,
                   r.period, r.match_value, r.join_combat,
                   COALESCE(r.willing_to_manage, 0),
                   r.account_type, r.league_type, r.rank_order,
                   r.player_tag,
                   r.team_info
            FROM registrations r
            LEFT JOIN accounts a ON a.player_tag = r.player_tag
            """
        )
        self.conn.execute("DROP TABLE registrations")
        self.conn.execute("ALTER TABLE registrations_new RENAME TO registrations")

    def reset(self) -> None:
        """清空并重建所有业务表（历史数据清零）。"""
        self.conn.execute("PRAGMA foreign_keys = OFF")
        for table in (
            "cwl_assembly_cache", "cwl_roster_snapshots",
            "cwl_live_war_cache", "cwl_live_group_cache", "war_history_cache",
            "member_war_facts",
            "capital_raid_member_results", "capital_raid_status_cache",
            "clan_games_member_snapshots",
            "current_war_cache",
            "farm_fill_accounts",
            "clan_profile_cache",
            "league_results", "league_teams",
            "registrations", "accounts", "sync_jobs", "service_runtime",
        ):
            self.conn.execute(f"DROP TABLE IF EXISTS {table}")
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def close(self) -> None:
        self.conn.close()
