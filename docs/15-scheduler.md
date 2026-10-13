# 15 — 周期调度

> 生产常驻入口：`scripts/scheduler.py` 和 `scripts/sync_worker.py`，服务分别为
> `sky-scheduler.service` 和 `sky-sync-worker.service`。任务执行状态存入 `sync_jobs`；
> 常驻进程身份和心跳单独存入 `service_runtime`。
> 不要再增加独立 cron 或竞争性的常驻循环。

## 任务边界

| 任务 | 频率 / 窗口 | 主要写入 | 要点 |
|---|---|---|---|
| `current_wars` | 每 2 分钟检查，按战争状态限频 | `current_war_cache`、结束时 `war_history_cache` / `member_war_facts` | 最终普通战才归档；单部落失败保留上次成功快照 |
| `cwl_live` | 战斗日每 2 分钟；准备日按轮次限频 | `cwl_live_group_cache`、`cwl_live_war_cache` | 合并所有联盟已确认月度队伍并按 Tag 去重；第一轮准备日动态 30/2 分钟；后续准备日由上一轮结束触发 |
| `cwl_assembly` | 月初窗口每 5 分钟 | 名单 revision、集结核对 | 开赛或截止后冻结，不重绑已冻结 revision |
| `farm_stats` | 30 分钟 | `farm_stats` | API 只读缓存，不在请求内批量访问 COC |
| `coc_sync` | 6 小时 | `accounts`、部落资料 | COC 身份和当前归属权威同步 |
| `player_details` | 每天 | 账号详情/活动观察 | 只扫描 high/internal 套餐（及苍穹兼容配置）部落；免费独占部落不逐成员扫描 |
| `member_combat_stats` | 每天 | `member_war_facts` | 仅补齐旧档案的新版事实 |
| `capital_raid_status` | 每 10 分钟检查 | `capital_raid_status_cache` | 只重试尚未开启/失败部落，已开启后停拉；结束后收口最终状态 |
| `capital_member_stats` | 每 6 小时检查业务窗口 | 都城成员事实 | 周二至周三结果窗口内运行 |
| `clan_games_stats` | 每 6 小时检查业务窗口 | 竞赛快照 | 月末窗口内运行 |
| `cwl` | 每天，规则允许日期 | `league_results` | 只从本地完整 CWL 原始档案重建投影 |
| `sync_shadow_plan` | 默认关闭；启用后默认每 5 分钟 | `sync_interests`、`sync_targets`、影子 `sync_tasks` | 只读本地联盟配置和缓存；不访问外部 API、不写业务事实、不接管旧任务 |
| `sync_queue_plan` | 默认关闭；启用后默认每 1 分钟 | 同步需求、目标与 live/shadow 任务 | 按资源类型分阶段接管；Planner 本身不访问外部 API |
| `war_layout` | 北京时间固定时刻 | 独立运行库、公众号草稿 | 默认仅草稿；群发硬开关不可绕过 |

## M4.0 影子规划

`sync_shadow_plan` 将有效 `alliance_clans` 映射为部落资料、成员列表和当前战争需求，并将当月已确认
的 `alliance_cwl_teams` 映射为 CWL 实时需求。多个联盟订阅相同 Tag 时，`sync_targets` 只保留一个
公共目标，并采用最高优先级和最短周期。免费套餐保持低频计划；内部或付费部落的活跃战争采用实时
优先级。当前战争的 2/30 分钟状态规则和错误退避只用于生成对照计划，不改变旧调度器。

功能开关 `SYNC_QUEUE_SHADOW_ENABLED` 默认是 `false`，周期可用
`SYNC_QUEUE_SHADOW_INTERVAL_MINUTES` 调整。关闭时仅建表，不生成影子数据；手工验证可执行：

```bash
source scripts/load_env.sh
venv/bin/python scripts/scheduler.py --once sync_shadow_plan
venv/bin/python scripts/observability_report.py --hours 24
```

M4.0 没有注册真实任务执行器，`current_wars`、`cwl_live`、`coc_sync` 等仍由原调度路径唯一执行。
发生异常时保持影子任务关闭即可，不需要切换或回滚业务事实。

2026-10-11 生产已完成手工影子验收：111 条有效需求合并为 48 个全局目标，生成
48 个 `shadowed` 任务；相同状态立即再规划时新增 0 个任务。该过程没有产生
`sync_attempts` 或外部 API 请求，生产 `sync_shadow_plan` 仍保持 `enabled=0`。

## M4 live Planner 与 Worker

