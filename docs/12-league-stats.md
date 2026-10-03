# 12 — CWL 联赛战斗数据与统计

> 状态：已实现。当前代码、`docs/02-database.md` 和 `docs/17-cwl-arrangement-sop.md`
> 是业务边界的权威来源。

## 两类联赛数据

报名与战斗数据不能合并：

| 类别 | 表 | 含义 |
|---|---|---|
| 月度报名事实 | `registrations` | 谁报名、当月编排输入 |
| 月度编排快照 | `league_teams` | 安排到哪个 COC 部落；`team_index` 是当月队伍身份 |
| 正式公示版本 | `cwl_roster_snapshots` | 腾讯文档正式名单的不可变 revision |
| 集结审计 | `cwl_assembly_cache` | 正式名单与实际成员的月初核对及冻结结果 |
| 分组目录 | `cwl_live_group_cache` | 一届联赛的部落、轮次与每轮 `war_tag` |
| 单场原始档案 | `cwl_live_war_cache` | 一场 CWL 的完整双方阵容和逐刀攻击 |
| 月度成绩投影 | `league_results` | 从完整原始档案确定性聚合出的每人月度结果 |

前三张报名/编排/公示表不因战斗数据重构而改变。`cwl_assembly_cache` 是开赛前的
到位事实，不是战绩；一旦 `locked_at` 写入，其 `roster_snapshot_id` 不能被后续修订重绑。

## 当前和历史使用同一套原始表

一个 CWL 分组的身份是 `(period, clan_tag)`，一场战争的身份是全局 `war_tag`：

```text
当前 CWL   = 当前 period 的 cwl_live_group_cache + cwl_live_war_cache
历史 CWL   = 历史 period 的同一批表
```

因此 CWL 不另建“当前表 + 历史表”。表名中的 `live_cache` 是保留的物理名称；语义上它们是
可长期保存的原始档案。分组保存赛程目录，战争保存逐场详情；不能把多轮多场战争塞进一个大 JSON。

## 完整性与 `league_results` 投影

`league_results` 保留以支持下月排序/升降级和高效展示，但它不是原始来源：

```text
cwl_live_group_cache + cwl_live_war_cache + league_teams
  -> 完整性校验
  -> league_results
```

对一个 `(period, clan_tag)`，分组目录列出的每个有效 `war_tag` 都必须存在、可解析，并且为
`war_ended`，才是 `complete`。状态为：

- `collecting`：本月仍在收集，或比赛尚未结束；
- `complete`：所有对局均为最终档案，可重建投影；
- `incomplete`：分组已结束但缺少或损坏任一最终档案。

只有 `complete` 允许在同一事务中替换该队 `(period, team_index)` 的所有
`league_results` 行。每支队伍只聚合包含该队的对局；完整分组中其他队之间的比赛只用于完整性验证。
进行中的月度成绩不会进入 `league_results`，从而不会污染下月编排和历史窗口。

进攻统计为我方成员攻击的星数、攻击次数和三星数；防守统计为对手攻击指向我方成员的总数和三星数。
每名玩家每次实际进入一场阵容计一次 `appearances`，该场没有进攻记录则计一次
`missed_attacks`。两项均从最终逐场档案重建，用于保留后续编排所需的出勤与漏刀事实；当前编排
只透传这些字段，尚未把它们加入排序、扣分或升降级公式。漏刀信息未来可作为参赛可靠性的排名
依据，但具体次数/比例、月份窗口、权重和豁免规则尚未确定，以 `docs/03-sorting.md` 的待讨论设计为准。
旧月份在重新投影前为 `NULL`，不能解释为零。
联赛详情页使用上月、前 3 月、前 6 月的滚动聚合；成员主页只显示近 3 个完整月的进攻摘要。

## 任务和补档

- `cwl_live` 在月初活跃窗口持续拉取官方分组和逐场数据；最终战争封存后不重复刷新。
- `cwl` 每日任务不再访问 ClashKing 直接写成绩，只重新检查本地原始档案并投影完整分组。
- `scripts/fetch_cwl_data.py --period YYYY-MM` 只从本地完整档案重建，绝不访问第三方聚合 API。
- `scripts/backfill_cwl_live.py --period YYYY-MM` 默认 dry-run。它只把可验证的完整历史分组和
  逐场档案写入本地，然后重建投影；已有同月原始缓存时拒绝覆盖。

历史补档来源可以是 ClashKing，但绝不能绕过分组/逐场档案直接写入 `league_results`。

## 月份和安全边界

战斗月份统一为 `YYYY-MM`，代表 CWL 实际发生月。编排月 `N` 使用
`registrations(N)`、`league_results(N-1)`、`league_teams(N-1)`；不要将两种月份混用。

小程序/API 请求只读本地表，不直接请求 COC、ClashKing 或腾讯文档。外部公示仍是独立的人工确认步骤，
编排或查询操作不得隐式发布名单。
