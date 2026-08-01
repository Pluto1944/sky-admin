# Teams 配置与排序逻辑全面梳理

## 一、TEAMS 配置体系

### 1.1 TEAMS 数据结构（config.py:100-115）

```python
TEAMS = [
    {"name": "泰坦二",    "clan_tag": "#2QQ",  "category": "combat", "member_count": 15, ...},
    {"name": "冠一 一队",  "clan_tag": "#2GGGGGGG", "category": "combat", ...},
    {"name": "冠二",      "clan_tag": "#2C822CJJC", "category": "combat", ...},
    {"name": "冠三",      "clan_tag": "#2QQQQ2G", "category": "combat", ...},
    {"name": "大一",      "clan_tag": "#UUP2",  "category": "combat", ...},      # team_index=4
    {"name": "大一",      "clan_tag": "#CYYL",  "category": "combat", ...},      # team_index=5
    {"name": "大一",      "clan_tag": "#2CU9JPYU8", "category": "combat", ...},  # team_index=6
    {"name": "大一",      "clan_tag": "#2R9Y209LY", "category": "shell", ...},   # team_index=7
    {"name": "大三",      "clan_tag": "#2JQR89P9G", "category": "shell", ...},   # team_index=8
    {"name": "水一",      "clan_tag": "#2JUJRYVQP", "category": "shell", ...},   # team_index=9
    {"name": "水二",      "clan_tag": "#2GR0LPGVQ", "category": "shell", ...},   # team_index=10
]
```

11 支队伍：7 combat + 4 shell。`team_index` = 列表索引（0~10），**是队伍的唯一身份标识**。

**每个 team dict 字段：**

| 字段 | 含义 | 唯一性 |
|------|------|--------|
| `name` | 队伍别名 | **不唯一**（4支"大一"） |
| `clan_tag` | COC 部落标签 | 唯一 |
| `category` | `"combat"` / `"shell"` | — |
| `member_count` | 队伍容量 | — |
| `reserved_slots` | 预留空位 | — |
| `leader` | 领队名称 | — |
| `league_level` | 联赛等级 | — |
| `manager` | 管理员 | 被 `_assign_managers()` 覆盖 |

### 1.2 TEAMS_LAST（config.py:120-135）

格式与 TEAMS 相同，`clan_tag` 不同（上月队伍配置）。供 `fetch_cwl_data.py` 拉取上月 CWL 数据。

### 1.3 league_teams 表（数据库快照）

```
league_teams(period, team_index, team_alias, team_name, clan_tag, category, ...)
```

- **写入**：`arrange()` 开始时通过 `_write_league_teams()` 幂等写入
- **读取**：`_load_prev_teams_config()` 读取上月配置用于升降级
- **回填**：`fetch_cwl_data.py` 在拉取战绩时回填 `team_name`（COC 真实名称）
- `team_alias` = config 中的 `name`（别名）
- `team_name` = COC API 返回的真实部落名称

### 1.4 三个名字概念对比

| 概念 | 来源 | 唯一性 | 用途 |
|------|------|--------|------|
| **team_index** | `enumerate(teams)` 索引 | **唯一** | 队伍身份标识、分组 key、升降级分组、DB 存储 |
| **team_alias** | config `name` 字段 | 不唯一（4支"大一"） | 人类可读的标签、Excel 展示 |
| **team_name** | COC API 返回 | 唯一 | 真实部落名称、Excel 新增列 |

### 1.5 TEAMS 数据流向图

```
config.py TEAMS / TEAMS_LAST
    │
    ├──► fetch_cwl_data.py
    │       _load_teams_to_fetch(period)
    │       → 过滤 combat 队伍，按 team_index 拉取 CWL API
    │       → 写入 league_results + results（双写）
    │       → 回填 league_teams.team_name（COC 真实名称）
    │
    ├──► roster.py: _write_league_teams(period, teams_cfg)
    │       → 幂等写入 league_teams 表
    │
    ├──► roster.py: _load_prev_teams_config(cwl_period)
    │       → 从 league_teams 读上月配置（回退到 TEAMS）
    │
    ├──► baseline_rebuilder.py: build_temp_lists()
    │       → 过滤 combat 队伍 → prev_combat_teams
    │       → 按 team_index 做分组 key
    │
    ├──► team_builder.py: fill_teams_from_final_list()
    │       → 按列表顺序连续填充队伍
    │       → enumerate(teams) → team_index
    │
    └──► team_builder.py: apply_whitelist()
            → 构建 clan_tag → team_index 映射
```