M4 完整链路使用 `sync_queue_plan` 将到期公共目标写为持久化任务，再由独立
`sky-sync-worker.service` 以有限并发执行。当前可切换的资源类型为 `clan_profile`、
`clan_members`、`current_war` 和 `cwl_live`。同一 Tag 被多个联盟订阅仍只生成一个目标和
一个到期任务。

```bash
SYNC_QUEUE_PLANNER_ENABLED=true
SYNC_QUEUE_WORKER_ENABLED=true
SYNC_QUEUE_LIVE_TYPES=clan_profile,clan_members,current_war,cwl_live
```

`SYNC_QUEUE_LIVE_TYPES` 既是切换顺序，也是回滚开关：只有列入的类型会生成 live 任务，对应
旧任务才会跳过。删除某个类型并同时重启 Scheduler/Worker 后，Planner 会取消该类型待执行
live 任务，旧路径恢复。不允许同时启用 `sync_shadow_plan`；它在检测到 live 类型时会拒绝
运行，避免意外将目标切回影子模式。

Worker 并发度默认为 3，最大限制为 8；任务使用租约、心跳、有上限重试和退避。Worker 重启时
会立即中断上一进程的运行尝试并释放租约；Scheduler 重启只收口 Scheduler 自己的运行记录，
不会误中断 Worker。`cwl_live` 虽由队列每 2 分钟唤醒高质量目标，仍由现有单场状态策略
决定是否访问官方 API，不会因切换而重拉所有准备中战争。

2026-10-11 生产已按上述顺序完成四类接管和一次 `clan_profile` 回滚/再接管演练。
四类新旧目标均为 12/12，无 missing/extra；周期 Planner 和第二轮自动战斗日任务均已验收，
生产仍保留按资源类型回滚的 systemd 环境开关。

## M5 免费联盟任务

免费部落由同一 Planner 映射为 `sync_tier=low`：资料和成员默认 24 小时、当前战争保底 6 小时。
首次订阅和手动刷新通过 API 插入 `interactive` live 任务，开放任务与冷却均按公共资源键共享；
`realtime` 始终高于 `interactive`，免费积压不会插到苍穹活跃战争之前。免费联盟配置月度 CWL 队伍后，
沿用 M3.1 月度目标并使用低频 CWL 策略。

每日 `player_details` 只选择 high/internal 套餐（以及迁移期苍穹固定配置）中的当前成员。只被免费
联盟订阅的部落不执行逐成员详情扫描；若同一 Tag 同时被高质量套餐订阅，则仍按最高质量采集一次。

## M8 人工付费权益与到期降级

`alliance_plan_grants` 记录人工开通的付费开始和到期时间。Planner 每次聚合同步需求前幂等收口已经
到期的 `paid` 权益：把权益标记为 `expired`，保留排序最前的一个订阅部落作为 `low` 级兜底，其余
部落改为 `inactive`。该操作只改变联盟私有订阅和同步需求，不删除部落资料、成员、战争、CWL 或
其他公共事实。`player_details` 也显式排除已到期/撤销的付费权益，避免继续承担高成本逐玩家扫描。

读取联盟上下文时即使 Planner 尚未完成下一轮，已到期但仍在 7 天宽限期内的付费权益也会动态显示为
`grace`，并保持原同步等级；超过宽限期后才显示 `expired`、以 `low` 读取并等待 Planner 幂等收口数据库。
查询接口本身不修改数据库。续费后，平台先恢复权益，联盟管理再按需要重新启用此前进入非活跃状态的部落。

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

同步目标由苍穹兼容 `league_teams` 与状态为 `active / frozen / complete` 的
`alliance_cwl_teams` 合并，按规范化 `clan_tag` 全局去重。同一支队伍被多个联盟配置时仍只有一次
官方分组和逐场请求。配置为 `draft` 的月份不进入调度；发现分组后调度器同步把联盟月份状态更新为
`frozen`，全部已发现分组完成后更新为 `complete`。

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
systemctl status sky-sync-worker.service
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
调度器每天清理一次过期运行记录及其请求明细。Scheduler 和 Worker 启动时只会收口各自上一进程
遗留的 `running` 记录；中断轮次不计为业务失败，也不会被误报为仍在运行。

只读诊断命令：

```bash
source scripts/load_env.sh
venv/bin/python scripts/observability_report.py --hours 24
venv/bin/python scripts/observability_report.py --hours 168 --json
```

报告包含任务运行次数、失败数、中断数、仍在运行数、外部请求量、429、成功率、平均/P95/最大耗时，
当前战争、部落资料、成员资料和当月 CWL 的数据新鲜度，以及 M4 需求、目标、任务、过期租约的聚合
计数。该命令以 SQLite `mode=ro` 打开数据库，不执行迁移或写入，也不输出同步资源 Tag。
