"""SQLite 连接管理 + 建表 + 幂等迁移。

设计要点：
- 整个进程共享**同一个** sqlite3 连接（内存库必须单连接才能共享数据；文件库
  单连接也简化了事务与外键行为）。三个业务模块的 Repository 都持有这个连接，
  因此外键约束在 accounts / registrations / results 之间照常生效。
- 建表脚本集中在此，业务模块不各自建表，避免 schema 分散。
- results 表带 UNIQUE(player_tag, period, league_type)：同月同类型战绩重复导入
  时走 upsert 覆盖而非累积（修复历史隐患 #1）。

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

_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_tag   TEXT NOT NULL,
    period       TEXT NOT NULL,
    league_type  TEXT,
    raw_metrics  TEXT,
    UNIQUE(player_tag, period, league_type),
    FOREIGN KEY(player_tag) REFERENCES accounts(player_tag)
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

_WAR_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS war_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_tag        TEXT NOT NULL,
    player_tag      TEXT NOT NULL,
    account_name    TEXT,
    town_hall_level INTEGER,
    end_time        TEXT NOT NULL,
    total_stars     INTEGER DEFAULT 0,
    attacks         INTEGER DEFAULT 0,
    offense_3stars  INTEGER DEFAULT 0,
    defense_3stars  INTEGER DEFAULT 0,
    defense_total   INTEGER DEFAULT 0,
    fetched_at      TEXT,
    raw_metrics     TEXT,
    UNIQUE(clan_tag, player_tag, end_time),
    FOREIGN KEY(player_tag) REFERENCES accounts(player_tag)
);
"""

_CHILDREN_DDL = (
    _REGISTRATIONS_DDL.format(table="registrations")
    + _RESULTS_DDL
    + _LEAGUE_TEAMS_DDL
    + _LEAGUE_RESULTS_DDL
    + _WECHAT_USERS_DDL
    + _WAR_RESULTS_DDL
)

_SCHEMA = _ACCOUNTS_DDL.format(table="accounts") + _CHILDREN_DDL

# accounts 瘦身后的完整列清单（重建迁移按此拷贝存量数据；子表下沉/派生列不在其中）
_ACCOUNTS_COLS = (
    "player_tag", "account_name", "exp_level", "trophies", "league_name",
    "town_hall_level", "clan_tag", "clan_role", "coc_raw", "last_synced_at",
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

        # war_results 表迁移（部落战战绩功能）
        wr_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(war_results)")}
        if not wr_cols:
            self.conn.execute(_WAR_RESULTS_DDL)

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
        for table in ("war_results", "league_results", "league_teams", "results", "registrations", "accounts"):
            self.conn.execute(f"DROP TABLE IF EXISTS {table}")
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def close(self) -> None:
        self.conn.close()