---

## 二、排序完整流程

### 2.1 流程总览

```
报名数据(registrations) 
  → _load_accounts() 加载 + 注入得分/奖杯
  → sort_accounts() 分组+排序
  → build_final_list() 基准重建+升降级
  → build_teams() 贪心填充队伍
  → arrange_and_export() 导出 Excel
```

### 2.2 阶段详解

#### 阶段 A：数据加载（roster.py:166-211）

`_load_accounts(period)`：
1. 从 `registrations` 表读取本月报名
2. 过滤 `EXCLUDED_CAMP_NAMES`（排除名单）
3. 反查 `accounts` 表获取 `history_score` 和 `trophies`
4. 注入 `prev_rank`（上月排名）
5. 输出每个账号：`{account_name, player_tag, account_type, match_value, join_combat, history_score, trophies, prev_rank, ...}`

#### 阶段 B：分组 + 排序（sorter.py:53-103）

`sort_accounts(accounts, weights)`：

```
全部报名账号
    │
    ├── 战营账号 (account_type=combat)
    │     → league_type = "combat"
    │     → 按 camp_sort_key 排序：trophies 降序（同杯用 rank_score tie-break）
    │     → adjust_camp_by_prev_rank() 微调（当前为恒等操作）
    │
    ├── 普通实战账号 (join_combat=True, account_type≠combat)
    │     → league_type = "combat"
    │     → 按 rank_score（综合分）降序
    │
    └── 壳子账号 (join_combat=False)
          → league_type = "shell"
          → 按 rank_score（综合分）降序
```

**排序键计算（rank_score.py）：**
```
rank_score = 0.6 × norm_match_value + 0.4 × norm_history_score
```
- `match_value`：匹配值（来自报名表）
- `history_score`：历史分（来自 accounts 表）
- 两者先归一化到 [0,1]，再加权求和

**输出字段：**
- `league_type`：combat / shell
- `rank_score`：综合分
- `rank_order`：全局位次（1 开始，实战在前，壳子在后）

**关键：排序不涉及 team 字段**。team_index 仅在后续升降级阶段作为分组 key 使用。

#### 阶段 C：基准重建 + 升降级（baseline_rebuilder.py）

`build_final_list()` → 阶段 0~6：

**阶段 0 — 黑名单过滤**（apply_blacklist）：
从 accounts 和 prev_combat_regs 中排除 BLACK_LIST 中的账号。

**阶段 1 — 构建 7 个临时名单**（build_temp_lists）：
| 名单 | 含义 | 来源 |
|------|------|------|
| list1 | 上月实战名单 | results 表（按 team_index 分组，组内按星数降序） |
| list2 | 当月实战名单 | sort_accounts 输出（league_type=combat） |
| list3 | 当月壳子名单 | sort_accounts 输出（league_type=shell，综合分降序） |
| list4 | 实战缺失 | list1 - list2 |
| list5 | 实战新增 | list2 - list1 |
| list6 | 战营实战新增 | list5 ∩ account_type=combat |
| list7 | 普通营实战新增 | list5 - list6（综合分降序） |

**list1 分组逻辑（基线核心）：**
```python
# 按 team_index 分组（team_index 是唯一身份标识）
team_index_order = [0, 1, 2, 3, 4, 5, 6]  # combat 队伍索引
team_groups = {0: [...], 1: [...], ...}     # 每个 group 是一支队伍
# 组内按星数降序排列
# team_index=None 的旧数据回退到 team_name 分组
```

