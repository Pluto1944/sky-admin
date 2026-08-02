# fetch_cwl_data 整体设计文档

## 1. 概述

`fetch_cwl_data.py` 是 CWL 联赛数据拉取脚本，负责获取指定月份的所有实战队伍 CWL 战绩，并写入数据库。

**核心原则**：fetch 不依赖 `config/settings.yaml` TEAMS 配置（因为 config 可能已更新为下月信息），队伍信息应从 `league_teams` 表获取。

**三级降级策略**：每队拉取时依次尝试三个数据源：
1. 🥇 Supercell 官方 API — 首选，数据最权威
2. 🥈 ClashKing War Log API — 兜底，突破 CWL 窗口期限制
3. 🥉 本地 JSON 文件 — 最后兜底

## 2. 数据流

```
fetch --period 2026-08
  │
  ├─ 1. 查 league_teams WHERE period='2026-08' AND category='combat'
  │     └─ 有数据 → 正常流程：得到队伍列表 (team_index, team_alias, clan_tag)
  │     └─ 无数据 → 冷启动流程：读本地 JSON 回退
  │
  ├─ 2. 逐队三级降级拉取战绩（正常流程）
  │     ├─ 通道1 🥇 Supercell 官方 API → 成功则写 DB
  │     │     └─ 失败/404 → 降级
  │     ├─ 通道2 🥈 ClashKing War Log → 成功则写 DB
  │     │     └─ 失败 → 降级
  │     └─ 通道3 🥉 本地 JSON → 成功则写 DB
  │           └─ 失败 → 🚨 该队全部失败
  │
  └─ 3. 写入目标
        ├─ league_results 表（主力表）
        └─ results 旧表（双写，过渡期兼容）
```

## 3. 两种流程详解

### 3.1 正常流程（league_teams 有数据）

**前置条件**：当月 `arrange` 已执行过，`league_teams` 表中存在对应 period 的 combat 队伍记录。

**步骤**：

1. 查询 `league_teams` 表获取所有 combat 队伍
   ```sql
   SELECT team_index, team_alias, team_name, clan_tag
   FROM league_teams
   WHERE period = ? AND category = 'combat'
   ORDER BY team_index
   ```
   得到列表：`[(team_index, team_alias, team_name, clan_tag), ...]`

2. 逐队三级降级拉取 CWL 战绩：

   **通道1 — Supercell 官方 API**（首选）：
   - `client.get_league_group(clan_tag)` 获取联赛组信息
   - 并发拉取所有 war 详情，汇总每个玩家的 `total_stars` 和 `total_attacks`
   - CWL 窗口期内可用（每月1-10号左右），窗口期外返回 404

   **通道2 — ClashKing War Log API**（兜底）：
   - 调用 `/war/{clan_tag}/previous` 获取历史战争日志
   - 通过 `is_cwl_war()` 筛选 CWL 战斗（teamSize=15/30 + 每人1攻特征）
   - 按 `period` 月份过滤 + 汇总玩家战绩
   - 突破 CWL 窗口期限制，可查历史数据
   - 实现位于 `modules/coc_sync/clashking/client.py`

   **通道3 — 本地 JSON 文件**（最后兜底）：
   - 从 `data/cwl_YYYYMM/` 目录按 `team_alias` 匹配 JSON 文件
   - 适用于 ClashKing 也不可用的极端情况

3. 直接写入数据库（**不保存 JSON 文件**）
   - 写入 `league_results` 表
   - 双写 `results` 旧表

4. 输出数据来源汇总报告
5. 输出升降级参与情况总结

### 3.2 冷启动流程（league_teams 查不到）

**触发条件**：`league_teams` 表中没有对应 period 的 combat 记录。

**步骤**：

1. 打印**显眼告警日志**
   ```
   ╔══════════════════════════════════════════════════════╗
   ║  ⚠️  league_teams 中无 2026-07 的 combat 记录       ║
   ║  ⚠️  进入冷启动模式：尝试从本地 JSON 读取            ║
   ╚══════════════════════════════════════════════════════╝
   ```

2. 尝试读取 `data/cwl_YYYYMM/*.json` 目录
   - 存在 JSON → 遍历所有 JSON 文件，导入 `league_results` + `results` 表
   - 不存在 JSON → 打印最终告警，退出

## 4. 写入数据库详情

### 4.1 league_results 表

| 字段 | 来源 | 说明 |
|------|------|------|
| `period` | `--period` 参数 | CWL 实际发生月 |
| `team_index` | league_teams 查询结果 / JSON 文件 | 队伍编号 |
| `team_alias` | league_teams 查询结果 / JSON 文件 | 队伍别名 |
| `team_name` | league_teams 查询结果 | COC 真实部落名称（arrange 时已写入） |
| `clan_tag` | league_teams 查询结果 / JSON 文件 | 部落 Tag |
| `category` | 固定 `"combat"` | 类别 |
| `player_tag` | API 返回 | 玩家 Tag |
| `account_name` | accounts 表关联查询 | 账号昵称 |
| `total_stars` | API 返回 | 总星数 |
| `attacks` | API 返回 | 攻击次数 |
| `raw_metrics` | 序列化为 JSON | 包含 total_stars, team_name, clan_tag, team_index |

