# 15 — 周期调度方案设计（sync_jobs 常驻调度器）

> 版本：v1.0（2026-08）
> 状态：已实现
> 关联代码：`shared/db/connection.py`（`sync_jobs` 表）、`scripts/scheduler.py`、`deploy/sky-scheduler.service`

---

## 一、背景与目标

### 1.1 现状问题

项目当前有 **4 类** 需要周期性刷新的数据，但脚本各自为政，存在以下痛点：

| 问题 | 现状 | 影响 |
|------|------|------|
| 脚本形态不统一 | `sync_farm_stats.py` 用 `--loop` 常驻循环；其余脚本是一次性执行 | 运维需要两套心智模型 |
| 无运行状态记录 | 每次运行结果只打印到 stdout，无处查询 | 报错后无法追溯、无法判断"上次到底成功没有" |
| 调度分散难管理 | 各脚本定时方式不一，无统一入口 | 增删任务、改频率、启停都要手动操作 |
| 调试不便 | 手动触发要靠记住各脚本的命令行参数 | 开发时反复补数据效率低 |

> 注：`docs/periodic-scripts.md` 早期描述过 `systemd timer`（`sky-sync-*.timer`）+ `manage-cron.sh` 方案，但那些文件实际从未落地；当前 `deploy/` 只有 `sky-admin.service`（FastAPI 后端）。本方案取代旧的 timer 方案。

### 1.2 目标

1. **周期 + 手动**：生产环境常驻自动刷新，开发调试时可单次手动触发任意任务
2. **状态可查**：每次运行的状态、错误、耗时、次数落库，`--list` 一目了然
3. **报错可管**：单任务失败不影响其它任务和常驻进程，失败信息持久化可追溯
4. **便捷管理**：统一入口启停任务、调整频率、强制执行

---

## 二、数据表现状

### 2.1 数据表全景

系统共 **9 张表**（`shared/db/connection.py` 中定义），按数据生命周期分三类：

| 表名 | 职责 | 主键 | 数据来源 | 刷新方式 |
|------|------|------|----------|----------|
| `accounts` | 玩家档案（COC 权威） | `player_tag` | COC 官方 API | **周期**（每天） |
| `registrations` | 月度报名（自包含事实源） | `id` 自增 | 腾讯文档报名表 | 人工（每月） |
| `results` | 月度战绩（旧表，过渡） | `id` 自增 | `fetch_cwl_data` 双写 | 周期（每月） |
| `league_teams` | 队伍配置快照 | `id` 自增 | `arrange()` 幂等写入 | 人工（每月） |
| `league_results` | 联赛战绩（结构化） | `id` 自增 | ClashKing API / 本地 JSON | **周期**（每月 12 号） |
| `war_results` | 普通部落战战绩 | `id` 自增 | ClashKing API | **周期**（每天） |
| `wechat_users` | 微信用户绑定 | `openid` | 微信小程序 | 实时（用户登录） |
| `farm_stats` | 互刷部落统计缓存 | `clan_tag` | COC 官方 API | **周期**（每 30 分钟） |
| `sync_jobs` | 调度器任务状态（待新增） | `job_id` | `scheduler.py` | 实时（调度器维护） |

> `results` 为过渡期旧表，`league_results` 写入时双写，稳定后废弃。
> `sync_jobs` 为周期调度方案新增的状态表，详见第三节。

### 2.2 表读写关系矩阵

| 表 | 写入者 | 读取者 |
|----|--------|--------|
| `accounts` | `coc_sync`、`war_result` | `player-export`、`import-reg`、`arrange`、`fetch_cwl_data`、`api_server` |
| `registrations` | `import-reg`、`arrange`（回写） | `arrange`、`refresh_status`、`api_server` |
| `results` | `fetch_cwl_data`（双写） | `arrange`（回退读取） |
| `league_teams` | `arrange`（幂等写入） | `arrange`、`fetch_cwl_data` |
| `league_results` | `fetch_cwl_data` | `arrange`、`api_server`（league-stats） |
| `war_results` | `fetch_war_data` | `api_server`（war-stats） |
| `wechat_users` | `api_server`（登录/绑定） | `api_server` |
| `farm_stats` | `sync_farm_stats` | `api_server`（farm-config） |
| `sync_jobs` | `scheduler.py` | `scheduler.py`（`--list`） |