**阶段 2 — 基准重建 + 升降级**（rebuild_baseline）：
```
list1 → _split_list1_into_slots() → prev_slots（按 team_index 切分）
     → _apply_promotion_relegation_on_slots() → 配对交换
     → 展开为线性列表
```

**升降级配对交换算法：**
```
对每对相邻队伍 (i, i+1)：
  上队 ≤18星 → 降级到 i+1
  下队 ≥21星 → 升级到 i
  配对交换，每对最多换 2 人（PROMOTION_RELEGATION_CONFIG.count）
  19-20星 / 无星数 → 不动
```

**阶段 3 — 删除实战缺失**（remove_missing）：
从 final_list 中移除 list4 成员（上月打实战但本月未报名/转壳）。

**阶段 4 — 插入战营新增**（insert_combat_new）：
在编号 `NEW_COMBAT_INSERT_START=30` 处连续插入 list6。

**阶段 5 — 插入普通营新增**（insert_normal_new）：
list7 全部追加到实战区末尾。

**阶段 6 — 追加壳子名单**（append_shell）：
list3 按综合分降序追加到 final_list 末尾。

**最终输出：** `final_list = [实战区] + [壳子区]`

#### 阶段 D：贪心填充队伍（team_builder.py）

`build_teams()` → 阶段 7~9：

**阶段 7 — 贪心填充**（fill_teams_from_final_list）：
```python
for team_index, team in enumerate(teams):
    members = pool[:capacity]     # 从池中取前 N 人
    pool = pool[capacity:]        # 剩余后移
    cur_team = f"{team_index} {team['name']}"   # 如 "5 大一"
```
按 TEAMS 列表顺序（先 combat 后 shell），从上到下连续填充。

**阶段 8 — 白名单**（apply_whitelist）：
- 按 `clan_tag` 找到目标队伍
- 强制插入到队伍开头
- 超员连锁后移到下一队

**阶段 9 — 管理员分配**（_assign_managers）：
三级优先级：config 列表匹配 → 报名意愿者 → 留空

---

## 三、cur_team 格式演进

### 3.1 历史格式（旧代码）
```
"{team_index} {team_alias}"
例如："5 大一"
```

### 3.2 当前格式（本次重构后）
```
"{team_index} {team_alias} {coc_name}"
例如："5 大一 苍穹·泰坦二"
```

**各阶段 cur_team 生成位置：**

| 阶段 | 文件 | 格式 |
|------|------|------|
| 阶段 7 填充 | team_builder.py:73 | `f"{team_index} {team['name']}"` |
| 阶段 8 白名单 | team_builder.py:176 | `f"{target_idx} {target_team['team_name']}"` |
| 阶段 8 溢出 | team_builder.py:211 | `f"{idx+1} {next_team['team_name']}"` |
| 最终合并 | roster.py:510 | 从 member.cur_team 或统一构造（含 coc_name） |

### 3.3 registrations.team_name 回写格式（本次重构后）
```
"{team_index} {team_alias} {coc_name} {clan_tag}"
例如："5 大一 苍穹·泰坦二 #CYYL"
```
包含完整四段信息，便于后续解析和展示。

---

## 四、team_index 的全链路追踪

```
config.py TEAMS 列表
  │  team_index = enumerate(teams) 索引
  │
  ├──► fetch_cwl_data.py
  │       TEAMS_TO_FETCH = [(i, alias, clan_tag), ...]
  │       → API 拉取时记录 team_index
  │       → 存入 league_results.team_index
  │
  ├──► roster.py: _write_league_teams()
  │       → league_teams.team_index（按月快照）
  │
  ├──► baseline_rebuilder.py: build_temp_lists()
  │       → prev_combat_teams = [t for t in cfg if t["category"] == "combat"]
  │       → team_index_order = [0, 1, 2, 3, 4, 5, 6]
  │       → 按 team_index 分组 → team_groups
  │
  ├──► baseline_rebuilder.py: _split_list1_into_slots()
  │       → 按 team_index 切分 prev_slots
  │       → team_index=None 回退到 team_name 分组
  │
  ├──► team_builder.py: fill_teams_from_final_list()
  │       → enumerate(teams) → team_index
  │       → _build_team_result(team, members, team_index)
  │
  └──► roster.py: 构建 ordered_with_team
          → tr.get("team_index") → cur_team 前缀
          → team_reg_team_name_map → registrations 回写
```

