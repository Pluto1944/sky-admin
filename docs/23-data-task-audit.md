# 23 — 数据表与周期任务审计

> 审计日期：2026-10-02。以生产 `data/league.db`、`shared/db/connection.py` 和
> `scripts/scheduler.py` 为准；行数和体积是该日期快照，不是固定容量指标。

---

## 一、结论

主库当前有 **19 张业务与运行状态表**，调度器有 **12 个任务**。没有发现可在不改变
业务语义的前提下直接删除的整张表。

表之间存在的重复分为两类：

1. **有意的物化缓存**：为避免 API 请求路径扫描完整战争 JSON 或重复访问外部 API；
2. **有意的事实与摘要并存**：事实表保证历史可追溯，摘要表保证成员页和看板响应速度。

唯一确认的物理 schema 遗留是 `registrations.prev_rank` 和 `registrations.team_name`：
它们不在当前目标 DDL、当前业务代码也不读写。清理需要独立的 SQLite 重建迁移，不能在
普通文档或功能变更中顺手删除。

---

## 二、表的生命周期与权威边界

| 分类 | 表 | 权威来源 / 写入方 | 保留理由 | 可否直接重建 |
|---|---|---|---|---|
| 账号事实 | `accounts` | `coc_sync`、玩家详情/竞赛任务、报名状态刷新 | COC 身份、当前归属和活动观察状态 | 否 |
| 月度业务事实 | `registrations`、`league_teams` | 报名导入、编排 | 报名与队伍的历史月度快照 | 否 |
| 战绩事实 | `league_results`、`war_results`、`member_war_facts` | CWL/普通战抓取与归档 | 升降级、5/15/45 战绩和跨部落成员窗口 | 否 |
| 成员贡献事实 | `capital_raid_member_results`、`clan_games_member_snapshots` | 周期任务 | 周/月份成员贡献的可追溯记录 | 否 |
| 用户事实 | `wechat_users` | 微信登录/绑定流程 | 用户身份与绑定关系 | 否 |
| 实时/详情缓存 | `current_war_cache`、`war_history_cache`、`cwl_live_group_cache`、`cwl_live_war_cache`、`clan_profile_cache`、`farm_stats` | 调度器 | 页面只读缓存、故障时保留最近成功值 | 有条件；会损失缓存和历史详情 |
| 物化摘要 | `member_combat_stats_cache` | 本地事实表重算 | `/api/members` 不做 N+1 或扫描完整 JSON | 是；用 `member_combat_stats` 重建 |
| 流程快照/检查 | `cwl_roster_snapshots`、`cwl_assembly_cache` | 公示表快照、集结检查 | 公示版本不可变、冻结状态可审计 | 前者否；后者需保留冻结语义 |
| 运行状态 | `sync_jobs` | 调度器 | 启停、失败次数、下次执行时间 | 有条件；会丢失运维状态 |

### 2.1 有意的字段重复

- `league_results` 的队伍字段（`team_index`、`team_alias`、`team_name`、`clan_tag`）同时也
  出现在 `league_teams`：这是月度战绩的归属快照，避免队伍改名或配置变化篡改历史结果。
- `league_results` / `war_results` 的结构化指标与 `raw_metrics` 同时保存：前者服务查询，后者
  保存上游抓取的可追溯载荷和未来兼容字段；不应为了节省少量空间删除 `raw_metrics`。
- `war_history_cache` 保存完整战争 JSON，`member_war_facts` 保存逐玩家可重建事实：前者只保留
  每部落最近 15 场，后者保证跨部落 90 天成员窗口不会随 JSON 清理而丢失。
- `member_combat_stats_cache` 是 `member_war_facts` 与 `league_results` 的物化摘要。它是唯一可
  完整重建的表；保留它是为了避免成员页每次请求遍历 7,000 余条事实和完整战争 JSON。

### 2.2 已确认的遗留字段

生产 `registrations` 仍带有早期迁移遗留的物理列：

| 列 | 审计时非空行 | 当前替代 | 结论 |
|---|---:|---|---|
| `prev_rank` | 0 | 上月名次读取 `rank_order` | 可删除候选 |
| `team_name` | 248 | 编排回写 `team_info`；展示队名来自 `league_teams` / 输出字段 | 可删除候选 |
| `team_info` | 953 | 当前编排读写 | 必须保留 |

执行清理前必须：停止写入窗口、用 SQLite Online Backup API 生成一致性备份、在临时库验证
`registrations` 重建迁移、检查 `PRAGMA foreign_key_check` 和月度编排回归测试。该清理不属于
本次文档更新，也不应与报名月临近时的编排操作混合执行。