### 2.3 需要周期性刷新的任务（4 类）

| job_id | 数据表 | 脚本 | 数据源 | 频率 | 前端接口 |
|--------|--------|------|--------|------|----------|
| `coc_sync` | `accounts` | `cli.py coc-sync` | COC 官方 API | 每天 | `/api/members` |
| `farm_stats` | `farm_stats` | `sync_farm_stats.py` | COC 官方 API | 每 30 分钟 | `/api/clan/farm-config` |
| `war_results` | `war_results` | `fetch_war_data.py` | ClashKing API | 每天 | `/api/clan/war-stats` |
| `cwl` | `league_results`+`results` | `fetch_cwl_data.py` | ClashKing API | 每月 12 号 | `/api/clan/league-stats` |

其余表（`registrations`、`league_teams`、`wechat_users`）由月度人工流程或用户实时操作写入，**不纳入周期刷新**。

### 2.4 各周期任务详情

#### `coc_sync` — 部落成员档案（`accounts`）

| 项 | 内容 |
|----|------|
| 入口 | `cli.py coc-sync` → `modules/coc_sync/service.py::CocSyncService.sync_clans()` |
| 数据源 | Supercell 官方 COC API `/clans/{tag}/members` |
| 建议频率 | 每天（`interval_min=360`，即每 6 小时兜底一次） |
| 逻辑 | 遍历联盟部落拉成员 → 写 `accounts` → 退部对账（标记 `membership_status=left`） |

#### `farm_stats` — 互刷部落大本配置（`farm_stats`）

| 项 | 内容 |
|----|------|
| 入口 | `scripts/sync_farm_stats.py`（`get_all_farm_stats()`） |
| 数据源 | COC 官方 API `/clans/{tag}/members` + `/clans/{tag}/currentwar` |
| 建议频率 | 每 30 分钟（`interval_min=30`） |
| 逻辑 | 并行拉 8 个互刷部落成员+战争 → 计算 TH 分布（实时 + 去速本）→ 写 `farm_stats` |

> 该脚本原生支持 `--loop` 常驻模式，调度方案落地后由 `scheduler.py` 统一接管，`--loop` 标记废弃。

#### `war_results` — 普通部落战战绩（`war_results`）

| 项 | 内容 |
|----|------|
| 入口 | `scripts/fetch_war_data.py --clan-tag "#2QQ"` |
| 数据源 | ClashKing War Log API `/war/{tag}/previous` |
| 建议频率 | 每天（`interval_min=1440`） |
| 逻辑 | 拉 war log → 筛普通战（排除 CWL）→ 满星前统计 → 写 `war_results`（`ON CONFLICT DO NOTHING` 幂等） |

#### `cwl` — CWL 联赛战绩（`league_results` + `results`）

| 项 | 内容 |
|----|------|
| 入口 | `scripts/fetch_cwl_data.py --period YYYY-MM` |
| 数据源 | ClashKing API（主力）→ 本地 JSON（兜底） |
| 建议频率 | 每月 12 号（`interval_min=1440` + `day==12` 判断） |
| 逻辑 | 查 `league_teams` 得 combat 队 → 逐队拉星数 → 双写 `league_results` + `results` |

### 2.5 人工触发（月度流程，不纳入周期）

| 表 | 触发时机 | 脚本/命令 |
|----|----------|-----------|
| `registrations` | 每月开赛前 | `register_and_arrange.sh <period>` |
| `league_teams` | 每月编排时 | `cli.py arrange`（`_write_league_teams()`） |
| `wechat_users` | 用户登录/绑定时 | 微信小程序 → `api_server` |