---

## 五、排序相关配置

### 5.1 排序权重（config.py:6-9）
```python
SORT_WEIGHTS = {
    "match_value": 0.6,    # 匹配值权重
    "history_score": 0.4,  # 历史分权重
}
```

### 5.2 升降级配置（config.py:160-164）
```python
PROMOTION_RELEGATION_CONFIG = {
    "count": 2,                   # 每对相邻队伍最多交换人数
    "promotion_min_stars": 21,    # 升级门槛：≥21星（满星）
    "relegation_max_stars": 18,   # 降级门槛：≤18星
}
```

### 5.3 插入编号配置（config.py:217-221）
```python
NEW_COMBAT_INSERT_START = 30     # 战营新增插入位置
NEW_NORMAL_INSERT_START = 45     # 已废弃（改为追加到实战末尾）
```

### 5.4 排除名单（config.py:58）
```python
EXCLUDED_CAMP_NAMES = {"Pluto2QQ", "落花归尘", ...}
```
在 `_load_accounts()` 和 `importer._read_camp()` 两处过滤。

### 5.5 黑白名单（config.py:212-214）
```python
BLACK_LIST = set()                                      # 阶段0过滤
WHITE_LIST = [("10°C✨Godwin 2", "#2QQ")]               # 阶段8强制插入
```

---

## 六、数据表关系

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  league_teams    │     │  league_results   │     │  registrations   │
│  (队伍配置快照)   │     │  (联赛战绩)       │     │  (报名数据)       │
├─────────────────┤     ├──────────────────┤     ├──────────────────┤
│ period          │────▶│ period           │     │ account_name     │
│ team_index ★    │     │ team_index       │     │ player_name      │
│ team_alias      │     │ team_alias       │     │ period           │
│ team_name (COC) │     │ team_name (COC)  │     │ match_value      │
│ clan_tag        │     │ clan_tag         │     │ join_combat      │
│ category        │     │ category         │     │ account_type     │
│ member_count    │     │ player_tag ──────│────▶│ player_tag       │
└─────────────────┘     │ account_name     │     │ team_name (回写)  │
                        │ total_stars      │     │ league_type      │
                        │ attacks          │     │ rank_order       │
                        │ raw_metrics      │     └──────────────────┘
                        └──────────────────┘              │
                               │                          │
                               ▼                          ▼
                        ┌──────────────────┐     ┌──────────────────┐
                        │    accounts      │     │    results (旧)   │
                        │  (账号档案)       │     │  (旧战绩表)       │
                        ├──────────────────┤     ├──────────────────┤
                        │ player_tag ◀─────┼─────│ player_tag       │
                        │ account_name     │     │ period           │
                        │ history_score    │     │ league_type      │
                        │ trophies         │     │ raw_metrics      │
                        └──────────────────┘     └──────────────────┘
```

**关联关系：**
- `league_teams.period + team_index` ←→ `league_results.period + team_index`
- `league_results.player_tag` → `accounts.player_tag`
- `registrations.player_tag` → `accounts.player_tag`（缓存关联，可空）
- `league_results` 双写到 `results`（过渡期兼容）

---

## 七、关键设计决策总结

1. **team_index 是唯一身份标识**：因为 team_alias（别名）可重名（4支"大一"），clan_tag 每月可能变化，只有 team_index 稳定
2. **排序不涉及 team 字段**：排序只看个人能力（match_value、history_score、trophies），team 只在升降级分组和填充阶段出现
3. **prev_teams_config 从数据库读取**：不再硬编码为当月配置，改为从 league_teams 表读取上月配置
4. **双写过渡**：league_results 写入同时双写到旧 results 表，确保旧读取路径兼容
5. **league_teams 幂等写入**：每次 arrange() 都写入当月配置，重复执行不会出错
