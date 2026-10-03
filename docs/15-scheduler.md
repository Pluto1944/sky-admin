# 15 — 周期调度

> 生产常驻入口：`scripts/scheduler.py`，服务：`sky-scheduler.service`。
> 每次执行状态存入 `sync_jobs`；不要再增加独立 cron 或竞争性的常驻循环。

## 任务边界

| 任务 | 频率 / 窗口 | 主要写入 | 要点 |
|---|---|---|---|
| `current_wars` | 每 2 分钟检查，按战争状态限频 | `current_war_cache`、结束时 `war_history_cache` / `member_war_facts` | 最终普通战才归档；单部落失败保留上次成功快照 |
| `cwl_live` | 活跃期每 2 分钟 | `cwl_live_group_cache`、`cwl_live_war_cache` | 只采集原始分组/逐场档案；完成后投影成绩 |
| `cwl_assembly` | 月初窗口每 5 分钟 | 名单 revision、集结核对 | 开赛或截止后冻结，不重绑已冻结 revision |
| `farm_stats` | 30 分钟 | `farm_stats` | API 只读缓存，不在请求内批量访问 COC |
| `coc_sync` | 6 小时 | `accounts`、部落资料 | COC 身份和当前归属权威同步 |
| `player_details` | 每天 | 账号详情/活动观察 | 只更新账号领域允许的字段 |
| `member_combat_stats` | 每天 | `member_war_facts` | 仅补齐旧档案的新版事实 |
| `capital_member_stats` | 每 6 小时检查业务窗口 | 都城成员事实 | 周末窗口内运行 |
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

`cwl` 任务和 `scripts/fetch_cwl_data.py` 不访问第三方 API，也不直写成绩；它们只对本地完整档案
进行重建。历史补档使用 `scripts/backfill_cwl_live.py`，默认 dry-run，已有同月原始缓存时拒绝覆盖。

## 运维

```bash
source scripts/load_env.sh
venv/bin/python scripts/scheduler.py --list
venv/bin/python scripts/scheduler.py --once current_wars
systemctl status sky-scheduler.service
```

生产不得手工启动第二个 scheduler 或带 `--reload` 的 uvicorn。代码或配置变更后以 systemd 重启，
并检查服务状态、`sync_jobs` 和真实 API 输出。外部 API 失败是可观测的任务失败，不得以空数据覆盖
已成功缓存。