**去重策略**：`ON CONFLICT(period, team_index, player_tag) DO UPDATE`（幂等写入）

### 4.2 results 旧表（双写）

| 字段 | 来源 |
|------|------|
| `player_tag` | API 返回 |
| `period` | `--period` 参数 |
| `league_type` | 固定 `"combat"` |
| `raw_metrics` | 同 league_results 的 raw_metrics |

**去重策略**：`ON CONFLICT(player_tag, period, league_type) DO UPDATE`

## 5. 数据源

| 通道 | 数据源 | 说明 |
|------|--------|------|
| 通道1 🥇 | ClashKing War Log API | 主力数据源，支持按月份筛选历史 CWL 战绩 |
| 通道2 🥈 | 本地 JSON（`data/cwl_YYYYMM/`） | 兜底，ClashKing 不可用时使用 |

注意：Supercell 官方 API 的 `get_league_group` 只能查当前 CWL，不按月份过滤，已从降级链路移除。ClashKing 封装位于 `modules/coc_sync/clashking/client.py`。

## 6. 命令行接口（不变）

```bash
python scripts/fetch_cwl_data.py --period 2026-08
```

- `--period`：必填，CWL 实际发生月（与联赛月相同），如 `2026-08`
- 删除 `--fetch-only` 参数（不再需要仅拉取 JSON 的模式）

## 7. 关键设计决策

| 决策 | 理由 |
|------|------|
| 不依赖 `config/settings.yaml` TEAMS | config 可能已更新为下月信息，且 team list 可能已删除 |
| 不保存 JSON 文件 | JSON 仅用于冷启动，正常流程无需文件缓存 |
| 查 league_teams 而非 league_clans | league_teams 是 arrange 时写入的队伍配置快照，是准确的当月队伍信息来源 |
| 保留 results 旧表双写 | 过渡期兼容，编排时有回退逻辑 |
| 冷启动保留读 JSON 能力 | 首次使用时 league_teams 无数据，需要从历史 JSON 导入 |

## 8. league_teams 数据写入时机

`league_teams` 表由 `arrange()` 在编排时通过 `_write_league_teams()` 幂等写入（`INSERT OR REPLACE`）。

**时间线示例**：
```
2026-08 联赛:
  1. fetch --period 2026-08（查 league_teams WHERE period='2026-08'，查不到则冷启动）
  2. arrange 2026-08（编排，写入 league_teams period='2026-08'）

2026-09 联赛:
  1. fetch --period 2026-09（查 league_teams WHERE period='2026-09'）
     ↑ 此时 league_teams 已有 period='2026-09' 数据（由 arrange 2026-09 写入）
     ↑ 等等，这是先 fetch 再 arrange...
```

**实际正确时间线**：
```
2026-08 联赛:
  1. arrange 2026-08（编排，写入 league_teams period='2026-08'）
  2. fetch --period 2026-08（查 league_teams WHERE period='2026-08'，有数据，正常流程）

2026-09 联赛:
  1. arrange 2026-09（编排，写入 league_teams period='2026-09'）
  2. fetch --period 2026-09（查 league_teams WHERE period='2026-09'，有数据，正常流程）
```

所以**正常流程中 arrange 先于 fetch 执行**，league_teams 中一定有对应 period 的数据。冷启动仅发生在首次使用（历史数据补录）场景。

## 9. 错误处理

| 场景 | 处理 |
|------|------|
| ClashKing API 不可用/无数据 | 自动降级到本地 JSON |
| 单队两个通道全部失败 | 打印 🚨 告警，跳过该队，继续其他队伍 |
| 全部队伍拉取失败 | 打印告警，退出 |
| 冷启动 JSON 不存在 | 打印告警，退出 |
| 玩家不在 accounts 表 | 跳过该玩家记录 |

## 10. ClashKing 集成说明

ClashKing 作为主力数据源，封装在 `modules/coc_sync/clashking/` 目录中：

```
modules/coc_sync/clashking/
├── __init__.py      # 模块说明
└── client.py        # API 封装（HTTP + CWL 筛选 + 战绩汇总）
```

Supercell 官方 API 封装位于 `modules/coc_sync/official/`：

```
modules/coc_sync/official/
├── __init__.py      # 模块说明
├── api_client.py    # CocApiClient HTTP 客户端
└── mapper.py        # COC dict → player 档案映射
```

核心函数：
- `fetch_cwl_players(clan_tag, period)` — 一站式接口，返回格式与 Supercell API 一致
- `is_cwl_war(war)` — CWL 战斗识别（teamSize=15/30 + 每人1攻）
- `filter_cwl_wars(clan_tag, period)` — 筛选指定月份 CWL 战斗
- `aggregate_players(cwl_wars, clan_tag)` — 汇总玩家战绩

HTTP 层使用 `subprocess.curl` 绕过 Cloudflare 防护，数据来源 `https://api.clashk.ing`。