### 2.6 数据源对照

| 数据源 | 用途 | 凭证 |
|--------|------|------|
| Supercell 官方 COC API | 成员同步、互刷统计 | `COC_API_TOKEN`（env） |
| ClashKing War Log API | CWL 战绩、部落战战绩 | 无需认证 |
| 本地 JSON（`data/cwl_YYYYMM/`） | CWL 兜底/冷启动 | — |
| 腾讯文档 OpenAPI v3 | 报名表读写、名单导出 | `TENCENT_DOC_*`（env） |

---

## 三、总体设计

### 3.1 架构

```
┌──────────────────────────────────────────────────────────────┐
│  scripts/scheduler.py（常驻 loop 进程，systemd 守护）            │
│                                                              │
│   ┌────────────────────────────────────────────────────────┐ │
│   │  主循环：遍历 JOBS → 判断是否到期 → run_one(job)         │ │
│   └────────────────────────────────────────────────────────┘ │
│                          │                                   │
│              ┌───────────┼───────────────┐                  │
│              ▼           ▼               ▼                  │
│         run_farm     run_coc_sync     run_war ...           │
│              │           │               │                  │
│              └───────────┴───────────────┘                  │
│                          │                                   │
│                          ▼                                   │
│              sync_jobs 表（状态/错误/耗时/次数）               │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 核心决策

| 决策点 | 结论 |
|--------|------|
| 运行形态 | 常驻 loop 进程 + systemd 守护，状态存 `sync_jobs` 表 |
| 调度模型 | 纯间隔 `interval_min`，**不引入 cron** |
| CWL 任务 | `interval_min=1440`（每天触发），函数内判断 `day==12` 才真正拉取，其余天返回 `skipped`，**不做时刻对齐** |
| 状态表 | 最小可用版（状态/错误/耗时/次数） |
| 失败策略 | 失败也推进 `next_run_at`，避免高频重试 |

---

## 四、任务定义

### 4.1 `sync_jobs` 状态表（新增）

```python
_SYNC_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS sync_jobs (
    job_id        TEXT PRIMARY KEY,
    job_name      TEXT,
    interval_min  INTEGER DEFAULT 1440,
    enabled       INTEGER DEFAULT 1,
    last_run_at   TEXT,
    next_run_at   TEXT,
    last_status   TEXT,   -- success / failed / skipped / running / never
    last_error    TEXT,
    last_duration REAL,
    run_count     INTEGER DEFAULT 0,
    fail_count    INTEGER DEFAULT 0,
    extra         TEXT
);
"""
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `job_id` | TEXT PK | 任务唯一标识（如 `farm_stats`） |
| `job_name` | TEXT | 人类可读名称（如「互刷部落统计」） |
| `interval_min` | INTEGER | 刷新间隔（分钟） |
| `enabled` | INTEGER | 是否启用（0/1） |
| `last_run_at` | TEXT | 上次运行时间 |
| `next_run_at` | TEXT | 下次计划运行时间 |
| `last_status` | TEXT | 上次运行状态：`success`/`failed`/`skipped`/`running`/`never` |
| `last_error` | TEXT | 上次错误信息（成功时为空） |
| `last_duration` | REAL | 上次运行耗时（秒） |
| `run_count` | INTEGER | 累计运行次数 |
| `fail_count` | INTEGER | 累计失败次数 |
| `extra` | TEXT | 扩展 JSON（备用） |

### 4.2 任务表

| job_id | job_name | interval_min | 说明 |
|--------|----------|-------------|------|
| `farm_stats` | 互刷部落统计 | 30 | 拉 8 个互刷部落成员+战争，计算 TH 分布 |
| `coc_sync` | COC 玩家档案 | 360 | 同步联盟成员到 `accounts`（每天 6 小时一次） |
| `war_results` | 普通部落战战绩 | 1440 | 拉取战营 `#2QQ` 部落战，写 `war_results` |
| `cwl` | CWL 联赛战绩 | 1440 | 每天触发，`day==12` 才真正拉当月 CWL |

> `interval_min` 首次写入 `sync_jobs` 后，可通过 `--set-interval` 调整。

---

## 五、CWL 任务的日期判断（方案 B）

CWL 战绩要求「每月 12 号同步一次」，任意时刻即可，不做凌晨 1 点对齐。采用**纯间隔 + 日期判断**：

```python
def run_cwl():
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    if today.day != 12:
        return {"status": "skipped", "reason": f"非12号（今天{today.day}号），跳过"}

    period = today.strftime("%Y-%m")  # 拉当月 CWL
    teams = _load_teams_from_db(period)
    if not teams:
        return {"status": "skipped", "reason": f"{period} 无 league_teams，跳过"}

    # 复用 fetch_cwl_data.py 的 _fetch_and_write
    _fetch_and_write(period, teams)
    return {"status": "success"}
```

### 为什么不用 cron 表达式

| 方案 | 优点 | 缺点 |
|------|------|------|
| A. 引入 cron 表达式 | 语义精确、可表达「12号1点」 | 需引入 cron 解析库，与「纯间隔」模型两套并存，复杂度上升 |
| **B. 纯间隔 + day 判断（采用）** | 复用统一间隔模型，零新依赖，代码简单 | 12 号当天会多次触发（每次 `skipped` 后仍按间隔推进） |
| C. 一次性精确时间 | 精确 | 状态机复杂，失败需重排，得不偿失 |

**结论**：选 B。12 号当天 `interval_min=1440` 下只会触发 1~2 次，第一次 `day==12` 命中即拉取成功；即便当天进程重启导致重跑，`fetch_cwl_data` 的 `ON CONFLICT DO UPDATE` 幂等机制保证不产生脏数据。

---

## 六、调度器核心逻辑

### 6.1 `run_one(job)` 状态流转（异常安全）

```python
def run_one(job):
    # 1. 置 running
    _update(job, last_status="running")

    # 2. 执行（try 包裹，单任务异常不影响其它任务和常驻进程）
    try:
        start = time.monotonic()
        result = job["run"]()            # 返回 {"status": "success"/"skipped", "reason": ...}
        duration = time.monotonic() - start
        _update(job, last_status=result["status"], last_duration=duration,
                last_error=result.get("reason", ""), run_count=+1)
    except Exception as e:
        _update(job, last_status="failed", last_error=str(e),
                fail_count=+1, run_count=+1)

    # 3. 无论成败都推进 next_run_at = now + interval（失败不阻塞，避免高频重试）
    _update(job, last_run_at=now, next_run_at=now + interval_min)
```

关键点：

- **失败也推进 `next_run_at`**：否则失败任务会每轮循环都被重试，把进程卡在错误循环里
- **单任务隔离**：一个任务抛异常，`try/except` 兜住，主循环继续下一任务
- **`skipped` 语义**：CWL 非 12 号、无 league_teams 等情况返回 `skipped`，不算失败也不计入 `fail_count`

### 6.2 主循环

```python
def loop():
    while True:
        now = datetime.now()
        for job in JOBS.values():
            if not job.enabled:
                continue
            if job.next_run_at and now < job.next_run_at:
                continue
            run_one(job)
        time.sleep(60)   # 每分钟轮询一次
```

---

## 七、CLI 接口

```bash
python scripts/scheduler.py                    # loop 模式（生产，systemd 守护）
python scripts/scheduler.py --once farm_stats  # 手动执行单个任务（调试）
python scripts/scheduler.py --once all         # 手动执行全部任务
python scripts/scheduler.py --once cwl --force # --force 跳过 day==12 判断，强制拉取
python scripts/scheduler.py --list             # 查看所有任务状态
python scripts/scheduler.py --enable farm_stats    # 启用任务
python scripts/scheduler.py --disable farm_stats   # 停用任务
python scripts/scheduler.py --set-interval farm_stats 60   # 调整间隔（分钟）
```

| 参数 | 说明 |
|------|------|
| `--once <job_id\|all>` | 单次执行（不进入常驻循环），调试/补数据用 |
| `--force` | 搭配 `--once` 使用，跳过 CWL 的 `day==12` 判断 |
| `--list` | 打印 `sync_jobs` 表全部任务状态 |
| `--enable` / `--disable` | 切换任务启用状态 |
| `--set-interval <分钟>` | 调整任务刷新间隔 |

---

## 八、systemd 守护

`deploy/sky-scheduler.service`（新增）：

```ini
[Unit]
Description=Sky Admin Periodic Sync Scheduler
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/YANG/sky-admin
ExecStart=/home/ubuntu/YANG/sky-admin/venv/bin/python scripts/scheduler.py
Restart=always
StandardOutput=append:/var/log/sky-scheduler.log
StandardError=append:/var/log/sky-scheduler-error.log

[Install]
WantedBy=multi-user.target
```

管理命令：

```bash
sudo systemctl status sky-scheduler          # 查看运行状态
sudo systemctl restart sky-scheduler         # 修改代码后重启
sudo systemctl stop sky-scheduler            # 停止常驻调度
journalctl -u sky-scheduler -f               # 实时日志
```

---

## 九、状态管理速查

| 场景 | 命令 |
|------|------|
| 查看全部任务状态 | `python scripts/scheduler.py --list` |
| 手动补一次 farm 数据 | `python scripts/scheduler.py --once farm_stats` |
| 强制拉当月 CWL（跳过日期判断） | `python scripts/scheduler.py --once cwl --force` |
| 临时停用某任务 | `python scripts/scheduler.py --disable farm_stats` |
| 恢复某任务 | `python scripts/scheduler.py --enable farm_stats` |
| 调整刷新频率 | `python scripts/scheduler.py --set-interval farm_stats 60` |
| 看报错原因 | `python scripts/scheduler.py --list`（看 `last_error` 列） |

---

## 十、落地清单（已全部实现）

1. `shared/db/connection.py`：新增 `_SYNC_JOBS_DDL`，挂载进 `_CHILDREN_DDL`，`_migrate()` 幂等建表 ✅
2. `scripts/scheduler.py`：新增调度器（任务定义 + run_one + 主循环 + CLI）✅
3. `deploy/sky-scheduler.service`：新增 systemd 单元 ✅
4. `deploy/README.md`：补充 sky-scheduler 运维命令 ✅
5. `docs/periodic-scripts.md`：标注旧 timer 方案已废弃，指向本文档 ✅
6. `scripts/sync_farm_stats.py`：标注 `--loop` 已由调度器接管 ✅

---

## 十一、边界与注意事项

| 场景 | 处理 |
|------|------|
| 任务抛异常 | `try/except` 兜底，记录 `failed` + `fail_count`，进程不退出 |
| 进程重启 | `next_run_at` 已持久化，重启后按计划继续；到期的立即补跑 |
| 首次启动 | `next_run_at` 为空 → 立即执行一次，之后按间隔推进 |
| CWL 非 12 号 | 返回 `skipped`，不计数失败 |
| CWL 12 号重复触发 | `fetch_cwl_data` 幂等（`ON CONFLICT DO UPDATE`），无脏数据 |
| 多实例误启 | systemd 单实例管理，避免手动再起一份 |

---

## 十二、相关文档

- `02-database.md` — 表结构详细定义与 ER 图
- `06-operations.md` — 月度循环与运维脚本
- `periodic-scripts.md` — 旧方案说明（已废弃）
