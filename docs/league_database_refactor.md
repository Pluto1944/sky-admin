# 联赛数据库重构设计方案（已实施）

> 实施日期：2026-08-01
> 状态：已完成

## 一、背景与问题分析

### 1.1 已解决的痛点

1. **队伍配置历史缺失**：`config.py` 中 `TEAMS` 每月变化，旧配置不持久化。**已解决**：新增 `league_teams` 表按月快照，`TEAMS_LAST` 已删除。
2. **team 概念混淆**：旧 `registrations.team_name` 只存别名。**已解决**：分离 `team_alias`（别名）和 `team_name`（COC 真实名称）。
3. **results 表设计问题**：team 信息藏在 `raw_metrics` JSON 中。**已解决**：新增 `league_results` 表，字段结构化。
4. **信息存储分散**：队伍信息散落各处。**已解决**：统一到 `league_teams` + `league_results`。

### 1.2 设计目标

- 建立独立的联赛记录表，完整记录每月队伍配置和战绩
- 分离 team_alias（别名）和 team_name（COC API 真实名称）
- 以 team_index 作为队伍唯一身份标识
- 支持历史数据回溯
- Excel 展示增加 team_name 列

---

## 二、核心概念定义

| 概念 | 来源 | 唯一性 | 用途 |
|------|------|--------|------|
| **team_index** | `enumerate(teams)` 索引（0-based） | 唯一 | 队伍身份标识、升降级分组 key |
| **team_alias** | config `name` 字段 | 不唯一 | 人类标签，如"大一"、"泰坦二" |
| **team_name** | COC API 真实部落名称 | 唯一 | 展示用途，如"云深不知处" |
| **clan_tag** | config `clan_tag` | 唯一 | COC API 查询标识 |
| **category** | config `category` | — | `combat` / `shell` |

---

## 三、新增数据库表

### 3.1 league_teams（队伍配置快照）

```sql
CREATE TABLE league_teams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,
    team_index      INTEGER NOT NULL,
    team_alias      TEXT NOT NULL,          -- 别名（config name）
    team_name       TEXT,                   -- COC 真实部落名称
    clan_tag        TEXT,
    category        TEXT NOT NULL,
    member_count    INTEGER NOT NULL,
    leader          TEXT,
    league_level    TEXT,
    reserved_slots  INTEGER DEFAULT 0,
    UNIQUE(period, team_index)
);
```

**写入时机**：`arrange()` 开始时幂等写入（`INSERT OR REPLACE`）。
**team_name 来源**：`arrange()` 从 `league_teams` 表读取已有值注入 `teams_cfg.coc_name`，写入时保留已有值不被覆盖。

### 3.2 league_results（联赛战绩）

```sql
CREATE TABLE league_results (
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
    raw_metrics     TEXT,
    UNIQUE(period, team_index, player_tag),
    FOREIGN KEY(player_tag) REFERENCES accounts(player_tag)
);
```

**写入时机**：`fetch_cwl_data.py` 拉取 CWL 数据后写入（同时双写到旧 `results` 表）。
**team 字段冗余**：同一队伍每个玩家存一份，避免 JOIN。

---

## 四、数据流

### 4.1 编排阶段（arrange）

```
config.TEAMS
  → arrange() 从 league_teams 读 team_name 注入 teams_cfg.coc_name
  → _write_league_teams() 幂等写入（保留已有 team_name）
  → team_builder._build_team_result() 透传 coc_name
  → ordered_with_team.team_name = coc_name（COC 真实名称）
  → Excel team_name 列展示
```

### 4.2 战绩拉取（fetch_cwl_data）

```
_load_teams_to_fetch(period)
  → 优先读 league_teams 表 → 回退到 TEAMS 当前配置
  → COC API 拉取 → 写入 league_results + results（双写）
```

### 4.3 上月数据读取（升降级）

```
_load_prev_teams_config(cwl_period) → 读 league_teams（回退 TEAMS）
_load_combat_star_data(cwl_period) → 优先 league_results（回退 results）
_load_prev_combat_from_results(cwl_period) → 优先 league_results（回退 results）
```

---

## 五、cur_team 和 registrations.team_name 格式

| 位置 | 格式 | 示例 |
|------|------|------|
| cur_team（展示） | `"{team_index} {team_alias} {coc_name}"` | `"5 大一 raiders x"` |
| registrations.team_name（回写） | `"{team_index} {team_alias} {coc_name} {clan_tag}"` | `"5 大一 raiders x #CYYL"` |
| Excel team_name 列 | COC 真实名称（空就空） | `"raiders x"` |

---

## 六、Excel 输出变更

`ARRANGEMENT_OUTPUT_HEADERS` 新增 `team_name` 列：
```
rank_order, league_type, cur_team, prev_team, movement,
player_tag, account_name, player_name, team_name, account_type,
prev_rank, trophies, match_value, history_score
```

- **Part1**：`team_name` 从 `coc_team_name_map` 取（COC 真实名称）
- **Part2**：`team_name` 统一取队伍级别的 `coc_name`
- 白名单人员：插入到 Part1 对应队伍开头位置

---

## 七、过渡策略

1. `league_results` 写入时双写到旧 `results` 表
2. `_load_prev_teams_config` 为空时回退 config TEAMS
3. `_load_combat_star_data` / `_load_prev_combat_from_results` 优先新表，回退旧表
4. `TEAMS_LAST` 已删除

---

## 八、迁移步骤（已完成）

1. ✅ DDL 添加 `league_teams` 和 `league_results`
2. ✅ `arrange()` 开始时写入 `league_teams`
3. ✅ `fetch_cwl_data.py` 读写新表
4. ✅ `registrations.team_name` 回写格式改为含 coc_name + clan_tag
5. ✅ `baseline_rebuilder.py` 从 `league_teams` 读取上月配置
6. ✅ Excel 导出新增 `team_name` 列
7. ✅ 迁移脚本 `migrate_results_202607.py` 将旧数据迁入新表
8. ✅ 回填脚本 `backfill_team_names.py` 通过 COC API 补全 team_name

---

## 九、表关系图

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  league_teams    │     │  league_results   │     │  registrations   │
├─────────────────┤     ├──────────────────┤     ├──────────────────┤
│ period          │────▶│ period           │     │ account_name     │
│ team_index      │     │ team_index       │     │ period           │
│ team_alias      │     │ team_alias       │     │ team_name (回写)  │
│ team_name (COC) │     │ team_name (COC)  │     │ league_type      │
│ clan_tag        │     │ clan_tag         │     │ rank_order       │
│ category        │     │ category         │     │ player_tag       │
│ member_count    │     │ player_tag ──────│──┐  └──────────────────┘
│ leader          │     │ account_name     │  │
└─────────────────┘     │ total_stars      │  │
                        │ raw_metrics      │  │
                        └──────────────────┘  │
                                │             │
                                ▼             ▼
                        ┌──────────────────┐
                        │    accounts      │
                        ├──────────────────┤
                        │ player_tag ◀─────┘
                        │ account_name     │
                        │ history_score    │
                        │ trophies         │
                        └──────────────────┘
```
