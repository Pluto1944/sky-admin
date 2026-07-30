# 实战队伍升降级系统 — 设计文档

> **版本**: v2.0
> **日期**: 2026-07-30
> **状态**: 已实现，135 测试全绿

---

## 目录

1. [问题背景](#1-问题背景)
2. [核心设计思路](#2-核心设计思路)
3. [算法详述](#3-算法详述)
4. [配置参数](#4-配置参数)
5. [数据流与架构](#5-数据流与架构)
6. [冷启动方案](#6-冷启动方案)
7. [文件变更清单](#7-文件变更清单)
8. [测试覆盖](#8-测试覆盖)
9. [COC API 数据采集](#9-coc-api-数据采集)
10. [运行流程](#10-运行流程)
11. [后续演进方向](#11-后续演进方向)

---

## 1. 问题背景

### 现状

- **壳子队伍**：按匹配值排序，排序结果正确
- **实战队伍**：7 支从上到下强度递减（泰坦二 → 冠一一队 → 冠一二队 → 冠三 → 大一 × 3）
- `fill_teams()` 按排序名单依次填充各队，首次分配合适，但**无法根据实际表现做动态调整**

### 核心矛盾

不同队伍的比赛强度不同，**三星率不可直接横向比较**：
- 在泰坦二打 18/21 的玩家，表现可能好于在大一打 21/21 的玩家
- 无法将所有实战队员的三星率拉通统一排序

### 解法：升降级制度

在 `fill_teams()` 完成基础队伍分配后，根据**上月联赛实际表现**，在相邻队伍之间执行人员交换：
- 上队星数低的 → 降级到下队
- 下队满星的 → 升级到上队

---

## 2. 核心设计思路

### 月份语义（重要）

```
CWL 时间线（以 8 月联赛为例）：

  7/1-7    7 月 CWL 战争 → 产生星数
  7/8-31   为 8 月 CWL 报名 → 产生报名数据
  8/1-7    8 月 CWL 战争（本次编排的目标）

系统接口的 period 语义（v2.5 统一）：
- `import-reg` / `arrange` / `import-result`：**联赛月份**（如 2026-08）
- `fetch_cwl_data.py`：**CWL 实际发生月**（拉哪月传哪月，如 2026-07）
- `registrations.period` = 联赛月份，`results.period` = CWL/战绩实际发生月

```
  arrange("2026-08")                ← 联赛月份（8 月 CWL）
       │
       ├── registrations WHERE period="2026-08"   读报名数据（直接，无需 -1）
       │
       ├── cwl_period = _prev_period("2026-08") = "2026-07"  ← 上月 CWL
       │     └── _load_combat_star_data("2026-07")  读星数数据
       │
       └── prev_rank 从 "2026-07"     ← 联赛月 -1（上月编排结果）
```

**两个时间维度互不混淆：**

| 操作 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份 | `--period 2026-08` |
| `arrange` | 联赛月份 | `--period 2026-08` |
| `fetch_cwl_data.py` | CWL 实际发生月 | `--period 2026-07` |

### 流程

```
原有流程                             新增步骤
─────────                           ─────────
_load_accounts(reg_period)
       ↓
sort_accounts()
       ↓
fill_teams()  ──────────────┐
       ↓                     ↓
       ↓           apply_promotion_relegation()  ← 新增
       ↓                     ↓
回写 team_name ←─────────────┘
       ↓
rebuild_assignment_map()      ← 升降级后修复映射
```

### 设计原则

1. **离散星数比较**：总星数 0-21，用整数直接比较，不需要浮点比率
2. **只在边界流动**：只动每队的前几名和后几名，大部分人员稳定
3. **满星才能升**：升级门槛严格限定 21/21
4. **低于门槛才降**：≤ 18/21 才降级，19-20 星的安全区人员不动
5. **每人每月最多跳 1 级**：`moved` 集合阻止同轮重复移动
6. **配置驱动**：所有阈值在 `config.py` 中可调
7. **纯函数设计**：`promotion.py` 无 IO，便于测试

---

## 3. 算法详述

### 输入

| 参数 | 类型 | 说明 |
|------|------|------|
| `team_results` | `list[dict]` | `fill_teams()` 的输出，每队含 `team_name`, `category`, `members` |
| `star_data` | `dict[str, int]` | `{account_name: total_stars}`，实战星数 |
| `config` | `dict` | `PROMOTION_RELEGATION_CONFIG` |

### 步骤

```
对于每对相邻实战队伍 (Team_Higher, Team_Lower)，自上而下依次处理：

┌─── 步骤 1：识别实战队伍 ──────────────────────────────┐
│ 从 team_results 中筛选 category=="combat" 的队伍       │
│ 按配置顺序，从第 0 队到第 n-2 队，依次与下一队配对处理  │
└────────────────────────────────────────────────────────┘

┌─── 步骤 2：筛选降级候选（来自 Team_Higher）────────────┐
│ 条件：                                                  │
│  · 有星数数据（在 star_data 中）                        │
│  · total_stars ≤ relegation_max_stars（默认 18）        │
│  · 不在 moved 集合中                                    │
│                                                         │
│ 按 total_stars 升序排列，取前 count 人                  │
└────────────────────────────────────────────────────────┘

┌─── 步骤 3：筛选升级候选（来自 Team_Lower）──────────────┐
│ 条件：                                                  │
│  · 有星数数据（在 star_data 中）                        │
│  · total_stars ≥ promotion_min_stars（默认 21）         │
│  · 不在 moved 集合中                                    │
│                                                         │
│ 按 total_stars 降序排列，取前 count 人                  │
└────────────────────────────────────────────────────────┘

┌─── 步骤 4：配对交换 ───────────────────────────────────┐
│ 将降级候选与升级候选按序配对：                          │
│   第 1 降级 ↔ 第 1 升级                                │
│   第 2 降级 ↔ 第 2 升级                                │
│                                                         │
│ 如果某侧候选不足，有多少换多少                          │
│ 已移动的人加入 moved 集合，本轮后续不再参与              │
└────────────────────────────────────────────────────────┘
```

### 实际函数签名

```python
# modules/cwl_registration/promotion.py

def apply_promotion_relegation(
    team_results: list[dict],
    star_data: dict[str, int],
    config: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """返回 (调整后的 team_results, 升降级日志列表)。"""

def rebuild_assignment_map(
    ordered_with_team: list[dict],
    team_results: list[dict],
) -> None:
    """升降级交换后重建 ordered_with_team 的 team_name 映射。"""
```

### 示例场景

| 队伍 | 成员 | 星数 | 资格 |
|------|------|------|------|
| 泰坦二 | 张三 | 15 | ≤18 → 降级候选 #1 |
| 泰坦二 | 李四 | 17 | ≤18 → 降级候选 #2 |
| 泰坦二 | 王五 | 19 | 不动（安全区） |
| 冠一一队 | 孙七 | 21 | 满星 → 升级候选 #1 |
| 冠一一队 | 周八 | 21 | 满星 → 升级候选 #2 |

**处理 泰坦二 ↔ 冠一一队：**
1. 降级候选：[张三(15), 李四(17)]
2. 升级候选：[孙七(21), 周八(21)]
3. 配对交换：张三↓ 孙七↑ / 李四↓ 周八↑

**下一对 冠一一队 ↔ 冠一二队：**  
张三、李四现在在冠一一队（刚降级），由于在 `moved` 集合中，不会在同轮继续降级。

---

## 4. 配置参数

`modules/cwl_registration/config.py`：

```python
PROMOTION_RELEGATION_CONFIG = {
    "count": 2,                  # 每对相邻队伍最多交换人数
    "promotion_min_stars": 21,   # 升级门槛：≥ 此值才可升级（满星）
    "relegation_max_stars": 18,  # 降级门槛：≤ 此值触发降级
}
```

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `count` | 2 | 每对相邻队伍最多交换人数 |
| `promotion_min_stars` | 21 | 升级所需最少星数（满星） |
| `relegation_max_stars` | 18 | 触发降级的最大星数 |

**设计理由**：
- 升级门槛 21/21：避免"接近满星"的人升到更强队后表现断崖下跌
- 降级门槛 ≤18/21：给 19-20 星留出安全区，防一两次失误即降级
- 星数离散（0-21 整数），天然有 ≥3 星的 gap

---

## 5. 数据流与架构

### 模块结构

```
modules/cwl_registration/
├── promotion.py          ← 新增：升降级纯函数
├── config.py             ← 修改：PROMOTION_RELEGATION_CONFIG
├── roster.py             ← 修改：LeagueArranger 集成升降级
├── repository.py         ← 修改：prev_team_assignments()
├── sorter.py             ← 不变
├── team_filler.py        ← 不变

modules/war_result/
└── repository.py         ← 修改：get_results_by_period()

modules/player/
└── service.py            ← 修改：resolve_name_by_tag()
```

### `roster.py` 集成（LeagueArranger）

```python
class LeagueArranger:
    def __init__(self, player_service, reg_repo, excel_io, result_repo=None):
        ...

    def arrange(self, period, weights=None, teams=None,
                combat_min_match_value=None, star_data=None):
        """period = 联赛月份（如 "2026-08"）。"""
        # registrations.period = 联赛月份，直接查询
        accounts = self._load_accounts(period)
        ordered = sort_accounts(accounts, ...)
        ordered_with_team, team_results = fill_teams(ordered, ...)
        
        # 升降级（星数从上月 CWL 加载：联赛月 -1）
        cwl_period = _prev_period(period)
        star_data = star_data or self._load_combat_star_data(cwl_period)
        team_results, movements = apply_promotion_relegation(team_results, star_data, ...)
        rebuild_assignment_map(ordered_with_team, team_results)
        
        # 回写
        ...

    def _load_combat_star_data(self, period):
        """从 results 表加载实战星数 {account_name: total_stars}。"""
        rows = self.result_repo.get_results_by_period(period, league_type="combat")
        # tag → account_name 反查
        ...
```

### 冷启动入口

`arrange()` 接受 `star_data` 参数，显式传入时跳过 DB 查询：

```python
# 冷启动：直接传入 star_data
arranger.arrange("2026-08", star_data={"张三": 15, "李四": 21, ...})

# 正常：从 results 表自动加载
arranger.arrange("2026-08")  # 内部读 results WHERE period="2026-07"
```

### `raw_metrics` 数据格式

```json
{"total_stars": 18, "total_attacks": 7}
```

`_extract_total_stars()` 兼容多种格式：
1. `{"total_stars": 18}` → 直接取
2. `{"three_stars": 15, "two_stars": 4, ...}` → 3×15 + 2×4 + ...
3. 无法解析 → None（该账号不参与升降级）

---

## 6. 冷启动方案

### 冷启动数据准备

| 步骤 | 内容 | 产出 |
|------|------|------|
| ① COC API 采集 | 对 6 支实战队伍的 clan_tag 调 leaguegroup API | 28 warTag/队，共 168 个 |
| ② 拉明细 | 逐 warTag 调 clanwarleagues/wars/{warTag} | 每人每场星数 |
| ③ 导出 JSON | `fetch_cwl_data.py` | `data/cwl_202607/*.json`（7 个） |
| ④ #2QQ 手工补录 | 战营不参加 CWL，手动提供 tag+星数 | `泰坦二_战营.json` |

### 冷启动执行

```bash
# 1. 导入 8 月报名表（联赛月份）
python cli.py import-reg 8月报名表.xlsx --period 2026-08

# 2. 预览星数据映射
python scripts/cold_start_arrange.py --period 2026-08 --dry-run

# 3. 执行编排（联赛月份，自动推算 CWL 月 + 数据目录）
python scripts/cold_start_arrange.py --period 2026-08 -o 2026-08名单.xlsx
```

`--period 2026-08` → 自动：
- CWL 月 = 2026-07（联赛-1）
- 数据目录 = `data/cwl_202607/`
- 读 `registrations WHERE period="2026-08"`
- 星数 JSON 映射到 `{account_name: total_stars}`
- 执行升

> boyyang 最新补充：2QQ 上月联赛队员 tag+星数
> 
> #LRYY0PYL0=21  #8U2RUPVJL=21  #P2CLCU0QL=20  #G9C9GU0PG=20  #GPCVG9G9C=20  #QUQUP99PL=19  #LYVPLQJ2=19  #GJLQUVVJC=19  #QGUQL9VRR=19  #G2R2UU20=19  #Q88LPL89L=18  #LJ8U9QR9=18  #QRRYURCQ0=18  #QVPQ9Q2R2=17  #QCRGU229R=17
> 
> 直接手动录入为泰坦二_战营.json

### 冷启动数据依赖关系

```
data/cwl_202607/*.json ──→ load_star_data() ──→ {account_name: total_stars}
                                                       ↓
2026-07 报名数据 ──→ fill_teams() ──→ 基础分配 ──→ apply_promotion_relegation()
                                                       ↓
                                                  升降级日志 + 最终分配
                                                       ↓
                                              回写 DB + 导出 Excel
```

---

## 7. 文件变更清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `modules/cwl_registration/promotion.py` | 升降级纯函数 + rebuild_assignment_map |
| `tests/cwl_registration/test_promotion.py` | 12 个升降级单元测试 |
| `scripts/fetch_cwl_data.py` | COC API 批量拉 CWL 战绩 JSON |
| `scripts/probe_cwl_data.py` | COC API 端点探测 |
| `scripts/cold_start_arrange.py` | 冷启动编排脚本（JSON → arrange） |
| `WORK_STATE.md` | 工作状态备忘 |
| `data/cwl_202607/*.json` | 7 支队伍 2026-07 CWL 战绩数据 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `modules/cwl_registration/config.py` | 新增 `PROMOTION_RELEGATION_CONFIG` |
| `modules/cwl_registration/roster.py` | LeagueArranger 新增 `result_repo`、`_load_combat_star_data()`；`arrange()` 集成升降级；参数改为联赛时间 |
| `modules/cwl_registration/repository.py` | 新增 `prev_team_assignments()` |
| `modules/war_result/repository.py` | 新增 `get_results_by_period()` |
| `modules/player/service.py` | 新增 `resolve_name_by_tag()` |
| `cli.py` | LeagueArranger 传入 `result_repo`；适配新返回值 |
| `tests/cwl_registration/test_roster.py` | arrange 周期改为联赛时间 |

### 无需修改的文件

| 文件 | 原因 |
|------|------|
| `sorter.py` | 升降级不改变排序逻辑 |
| `team_filler.py` | 升降级是 fill_teams 的后处理 |
| `rank_score.py` | 综合分计算不变 |
| `shared/db/connection.py` | 表结构无需变更 |

---

## 8. 测试覆盖

### 测试文件：`tests/cwl_registration/test_promotion.py`（12 个）

| # | 场景 | 预期结果 |
|---|------|----------|
| 1 | 基本升降级，两队各有 2 候选 | 2 升 2 降，4 条日志 |
| 2 | 升级候选不足（下队 1 人满星） | 1 升 1 降 |
| 3 | 降级候选不足（上队 1 人 ≤18） | 1 升 1 降 |
| 4 | 无候选（无人满足条件） | 0 日志，队伍不变 |
| 5 | 安全区不动（19 星） | 不在候选列表 |
| 6 | 无星数数据跳过（新人） | 不参与升降级 |
| 7 | moved 集合阻止同轮重复移动 | 每人最多跳 1 级 |
| 8 | 3 支实战队级联 | 逐对处理，日志正确 |
| 9 | 空队伍 | 无异常 |
| 10 | 仅壳子队伍 | 返回原结果，日志为空 |
| 11 | 自定义配置 | 阈值可覆盖 |
| 12 | rebuild_assignment_map | team_name 正确回写 |

完整测试套件：**135 passed**

---

## 9. COC API 数据采集

### API 端点能力总结

| 端点 | warTag | 每人星数 | 可用时机 |
|------|--------|----------|----------|
| `/clans/{tag}/currentwar/leaguegroup` | ✅ 唯一来源 | — | CWL 周 + 结束后保留期 |
| `/clans/{tag}/warlog` | ❌ 无 | ❌ 无 | 始终可用 |
| `/clans/{tag}/currentwar` | ❌ 无 | ❌ 无 | 开战时 |
| `/clanwarleagues/wars/{warTag}` | — | ✅ 每场每人明细 | warTag 有效期内 |

### 数据采集链路

```
leaguegroup → warTags[28] → clanwarleagues/wars/{warTag} → per-player stars
```

### 关键发现

1. **leaguegroup 在结束后仍可查**（state="ended"），但新赛季开始后可能失效
2. **warlog 不含 warTag**，事后无法通过 warlog 回溯 CWL 每人明细
3. **`attacksPerMember=1`** 可在 warlog 中区分 CWL 和常规 war
4. **战营 #2QQ 不参加 CWL**，leaguegroup 返回 404，需手工录入

### 数据采集脚本

```bash
# 探测 API 端点
python scripts/probe_cwl_data.py '#2QQ'

# 批量拉取 6 支实战队伍 CWL 战绩
python scripts/fetch_cwl_data.py
# → data/cwl_202607/冠一_一队.json ... (7 个文件)
```

### CocApiClient 待扩展方法

`modules/coc_sync/api_client.py`（当前用猴子补丁，正式应移入）：

```python
def get_clan_warlog(self, clan_tag, limit=None) -> list[dict]
def get_cwl_war(self, war_tag) -> dict
def get_league_group(self, clan_tag) -> dict | None
```

---

## 10. 运行流程

### 每月完整流程（以 8 月联赛为例）

```bash
# 步骤 1：导入报名表（联赛月份 = 8 月）
python cli.py import-reg 8月报名表.xlsx --period 2026-08

# 步骤 2：编排 + 导出（联赛月份 = 8 月，升降级自动生效）
python cli.py arrange --period 2026-08 -o 2026-08名单.xlsx
```

### 冷启动补充步骤

```bash
# 步骤 0a：拉取 CWL 战绩 JSON（一次性）
python scripts/fetch_cwl_data.py

# 步骤 0b：冷启动编排（用 JSON 替代 DB 星数）
python scripts/cold_start_arrange.py --period 2026-08 -o 2026-08名单.xlsx
```

### 升降级生效规则

```
首次冷启动：
  - 从 JSON 加载星数，传入 arrange(period, star_data=...)
  - 如果无星数数据 → 跳过升降级，按原逻辑填充

后续月份：
  - arrange() 自动从 results 表加载同期星数（period - 1 月）
  - 上月没打实战的新人 → 不参与升降级
```

### 控制台输出示例

```
[升降级] 本月人员调整：
  小小龙 (16星) ↓降级: 泰坦二 → 冠一 一队
  丶抱抱丶 (21星) ↑升级: 冠一 一队 → 泰坦二
  楪祈 (18星) ↓降级: 泰坦二 → 冠一 一队
  孤芳时自赏 (21星) ↑升级: 冠一 一队 → 泰坦二
  ...
=== 升降级汇总 ===
升级 8 人, 降级 8 人, 共 16 条变动
```

---

## 11. 后续演进方向

### 阶段二（3-4 个月后）

在积累了多个月的每队"难度系数"数据后：
- 计算每队难度系数 = 队总星数 / 队总进攻次数
- 个人校准三星率 = 个人三星率 / 所在队伍难度系数
- 将校准率融入 `history_score.py`
- 升降级制度保留作为安全网

### 阶段三（长期）

- 引入 Elo / Glicko 能力分体系
- 每次进攻视为一场"比赛"：对手强度 × 你的表现
- 更精确地反映个人能力

---

## 附录 A：术语表

| 术语 | 说明 |
|------|------|
| combat team | 实战队伍（泰坦二/冠一/冠三/大一），参加 CWL 联赛 |
| shell team | 壳子队伍，不参加 CWL，仅用于奖杯排序 |
| 联赛月份 | `arrange` / `import-reg` / `import-result` 的参数，CWL 实际所在月（如 2026-08） |
| CWL 实际发生月 | `fetch_cwl_data.py` 的参数，拉哪月 CWL 就传哪月；编排 N 月联赛时传 N-1 月 |
| total_stars | 一个玩家在一个月 CWL 中发起进攻获得的总星数（最大 21） |
| three_star_rate | 三星率 = total_stars / (3 × n_wars) |
| promotion | 升级：从低强度队升到高强度队 |
| relegation | 降级：从高强度队降到低强度队 |
| cold start | 冷启动：首次运行，用 JSON 数据替代 DB 星数 |
| moved set | 已移动账号集合，保证同轮内每人最多跳 1 级 |
| leaguegroup | COC API 端点，CWL 战争组的元数据（含所有 warTag） |

## 附录 B：项目文件结构（相关部分）

```
sky-admin/
├── modules/
│   ├── cwl_registration/
│   │   ├── config.py          ← TEAMS / PROMOTION_RELEGATION_CONFIG
│   │   ├── sorter.py          ← sort_accounts()
│   │   ├── team_filler.py     ← fill_teams()
│   │   ├── promotion.py       ← 【新增】apply_promotion_relegation()
│   │   ├── roster.py          ← LeagueArranger（升降级集成）
│   │   ├── repository.py      ← RegistrationRepository
│   │   └── importer.py        ← 报名表导入
│   ├── war_result/
│   │   ├── repository.py      ← ResultRepository（新增 get_results_by_period）
│   │   ├── history_score.py
│   │   └── importer.py
│   └── player/
│       └── service.py         ← PlayerService（新增 resolve_name_by_tag）
├── scripts/
│   ├── probe_cwl_data.py      ← COC API 探测脚本
│   ├── fetch_cwl_data.py      ← CWL 战绩 JSON 采集
│   └── cold_start_arrange.py  ← 【新增】冷启动编排
├── data/
│   └── cwl_202607/            ← 7 支队伍的战绩 JSON
├── tests/
│   └── cwl_registration/
│       ├── test_promotion.py  ← 【新增】12 个升降级测试
│       └── test_roster.py     ← 联赛时间适配
└── docs/
    └── promotion_relegation_design.md  ← 【本文档】
```
