# 苍穹联赛管理系统 — 全流程与数据流文档

> 版本：v2.0（联赛重构后）
> 更新日期：2026-08-01

---

## 一、系统总览

### 1.1 系统定位

管理部落联赛（CWL）月度循环：成员同步 → 报名导入 → 名单编排 → 战绩拉取 → 升降级 → 结果发布。

| 脚本 | 执行频率 | 核心职责 |
|------|---------|---------|
| `sync_and_export.sh` | 每天 | COC API 同步成员 → accounts 表 |
| `fetch_cwl_data.sh` | 每月 7 号 | COC API 拉取 CWL 战绩 → league_results + results |
| `register_and_arrange.sh` | 每月底 | 报名导入 → 编排+升降级 → 发布联赛安排 |

### 1.2 period 语义

```
registrations.period = 联赛月份（实际打 CWL 的月份）
league_results.period = CWL 实际发生月
league_teams.period = 联赛月份

编排 N 月联赛：读 registrations(N) + league_results(N-1)
```

---

## 二、register_and_arrange.sh 详解

```
register_and_arrange.sh 2026-08
  │
  ├─ [1] import-reg --period 2026-08
  │     腾讯文档报名表 → registrations(period=2026-08)
  │
  ├─ [2] fetch_cwl_data.py --period 2026-07
  │     COC API → league_results + results（双写）
  │     若 REG_PERIOD=2026-07 则跳过（数据已迁移）
  │
  └─ [3] arrange --period 2026-08
        → 读 registrations(2026-08) + league_results(2026-07)
        → 从 league_teams 读 team_name 注入 teams_cfg
        → 基准重建 + 升降级 + 队伍填充
        → 导出腾讯文档 "名单_2026-08"
```

### 2.1 编排流程（v3.0 基准重建）

```
arrange(period)
  ├─ 从 league_teams 读 team_name → 注入 teams_cfg.coc_name
  ├─ _write_league_teams() 幂等写入当月配置
  ├─ _load_accounts() 加载报名 + 注入分数/奖杯
  ├─ sort_accounts() 分组+排序
  ├─ _load_combat_star_data() 从 league_results 读星数
  ├─ _load_prev_combat_from_results() 从 league_results 读上月名单
  ├─ _load_prev_teams_config() 从 league_teams 读上月配置
  ├─ build_final_list() 基准重建+升降级（阶段0~6）
  ├─ build_teams() 贪心填充+白名单+管理员（阶段7~9）
  ├─ 构建 ordered_with_team（含 team_name COC真实名称）
  ├─ 白名单人员插入到 Part1 对应队伍开头
  └─ arrange_and_export() 导出 Excel
```

### 2.2 排序流程

```
sort_accounts()
  ├─ 战营账号 (account_type=combat) → 按 trophies 降序
  ├─ 普通实战 (join_combat=True)    → 按 rank_score 降序
  └─ 壳子 (join_combat=False)       → 按 rank_score 降序

rank_score = 0.6 × norm_match_value + 0.4 × norm_history_score
```

### 2.3 升降级参数

```python
PROMOTION_RELEGATION_CONFIG = {
    "count": 2,                # 每对相邻队伍最多交换人数
    "promotion_min_stars": 21,  # 升级门槛：满星
    "relegation_max_stars": 18, # 降级门槛：≤18星
}
```

---

## 三、Excel 输出结构

输出 sheet 包含 4 个部分：

| Part | 内容 | team_name 列 |
|------|------|-------------|
| Part1 | 排序名单（含白名单） | COC 真实名称 |
| Part2 | 队伍明细（逐队展示） | COC 真实名称 |
| Part3 | 离队/缺失/黑名单 | 上月队伍别名 |
| Part4 | 联赛名单排布网格（5列） | — |

**ARRANGEMENT_OUTPUT_HEADERS**：
```
rank_order, league_type, cur_team, prev_team, movement,
player_tag, account_name, player_name, team_name, account_type,
prev_rank, trophies, match_value, history_score
```

---

## 四、数据库表

| 表 | 职责 | 状态 |
|----|------|------|
| `accounts` | 账号档案 | 活跃 |
| `registrations` | 月度报名 | 活跃 |
| `league_teams` | 队伍配置快照 | **新增** |
| `league_results` | 联赛战绩 | **新增** |
| `results` | 旧战绩表 | 过渡期保留 |

---

## 五、配置体系

### 报名编排配置（config.py）

| 配置项 | 说明 |
|--------|------|
| `SORT_WEIGHTS` | 综合分权重：match_value 0.6 / history_score 0.4 |
| `TEAMS` | 当月队伍配置（7 combat + 4 shell） |
| `PROMOTION_RELEGATION_CONFIG` | 升降级参数 |
| `BLACK_LIST` | 黑名单 |
| `WHITE_LIST` | 白名单（强制插入指定队伍） |
| `MANAGER_CANDIDATES` | 管理员候选列表 |
| `EXCLUDED_CAMP_NAMES` | 战营排除名单 |
| `NEW_COMBAT_INSERT_START` | 战营新增插入点 30 |

> `TEAMS_LAST` 已删除，上月配置从 `league_teams` 表读取。

---

## 六、核心概念

| 概念 | 含义 | 唯一性 |
|------|------|--------|
| `team_index` | 队伍在 TEAMS 中的顺序索引 | **唯一** |
| `team_alias` | 别名（config name） | 不唯一 |
| `team_name` | COC 真实部落名称 | 唯一 |
| `clan_tag` | COC 部落 Tag | 唯一 |

---

## 七、月度循环时间线

| 日期 | 操作 |
|------|------|
| 每天 | `sync_and_export.sh` 同步成员 |
| 月底 | `register_and_arrange.sh 2026-08` 编排 8 月联赛 |
| 8月7号 | `fetch_cwl_data.sh --period 2026-08` 拉取 8 月战绩 |
| 9月底 | `register_and_arrange.sh 2026-09` 编排 9 月联赛 |

---

## 八、数据目录结构

```
data/
├── league.db                    # SQLite 主数据库
├── cwl_202607/                  # CWL 战绩 JSON 缓存
│   ├── 0_泰坦二.json
│   └── ...
├── scripts/
│   ├── migrate_results_202607.py   # 旧数据迁移脚本
│   └── backfill_team_names.py      # team_name 回填脚本
└── docs/
    ├── league_database_refactor.md     # 数据库重构方案
    ├── database_and_dataflow.md        # 数据库与数据流
    ├── teams_and_sorting_analysis.md   # Teams 与排序分析
    ├── system_workflow.md              # 全流程文档
    ├── combat_baseline_design.md       # 基准重建方案
    ├── promotion_relegation_design.md  # 升降级方案
    └── roster_part4_design.md          # Part4 设计
```
