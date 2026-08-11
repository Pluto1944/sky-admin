# 周期性数据更新脚本说明

## 概述

项目中有 **4 张数据库表** 的数据需要通过外部 API 拉取，对应 **3 个独立脚本** 负责周期性更新。

---

## 1. 部落成员档案同步 (`accounts` 表)

| 项目 | 内容 |
|---|---|
| **脚本入口** | `cli.py coc-sync`（通过 `scripts/sync_and_export.sh` 包装） |
| **核心模块** | `modules/coc_sync/service.py` — `CocSyncService.sync_clans()` |
| **数据来源** | Supercell 官方 COC API（`/clans/{tag}/members`） |
| **建议频率** | **每天 1 次**（推荐凌晨执行，如 `0 8 * * *`） |
| **影响接口** | `GET /api/members`— 成员列表 |

### 更新逻辑
1. 遍历所有联盟部落，调用 COC API 获取成员列表
2. 将每个成员信息写入 `accounts` 表（INSERT 或 UPDATE）
3. 执行"退部对账"：对比新旧成员列表，发现已退出成员则标记 `membership_status=left`

### 数据字段
昵称、等级、经验值、奖杯数、大本等级、部落归属、部落职位、联赛段位等。

---

## 2. 互刷部落大本配置统计 (`farm_stats` 表)

| 项目 | 内容 |
|---|---|
| **脚本** | `scripts/sync_farm_stats.py` |
| **核心逻辑** | `get_all_farm_stats()` → 拉取成员 + 部落战数据 → 计算 TH 分布 |
| **数据来源** | Supercell 官方 COC API（`/clans/{tag}/members` + `/clans/{tag}/currentwar`） |
| **建议频率** | **每 30 分钟**（脚本原生支持 `--loop` 循环 + `--interval` 自定义） |
| **影响接口** | `GET /api/clan/farm-config`— 互刷部落配置 |

### 更新逻辑
1. 并行拉取 8 个互刷部落的成员数据
2. 并行拉取各部落当前战争状态
3. 计算 TH 分布统计（大本等级分布 + 去速本后的阶段归类）
4. 写入 `farm_stats` 表（INSERT OR REPLACE）

### 运行方式
```bash
# 单次执行
python scripts/sync_farm_stats.py

# 常驻循环模式（每 30 分钟刷新）
python scripts/sync_farm_stats.py --loop --interval 1800
```

---

## 3. CWL 联赛战绩 (`league_results` 表)

| 项目 | 内容 |
|---|---|
| **脚本** | `scripts/fetch_cwl_data.py --period YYYY-MM` |
| **核心逻辑** | `fetch_cwl_players()` → 双写 `league_results` + `results` 表 |
| **数据来源** | ClashKing War Log API（主力）→ 本地 JSON 文件（降级兜底） |
| **建议频率** | **每月 1 次**（CWL 结束后执行） |
| **影响接口** | `GET /api/clan/league-stats`— 联赛战绩滚动三星率 |

### 更新逻辑
1. 按月份查询 ClashKing API 获取各战营 CWL 对战数据
2. 聚合每位玩家的总星数、进攻次数、防守次数
3. 计算进攻三星率、防守三星率
4. 双写 `league_results`（新表）+ `results`（旧表兼容）

### 运行方式
```bash
# 拉取指定月份联赛数据
python scripts/fetch_cwl_data.py --period 2026-07

# 通常由一站式脚本调用
bash scripts/register_and_arrange.sh
```

### API 接口滚动窗口
前端 `league-stats` 接口支持 **1 月 / 3 月 / 6 月** 滚动窗口计算三星率。

---

## 4. 普通部落战战绩 (`war_results` 表)

| 项目 | 内容 |
|---|---|
| **脚本** | `scripts/fetch_war_data.py --clan-tag "#2QQ"` |
| **核心逻辑** | `fetch_war_log()` → 筛选普通战 → `aggregate_regular_war_players()` |
| **数据来源** | ClashKing War Log API |
| **建议频率** | **每天 1 次**（推荐凌晨执行） |
| **影响接口** | `GET /api/clan/war-stats`— 部落战战绩滚动三星率 |

### 更新逻辑
1. 拉取指定部落的战斗日志
2. 筛选出普通部落战（排除 CWL）
3. 按玩家聚合进攻/防守数据
4. 计算满星前的进攻三星率、防守三星率
5. 按 `end_time` 唯一键写入 `war_results`（INSERT OR IGNORE，保证幂等）

### 运行方式
```bash
python scripts/fetch_war_data.py --clan-tag "#2QQ"
```

### API 接口滚动窗口
前端 `war-stats` 接口支持 **5 场 / 15 场 / 45 场** 滚动窗口计算三星率。

---

