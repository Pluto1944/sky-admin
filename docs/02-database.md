# 02 — 数据库结构与数据所有权

> 数据库：SQLite `data/league.db`。DDL 与幂等迁移的唯一位置是
> `shared/db/connection.py`；本文件说明业务语义，而不是替代代码。

## 表概览

| 类别 | 表 | 键 / 身份 | 责任 |
|---|---|---|---|
| COC 账号事实 | `accounts` | `player_tag` | COC 账号、当前部落归属、活动观察；只由 `modules/player` 写账号领域数据 |
| 月度报名 | `registrations` | `(account_name, period)` | 自包含报名事实；`player_tag` 可为空关联缓存，不设 accounts 外键 |
| 月度编排 | `league_teams` | `(period, team_index)` | 编排完成时的队伍配置快照 |
| 正式公示 | `cwl_roster_snapshots` | `(period, revision)` | 腾讯文档正式名单不可变版本 |
| 集结审计 | `cwl_assembly_cache` | `(period, clan_tag)` | 正式名单和实际成员核对；冻结后保留使用的 revision |
| CWL 原始目录 | `cwl_live_group_cache` | `(period, clan_tag)` | 分组、轮次、`war_tag` 目录与完整性状态 |
| CWL 原始战争 | `cwl_live_war_cache` | `war_tag` | 双方完整阵容、逐刀攻击和最终状态 |
| CWL 投影 | `league_results` | `(period, team_index, player_tag)` | 仅由完整 CWL 原始档案确定性重建的月度成绩 |
| 当前普通战 | `current_war_cache` | `clan_tag` | 当前或最近成功的战争状态、错误降级与归档触发 |
| 普通战原始历史 | `war_history_cache` | `(clan_tag, war_key)` | 每部落最多 45 场已结束普通战完整档案 |
| 普通战事实投影 | `member_war_facts` | `(clan_tag, war_key, player_tag)` | 可重建的逐玩家进攻/防守查询事实 |
| 互刷统计 | `farm_stats` | `clan_tag` | 互刷部落配置与去速本统计缓存 |
| 账号外部身份 | `wechat_users` | `openid` | 微信登录和账号绑定 |
| 都城贡献 | `capital_raid_member_results` | `(clan_tag, start_time, player_tag)` | 突袭周末成员事实 |
| 竞赛贡献 | `clan_games_member_snapshots` | `(period, player_tag)` | 月末成就快照和差值 |
| 部落资料 | `clan_profile_cache` | `clan_tag` | 自有部落官方资料缓存 |
| 调度状态 | `sync_jobs` | `job_id` | 周期任务的状态、时间和失败信息 |

## 普通部落战

`current_war_cache` 是覆盖更新的当前状态，不承担历史；`war_history_cache` 只保存最终
`war_ended` 普通战，包含来源、最终封存时间、载荷版本、哈希和完整 JSON。未结束或请求失败不能清理
历史。`member_war_facts.metric_version=2` 表示已按“满星前、最高星增量、进攻防守独立”规则物化。

历史保留为每个启用自有部落最近 45 场。普通战页面以当前 `accounts.clan_tag` 决定成员，按部落
固定 5/15/45 场窗口聚合；成员主页则按玩家实际参战、90 天和最多 15 场聚合。详细口径见
[`13-war-stats.md`](13-war-stats.md)。

## CWL

`cwl_live_group_cache` 和 `cwl_live_war_cache` 是 CWL 的原始事实层；物理名称保留以降低迁移风险，
不代表可随意清空。分组以 `(period, clan_tag)` 存赛程目录，单场以 `war_tag` 存完整战争，因而同一套
表同时承载当前月和历史月。

`raw_status` 取 `collecting`、`complete`、`incomplete`。只有分组所列全部战争均存在且为最终
`war_ended` 时，才可替换对应队伍的 `league_results` 投影。该投影除星数和实际进攻外，还保存
`appearances`（进入阵容场次）、`missed_attacks`（漏刀次数）与 `offense_1stars`（一星刀数）；
旧月份未重建时这些字段为 `NULL`，不能按零漏刀或零一星刀处理。`league_results` 可删除并重建，
但在当前规模下保留以服务编排和快速查询。
详细规则见 [`12-league-stats.md`](12-league-stats.md)。

## 不可破坏的约束

- `accounts.player_tag` 是真实 COC Tag；`NULL` 不能覆盖已有资料。
- `registrations.period` / `league_teams.period` 是即将参赛月；`league_results.period` 是实际发生月；
  普通战使用单场 `end_time`，不得混用。
- `team_index` 是月内从 0 开始的稳定队伍身份；`team_alias` 不是唯一键。
- 不在 API 请求路径访问 COC、ClashKing 或腾讯文档；先由任务或显式回填落本地。
- SQLite schema 或批量写入前必须创建并验证一致性备份；生产备份使用 `scripts/backup_to_cos.py`。

## 重建与恢复

| 数据 | 重建方式 |
|---|---|
| `member_war_facts` | 从 `war_history_cache` 的最终完整 JSON 物化 |
| `league_results` | 从完整 `cwl_live_group_cache` + `cwl_live_war_cache` 运行 `scripts/fetch_cwl_data.py --period YYYY-MM` |
| `farm_stats` / 部落资料缓存 | 对应调度任务重新抓取 |
| `cwl_assembly_cache` 未冻结记录 | 由月初检查窗口重新核对；冻结结果不可用重算值替换 |

恢复 COS SQLite 快照后须运行 `PRAGMA integrity_check`、重启 `sky-admin.service` 与
`sky-scheduler.service`，再验证 `/api/ping` 与目标业务接口。
