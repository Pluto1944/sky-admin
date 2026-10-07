# 15 — 周期调度

> 生产常驻入口：`scripts/scheduler.py`，服务：`sky-scheduler.service`。
> 每次任务执行状态存入 `sync_jobs`；调度器进程身份和心跳单独存入 `service_runtime`。
> 不要再增加独立 cron 或竞争性的常驻循环。

## 任务边界

| 任务 | 频率 / 窗口 | 主要写入 | 要点 |
|---|---|---|---|
| `current_wars` | 每 2 分钟检查，按战争状态限频 | `current_war_cache`、结束时 `war_history_cache` / `member_war_facts` | 最终普通战才归档；单部落失败保留上次成功快照 |
| `cwl_live` | 战斗日每 2 分钟；准备日按轮次限频 | `cwl_live_group_cache`、`cwl_live_war_cache` | 第一轮准备日动态 30/2 分钟；后续准备日由上一轮结束触发并保留 30 分钟兜底 |
| `cwl_assembly` | 月初窗口每 5 分钟 | 名单 revision、集结核对 | 开赛或截止后冻结，不重绑已冻结 revision |
| `farm_stats` | 30 分钟 | `farm_stats` | API 只读缓存，不在请求内批量访问 COC |
| `coc_sync` | 6 小时 | `accounts`、部落资料 | COC 身份和当前归属权威同步 |
| `player_details` | 每天 | 账号详情/活动观察 | 只更新账号领域允许的字段 |
| `member_combat_stats` | 每天 | `member_war_facts` | 仅补齐旧档案的新版事实 |
| `capital_raid_status` | 每 10 分钟检查 | `capital_raid_status_cache` | 只重试尚未开启/失败部落，已开启后停拉；结束后收口最终状态 |
| `capital_member_stats` | 每 6 小时检查业务窗口 | 都城成员事实 | 周二至周三结果窗口内运行 |
| `clan_games_stats` | 每 6 小时检查业务窗口 | 竞赛快照 | 月末窗口内运行 |
| `cwl` | 每天，规则允许日期 | `league_results` | 只从本地完整 CWL 原始档案重建投影 |
| `war_layout` | 北京时间固定时刻 | 独立运行库、公众号草稿 | 默认仅草稿；群发硬开关不可绕过 |

## 普通战归档

`current_wars` 先写当前缓存。只有确认普通战为完整 `war_ended` 后，才在同一事务：

1. 写或更新 `(clan_tag, war_key)` 的完整历史档案；
2. 物化所有成员的进攻和防守事实；
3. 清理该部落第 45 场以外的历史及其事实；
4. 标记 `history_sealed_at`。

网络错误、非最终状态或归档异常均不得触发清理。回填使用
`scripts/backfill_war_history.py`：默认 dry-run，只有所有启用部落通过校验后才可 `--apply`。

## CWL 原始档案和投影

`cwl_live` 将当月每队的分组目录和目录中每个 `war_tag` 独立保存。每个分组计算
`raw_status`：采集中、完整或已结束但缺档。只有完整分组会调用投影器重建
`league_results`；进行中的成绩不得进入该表。

CWL 的第二轮至最后一轮准备日与上一轮战斗日重叠，因此调度器只对当前战斗日保持
2 分钟高频刷新。第一轮准备日平时每 30 分钟刷新，开战前 30 分钟提升到 2 分钟；
后续准备日首次入库后每 30 分钟兜底，并在上一轮任一战争新确认 `warEnded` 时立即刷新
下一轮。已经结束的 `war_tag` 永久停拉，单场请求失败不阻塞同组其余战争。

`cwl` 任务和 `scripts/fetch_cwl_data.py` 不访问第三方 API，也不直写成绩；它们只对本地完整档案
进行重建。历史补档使用 `scripts/backfill_cwl_live.py`，默认 dry-run，已有同月原始缓存时拒绝覆盖。

## 运维

常驻 loop 启动时冻结 `VERSION`、Git commit、`git describe` 和已跟踪工作区状态，并以
`component=scheduler` 写入 `service_runtime`。主循环每轮以及每个任务执行后更新心跳；长任务运行期间
允许最多 15 分钟无新心跳。`--once` 和 `--list` 是临时命令，不覆盖常驻进程身份。

```bash
source scripts/load_env.sh
venv/bin/python scripts/scheduler.py --list
venv/bin/python scripts/scheduler.py --once current_wars
venv/bin/python scripts/scheduler.py --once capital_raid_status --force
systemctl status sky-scheduler.service
curl -fsS http://127.0.0.1:8000/api/system/version
```

生产不得手工启动第二个 scheduler 或带 `--reload` 的 uvicorn。代码或配置变更后以 systemd 重启，
并检查服务状态、`sync_jobs` 和真实 API 输出。外部 API 失败是可观测的任务失败，不得以空数据覆盖
已成功缓存。

## 可观测性

每次 `run_one` 都会在 `sync_job_runs` 保存一条逐轮记录，并把该轮内已接入观测的外部请求批量写入
`external_request_events`。当前覆盖 COC 官方 API、ClashKing、腾讯文档 MCP/OpenAPI，以及阵型任务的
SocialData、X、微信公众号和图片下载请求。记录内容仅包括来源、操作、资源键、结果分类、HTTP 状态、
耗时和异常类型，不保存 Token、请求头或响应正文。

外部请求观测采用进程内收集、任务结束后批量落库。创建、完成或清理观测记录失败时只输出警告，
不能改变业务任务的成功或失败状态。历史默认保留 30 天，由 `OBSERVABILITY_RETENTION_DAYS` 调整；
调度器每天清理一次过期运行记录及其请求明细。

只读诊断命令：

```bash
source scripts/load_env.sh
venv/bin/python scripts/observability_report.py --hours 24
venv/bin/python scripts/observability_report.py --hours 168 --json
```

报告包含任务运行次数、失败数、外部请求量、429、成功率、平均/P95/最大耗时，以及当前战争、部落
资料、成员资料和当月 CWL 的数据新鲜度。该命令以 SQLite `mode=ro` 打开数据库，不执行迁移或写入。