## 汇总

| 序号 | 数据表 | 脚本 | 频率 | 数据源 | API 接口 |
|---|---|---|---|---|---|
| 1 | `accounts` | `coc-sync` | 每天 | COC 官方 API | `/api/members` |
| 2 | `farm_stats` | `sync_farm_stats.py` | 每 30 分钟 | COC 官方 API | `/api/clan/farm-config` |
| 3 | `league_results` | `fetch_cwl_data.py` | 每月 | ClashKing API | `/api/clan/league-stats` |
| 4 | `war_results` | `fetch_war_data.py` | 每天 | ClashKing API | `/api/clan/war-stats` |

---

## 定时调度架构

定时任务通过 **systemd user timer** 管理，与主服务 `sky-admin.service` 统一体系：

```
deploy/systemd/
├── sky-sync-accounts.service   # 同步部落成员档案
├── sky-sync-accounts.timer     # 每天 8:00
├── sky-sync-farm.service       # 同步互刷统计数据
├── sky-sync-farm.timer         # 每 30 分钟
├── sky-sync-war.service        # 拉取部落战数据
├── sky-sync-war.timer          # 每天 9:00
├── sky-sync-cwl.service        # 拉取 CWL 联赛战绩
└── sky-sync-cwl.timer          # 每月 28 号 10:00
```

| Timer | 脚本 | 频率 | 超时 |
|---|---|---|---|
| `sky-sync-accounts` | `cli.py coc-sync` | 每天 8:00 | 10 分钟 |
| `sky-sync-farm` | `sync_farm_stats.py` | 每 30 分钟 | 5 分钟 |
| `sky-sync-war` | `fetch_war_data.py --clan-tag "#2QQ"` | 每天 9:00 | 15 分钟 |
| `sky-sync-cwl` | `fetch_cwl_data.py --period <上月>` | 每月 28 号 10:00 | 15 分钟 |

所有日志统一通过 `journalctl` 查看，无需手动管理日志文件。

---

## 定时任务管理

使用 `scripts/manage-cron.sh` 统一管理所有定时任务，覆盖日常运维场景。

### 场景一：查看所有任务状态

```bash
bash scripts/manage-cron.sh status
```

输出每个 timer 的运行状态、下次触发时间、上次执行结果。

### 场景二：手动执行一次（测试 / 补数据）

```bash
# 执行指定任务，自动显示实时日志
bash scripts/manage-cron.sh run accounts    # 手动同步成员档案
bash scripts/manage-cron.sh run farm        # 手动同步互刷数据
bash scripts/manage-cron.sh run war         # 手动拉取部落战数据
bash scripts/manage-cron.sh run cwl         # 手动拉取 CWL 战绩
```

`run` 命令会立即触发一次 service 执行，等待完成后报告成功或失败。

### 场景三：查看任务日志

```bash
# 查看最近 50 行日志
bash scripts/manage-cron.sh logs accounts
bash scripts/manage-cron.sh logs farm

# 实时跟踪日志（Ctrl+C 退出）
bash scripts/manage-cron.sh logs accounts -f
```

所有日志存储于 journald，`logs` 命令实际调用 `journalctl --user -u <unit>`。

### 场景四：修改代码后重启定时任务

```bash
# 重启单个 timer（重读 service 文件和最新代码依赖）
bash scripts/manage-cron.sh restart accounts
bash scripts/manage-cron.sh restart farm

# 或直接使用 systemctl
systemctl --user restart sky-sync-farm.timer
```

### 其他管理命令

```bash
bash scripts/manage-cron.sh stop <任务名>       # 停止单个 timer
bash scripts/manage-cron.sh start <任务名>      # 启动单个 timer
bash scripts/manage-cron.sh enable-all          # 批量启用所有 timer
bash scripts/manage-cron.sh disable-all         # 批量停用所有 timer
```

### 日志排查速查表

| 场景 | 命令 |
|---|---|
| 最近一次执行是否成功 | `bash scripts/manage-cron.sh status` |
| 查看失败时的错误信息 | `bash scripts/manage-cron.sh logs <任务名>` |
| 实时观察执行过程 | `bash scripts/manage-cron.sh logs <任务名> -f` |
| 查看特定时间段的日志 | `journalctl --user -u sky-sync-farm --since "2026-08-01" --until "2026-08-02"` |

---

## 初始部署

```bash
# 一键安装所有 timer
bash deploy/install-cron.sh

# 查看是否安装成功
bash scripts/manage-cron.sh status
```

安装脚本会：
1. 复制 service + timer 文件到 `~/.config/systemd/user/`
2. 执行 `loginctl enable-linger`（确保用户登出后 timer 仍运行）
3. 重新加载 systemd 配置并启用所有 timer