`accounts.history_score` 不是空闲 schema 列：当前值全部为 0，且没有自动写入方，但排序配置和
玩家导出仍读取它。是否删除应连同排序权重和导出字段进行一次单独的业务决策，不能只删列。

---

## 三、任务边界与重叠

| 类型 | 任务 | 频率 / 窗口 | 主要输出 |
|---|---|---|---|
| 实时战争 | `current_wars` | 2 分钟检查，按部落状态限频 | 当前战争、普通战归档、成员战争事实 |
| CWL 实时 | `cwl_live` | 2 分钟；每月 1–12 日 | 联赛组与逐场战争缓存 |
| 集结检查 | `cwl_assembly` | 5 分钟；每月 1 日 14:00–3 日 16:00 | 公示名单 revision、集结差异 |
| 部落资料 | `coc_sync` | 6 小时 | 账号档案、部落资料缓存 |
| 玩家详情 | `player_details` | 每天 | `attackWins` 与活动观察字段 |
| 成员摘要 | `member_combat_stats` | 每天 | 90 天/近 3 完整月窗口重算 |
| 互刷 | `farm_stats` | 30 分钟 | 大本分布与去速本配置 |
| 都城贡献 | `capital_member_stats` | 每 6 小时检查；周二至周三 | 已结束突袭周末成员事实 |
| 竞赛贡献 | `clan_games_stats` | 每 6 小时检查；每月 29–30 日 | 月末成就快照和差值 |
| 普通战历史 | `war_results` | 每天 | 战营长期 5/15/45 战绩 |
| CWL 历史 | `cwl` | 每天触发；仅每月 12 日写入 | 结构化 CWL 战绩 |
| 公众号阵型 | `war_layout` | 北京时间每日固定时刻 | 独立运行库与公众号草稿 |

### 3.1 不是冗余的重叠

- `current_wars` 在战争变动后重算成员摘要，`member_combat_stats` 每日再全量重算一次：前者保证
  页面及时，后者负责 90 天和 3 个完整月窗口自然过期，两者职责不同。
- `player_details` 与 `clan_games_stats` 都会访问玩家详情：前者每日维护活动信号，后者只在月末
  窗口读取竞赛累计成就。月末存在少量重复请求，但删除任一任务会失去独立的失败重试与业务窗口。
- `war_results` 与 `member_war_facts` 都有普通战指标：前者是战营长期战绩页口径，后者是跨全部
  自有部落的成员事实口径，时间窗口、部落范围和消费者不同。
- `cwl_live_*` 与 `league_results` 都涉及 CWL：前者保存联赛组/轮次/逐场详情，后者是个人聚合，
  不能互相替代。

### 3.2 已实施优化与待观察项

1. `current_wars` 已改为：普通战进入 `war_ended` 且 `member_war_facts` 新增或变化时，才按受影响的
   `player_tag` 重算成员摘要；进行中战争、相同结束快照和同步失败均不触发摘要写入。每日
   `member_combat_stats` 保留全量窗口过期处理。
2. 月末 `player_details` 与 `clan_games_stats` 可共享同轮玩家详情响应以降低请求数，但需要把两个
   独立失败边界改成共享批处理；在没有 API 限流或耗时证据前不建议改变。
3. `member_war_facts`、CWL 实时缓存和贡献事实目前按业务历史保存，没有统一 TTL。当前体积很小，
   先保持可追溯性；达到容量或查询压力阈值后，再单独制定归档/压缩策略，不能按缓存名直接清空。

---

## 四、2026-10-02 生产快照

| 指标 | 值 |
|---|---:|
| 业务表数 | 19 |
| 启用调度任务 | 12 / 12 |
| 账号档案 | 771 |
| 报名记录 | 972 |
| CWL 战绩 | 937 |
| 普通战聚合 | 5,657 |
| 普通战玩家事实 | 7,135 |
| 成员战斗摘要 | 771 |
| 主库中最大表 | `accounts`，约 9.8 MiB（主要为 `coc_raw`） |
| 第二大表 | `war_history_cache`，约 7.7 MiB（完整战争 JSON） |

审计时 12 个任务都处于启用状态，最后状态均为 `success` 或按日期窗口正常 `skipped`。
`sync_jobs.fail_count` 是累计历史失败次数，不能单独视为当前故障。

---

## 五、变更准则

1. 优先删除无消费者的**遗留列**，不要因名称相近而删除事实表或缓存表；
2. 先更新消费者和重建路径，再做 schema 迁移；
3. 涉及生产表重建、历史清理或 TTL 时，必须先做 COS 一致性备份，并验证恢复路径；
4. 任意缓存删除前，必须确认 API 在缺缓存时的降级行为和重建任务；
5. 单独记录事实表的保留策略，避免把“缓存”误解为可以无条件清空的数据。
