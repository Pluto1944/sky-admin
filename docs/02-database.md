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
| 互刷填坑号 | `farm_fill_accounts` | `account_number` | 一次性导入的长期保护身份；`player_tag` 可重复且无 accounts 外键 |
| 互刷独立账号 | `farm_auth_accounts` | `id` / `username` | 互刷系统独立登录、角色、状态和令牌版本 |
| 互刷部落归属 | `farm_clans` | `id` / `clan_tag_key` | 部落联盟账号与互刷部落的归属；积分初始为 0 |
| 互刷管理审计 | `farm_audit_logs` | `id` | 账号创建、密码和状态变更等受控操作审计 |
| 互刷场次 | `farm_rounds` | `id` | 全联盟统一时间、场次状态和时间锁定 |
| 互刷场次部落 | `farm_round_clans` | `(round_id, clan_id)` | 创建场次时的部落、归属和积分快照及登记状态 |
| 互刷匹配 | `farm_matches` | `id` / `(round_id, pair_key)` | 内部匹配或外部匹配失败及一次性平分随机结果 |
| 互刷积分流水 | `farm_score_ledger` | `id` | 胜负积分前后余额和后续反向冲销事实 |
| 互刷登记尝试 | `farm_registration_attempts` | `id` | 每次手工登记的状态、时间校验和排障摘要 |
| 互刷登录观测 | `farm_auth_events` | `id` | 不含用户名和凭证的登录结果计数 |
| 账号外部身份 | `wechat_users` | `openid` | 微信登录和账号绑定 |
| 联盟套餐 | `alliance_plans` | `plan_code` | `free / paid / internal` 的部落配额、同步等级和权益快照 |
| 联盟主体 | `alliances` | `id` / `alliance_key` | 联盟稳定身份、名称、状态、套餐与创建者；名称不是业务键 |
| 联盟成员 | `alliance_members` | `(alliance_id, user_id)` | 用户在某个联盟内的角色和成员状态，不从全局角色推断 |
| 联盟部落 | `alliance_clans` | `(alliance_id, clan_tag)` | 联盟订阅部落、业务标签、显示顺序和认证摘要 |
| 联盟访问 | `alliance_visits` | `(alliance_id, user_id)` | 最近访问及默认联盟；访问记录本身不授予成员权限 |
| 联盟审计 | `alliance_audit_events` | `id` / `event_key` | 联盟迁移及后续管理动作的幂等审计记录 |
| 联盟分享 | `alliance_share_links` | `id` / `token_hash` | 只保存普通浏览或加入邀请令牌摘要、来源联盟、创建者、状态、次数和过期时间 |
| 联盟加入申请 | `alliance_join_requests` | `id` | 非成员申请加入、审核人、审核状态与时间；同一用户同一联盟最多一个待处理申请 |
| 联盟权益 | `alliance_plan_grants` | `id` | 人工套餐开通、开始/到期、状态、操作人和备注 |
| 平台管理员 | `platform_admins` | `user_id` | 平台后台授权；不改变用户在各联盟中的角色 |
| 平台设置 | `platform_settings` | `setting_key` | 免费注册开关、总配额等平台级安全设置 |
| 平台审计 | `platform_audit_events` | `id` / `event_key` | 人工认证、套餐、联盟状态和平台设置操作 |
| 联盟 CWL 月份 | `alliance_cwl_seasons` | `(alliance_id, period)` | 联盟月度联赛配置与生命周期 |
| 联盟 CWL 队伍 | `alliance_cwl_teams` | `(season_id, team_index)` / `(season_id, clan_tag)` | 当月队伍、类别、顺序和来源 |
| 都城贡献 | `capital_raid_member_results` | `(clan_tag, start_time, player_tag)` | 突袭周末成员事实 |
| 都城状态 | `capital_raid_status_cache` | `clan_tag` | 最近一次突袭周末的开启、进行、结束或未开启状态 |
| 竞赛贡献 | `clan_games_member_snapshots` | `(period, player_tag)` | 月末成就快照和差值 |
| 部落资料 | `clan_profile_cache` | `clan_tag` | 自有部落官方资料缓存 |
| 调度状态 | `sync_jobs` | `job_id` | 周期任务的状态、时间和失败信息 |
| 调度运行历史 | `sync_job_runs` | `id` | 每轮任务状态、耗时、原因及外部请求计数；默认保留 30 天 |
| 外部请求明细 | `external_request_events` | `id` | 按任务记录外部来源、操作、结果、HTTP 状态和耗时；不保存凭证或响应正文 |
| 服务运行身份 | `service_runtime` | `component` | 常驻组件启动时冻结的版本、Git 提交、工作区状态与心跳 |
| 同步需求 | `sync_interests` | `(source_type, source_key, resource_type, resource_key)` | 联盟订阅或月度队伍对公共资源提出的同步需求；由 M4 Planner 维护 |
| 同步目标 | `sync_targets` | `(resource_type, resource_key)` | 合并相同公共资源的优先级、最短周期和需求计数 |
| 同步任务 | `sync_tasks` | `id` / `idempotency_key` | 影子或真实任务、优先级、到期时间、租约、有限重试和终态 |
| 同步尝试 | `sync_attempts` | `(task_id, attempt_no)` | Worker 每次领取后的结果、错误分类和外部请求摘要 |

`capital_raid_status_cache` 与都城成员贡献事实分离：它每个自有部落只保留一行最近周末状态，服务概览卡片的开启提醒，不保存成员明细。同步失败只更新错误与尝试时间，已有同周状态不会被空结果覆盖。

## 联盟租户底座（M1–M9）

M1 数据模型、M2 后端访问控制和 M3 小程序联盟切换均已实现。`config/settings.yaml` 继续作为苍穹
遗留任务与编排流程的兼容来源；登录后的联盟页面以 `alliance_members`、`alliance_clans` 和联盟月度
CWL 配置作为范围与权限依据。公共 COC 事实仍按全局 Tag 保存，不按联盟重复复制。

- `alliances.alliance_key` 是不可变的程序身份；苍穹固定使用 `sky-internal`，展示名称可修改；
- `alliance_members.role` 只允许 `member / admin / leader`，同一联盟最多一个有效首领；
- `wechat_users.role` 暂留给旧 API 兼容，不是新联盟权限依据；M1 按已确认的兼容策略，将迁移时已经存在的苍穹微信用户默认映射为联盟管理员，但不修改该遗留字段；
- 固定配置迁入的 12 个苍穹自有部落作为内部可信存量标记为已认证，确保 M2 接入权限后现有用户可见范围不突然收窄；该规则不适用于以后新增的免费或付费联盟部落；
- 所有用户通过普通入口最多创建一个有效免费联盟；超级管理员只有通过“超级管理”平台接口才可为运营和测试创建多个，因此不使用数据库唯一索引表达个人创建规则。免费、付费套餐的有效部落上限分别为 1、10，内部套餐为苍穹迁移保留更高上限；`alliances.clan_limit_override` 仅供平台超级管理自动扩容单个联盟，普通首领和管理员仍由服务层按套餐上限校验；
- 部落数量约束由 SQLite trigger 执行，新增部落、重新启用部落、切换套餐或降低套餐配额都不能绕过；
- `alliance_visits` 记录已登录用户最多 50 条浏览历史、最近访问和默认选择；它可以授权普通只读访问，但不能替代 `alliance_members`，也不能授权写操作或管理数据；
- `alliance_audit_events.event_key` 用于让同一份迁移清单重复应用时不产生重复审计。
- 部落认证以 `(alliance_id, clan_tag)` 为单位；同一部落可被多个联盟订阅。普通用户后续发起自助认证时，
  若该 Tag 已被其他联盟认证，服务层必须拒绝并提示联系超级管理员；超级管理员可在平台人工认证接口中
  允许同一 Tag 同时被多个联盟认证，不自动撤销或改写原关系。平台后台将这些关系列为“多联盟认证”，
  可进入各联盟逐个撤销；数据库不再用全局唯一 trigger 限制 `verified` 关系；
- `alliance_share_links.share_type` 区分 `browse / invite`，只存 SHA-256 摘要，原始令牌仅创建时返回；
  普通分享只建立浏览历史，邀请经接收者确认后固定加入为 `member`。被移除用户需重新申请，`blocked`
  用户不能依赖链接或申请恢复权限；
- `alliance_plan_grants` 与 `alliances.plan_code` 分工：前者记录人工权益生命周期，后者选择套餐模板。
  付费到期后权益状态变为 `expired`，额外部落转为 `inactive`，但联盟关系、审计和公共事实不删除；
- `platform_admins`、环境白名单和平台设置都不赋予联盟角色。平台 API 仍单独检查平台管理员身份，
  联盟业务 API 继续检查 `alliance_members` 和逐部落认证。

M5 不新增一套“免费部落事实表”。免费联盟继续写上述核心表：创建者写为唯一有效 `leader`，
订阅部落写入 `alliance_clans` 且保持 `unverified`，创建、改名、订阅/改标签、手动刷新和软删除均写
`alliance_audit_events`。删除采用 `alliances.status=archived`，同时停用订阅和成员关系，不物理删除
联盟审计，也不删除 `clan_profile_cache`、`current_war_cache`、战争档案或其他公共事实。

迁移命令为 `scripts/migrate_alliance_m1.py`。默认只读预览；写入必须显式使用 `--apply --yes`，
并在写入前创建 SQLite 一致性备份。迁移工具默认把执行迁移时已有的全部 `wechat_users` 映射为
苍穹管理员；可用已复核的 `--members-file` 将指定用户覆盖为 `member / admin / leader`。该默认规则
只执行于苍穹存量迁移，M1 以后新加入联盟的用户仍默认是普通成员。建议将预览输出的配置哈希通过
`--expected-config-hash` 带入应用命令，防止评审后配置发生漂移。

`service_runtime` 不属于业务任务队列，也不复用 `sync_jobs`。常驻调度器与 M4 Worker 分别以
`component=scheduler / sync_worker` 上报启动身份并更新心跳；API 的运行身份直接保存在各 Uvicorn worker
内存中，由 `/api/system/version` 与调度器记录聚合。发布版本或 Git 提交变化只有在组件重启后
才会更新，这正是用于识别“磁盘代码已更新、进程仍运行旧代码”的依据。

`sync_jobs` 只保存每个任务的最新状态和累计次数；`sync_job_runs` 保存逐轮历史，
`external_request_events` 通过 `run_id` 关联到具体任务轮次。删除过期的运行历史时，请求明细通过
外键级联删除。默认保留 30 天，可通过 `OBSERVABILITY_RETENTION_DAYS` 调整。观测表是可丢弃的
运行数据，不是业务事实；观测写入或清理失败不得改变同步任务结果。调度器进程启动时会把上一进程
遗留的 `running` 记录收口为 `interrupted`，保留发现中断的时间和原因，不伪造完整耗时或请求计数。

## M4 同步队列底座

M4.0 在 SQLite 中新增 `sync_interests → sync_targets → sync_tasks → sync_attempts` 四层运行模型。
它们不是 COC 业务事实，也不能替代现有缓存：需求按联盟来源保存，目标按公共资源键全局去重，任务
按时间桶使用 `idempotency_key` 去重，尝试记录 Worker 租约内的一次执行。删除或停用一个联盟只会
停用对应需求；仍被其他联盟使用的公共目标继续存在。

`sync_targets.planning_mode` 记录每个目标当前应生成 `shadow` 还是 `live` 任务。`mode=live`
任务由独立 Worker 原子领取，每次尝试使用租约、心跳、指数退避和最大尝试次数。目标从 live
切回 shadow 时，待执行和等待重试的 live 任务会被取消，已开始的任务由租约所有者收口。
影子记录默认保留 7 天；队列聚合状态由 `scripts/observability_report.py` 只读输出，不展示资源 Tag。

M5 手动刷新复用同一 `sync_targets` 和 `sync_tasks`：按 `resource_type + resource_key` 查询全局目标，
优先复用开放任务，并按部落资源共享冷却。交互任务使用 `interactive` 优先级，低于战斗期
`realtime`；相同部落被多个联盟订阅时仍只有一个目标。首次订阅若缓存满足新鲜度则不建任务，
否则只为部落资料、成员列表和当前战争分别提交异步任务。

## 互刷系统独立认证底座（F1）

`farm_auth_accounts` 与 `wechat_users` 完全分离。账号统一使用邮箱登录，邮箱规范化后唯一，角色只允许
`creator / admin / member`，状态只允许 `active / disabled`；部分唯一索引保证同一时刻最多一个
有效创建者。密码只保存带随机盐的 `scrypt-v1` 哈希。修改或重置密码、启停账号都会递增
`token_version`，使全部旧互刷令牌失效。

`farm_clans` 从 F1 起预留账号与部落归属，使用 `clan_tag_key` 比较规范化标签并兼容 COC 标签中的
`O / 0` 易混写法；F1 不开放部落管理接口，也不迁移现有 `farm_stats`。`farm_audit_logs` 不保存密码、
哈希或令牌。三张表由 `shared/db/connection.py` 幂等创建，功能开关关闭时不会改变现有微信登录和页面。

F3 新增 `farm_rounds` 与 `farm_round_clans`。部分唯一索引保证最多一个
`scheduled / open / partially_registered` 场次；创建场次时只复制启用账号下的启用部落，并保存当时
归属、标签、名称和积分。后续转移部落不会改变历史快照。统一时间以 UTC 保存，API 同时返回
`Asia/Shanghai` 展示值。业务统一时间固定为“开始搜战时间”，`business_time_kind` 只允许
`preparation_start`，登记时校验 COC 官方 `preparationStartTime`。

F4 的 `farm_matches`、`farm_score_ledger` 和 `farm_registration_attempts` 分离最终事实、积分事实与
可重试观测。一个场次的同一规范化部落对最多一条有效匹配，同一匹配同一部落最多一条基础胜负流水。
内部双方结果、两笔流水、物化积分和场次状态在同一事务提交；失败全部回滚。登记尝试只保存必要的
官方状态、时间和对手摘要，不保存成员宽表、API Token 或授权头。
`farm_auth_events` 只记录账号 ID（可空）、结果和时间，用于统计成功、无效凭证、停用、限流和未进入
灰度范围；它不保存提交的用户名、密码、令牌或客户端授权头。

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
旧月份未重建时这些字段为 `NULL`，不能按零漏刀或零一星刀处理。投影唯一键为
`(period, clan_tag, player_tag)`；`team_index` 继续作为苍穹编排兼容字段，但不再充当公共事实身份。
`league_results` 可删除并重建，
但在当前规模下保留以服务编排和快速查询。
详细规则见 [`12-league-stats.md`](12-league-stats.md)。

### 多联盟月度配置（已实现并完成生产迁移）

多联盟 CWL 不复用 `alliance_clans` 表示当月参赛范围，也不把苍穹专用 `league_teams` 直接扩展为
租户表。当前实现新增：

| 表 | 键 / 身份 | 责任 |
|---|---|---|
| `alliance_cwl_seasons` | `(alliance_id, period)` | 联盟当月 CWL 配置及 `draft / active / frozen / complete` 生命周期 |
| `alliance_cwl_teams` | `(season_id, team_index)`、`(season_id, clan_tag)` | 当月队伍 Tag、名称快照、别名、`combat / shell`、顺序与来源 |

两表是联盟私有配置；官方分组、战争和成绩仍使用现有公共事实表。月度队伍可以是临时壳子，
不要求存在于 `alliance_clans`，也不要求完成部落认证。套餐通过 `max_cwl_teams` 限制每月队伍数：
免费 1、付费 20；该字段与日常订阅部落配额分开。

苍穹现有 `league_teams` 保留为编排快照和旧接口兼容来源，并幂等导入新表；以后编排成功时同步
更新苍穹对应月度配置。`scripts/migrate_alliance_cwl.py` 默认只读预览；`--apply --yes` 会先创建
一致性备份，再建表、迁移全部苍穹结构化历史并执行完整性与外键检查。

## 不可破坏的约束

- `accounts.player_tag` 是真实 COC Tag；`NULL` 不能覆盖已有资料。
- `registrations.period` / `league_teams.period` 是即将参赛月；`league_results.period` 是实际发生月；
  `alliance_cwl_seasons.period` 与 `alliance_cwl_teams` 表示联盟配置的实际 CWL 月份；
  普通战使用单场 `end_time`，不得混用。
- `team_index` 是月内从 0 开始的稳定队伍身份；`team_alias` 不是唯一键。
- `farm_fill_accounts` 以填坑账号编号保留全部登记；当前部落归属始终通过 `player_tag` 关联
  `accounts.clan_tag`，不能用导入快照覆盖 COC 权威归属。
- 联盟名称不是业务键；角色必须按 `(alliance_id, user_id)` 查询。访问过联盟不等于加入联盟，
  未认证部落中的管理角色也不能仅凭角色字段取得管理数据。
- 不在 API 请求路径访问 COC、ClashKing 或腾讯文档；先由任务或显式回填落本地。
- SQLite schema 或批量写入前必须创建并验证一致性备份；生产备份使用 `scripts/backup_to_cos.py`。

## 重建与恢复

| 数据 | 重建方式 |
|---|---|
| `member_war_facts` | 从 `war_history_cache` 的最终完整 JSON 物化 |
| `league_results` | 从完整 `cwl_live_group_cache` + `cwl_live_war_cache` 运行 `scripts/fetch_cwl_data.py --period YYYY-MM` |
| `farm_stats` / 部落资料缓存 | 对应调度任务重新抓取 |
| `farm_fill_accounts` | 不可由 COC 重建；从一致性备份恢复，或由已确认来源显式重新导入 |
| `farm_auth_accounts` / `farm_clans` / `farm_rounds` / `farm_round_clans` / `farm_matches` / `farm_score_ledger` / `farm_audit_logs` | 私有管理事实，不可由 COC 重建；从一致性备份恢复 |
| `farm_registration_attempts` | 可丢弃观测记录；不作为匹配或积分事实 |
| `farm_auth_events` | 可丢弃认证观测记录；不作为账号或授权事实 |
| `cwl_assembly_cache` 未冻结记录 | 由月初检查窗口重新核对；冻结结果不可用重算值替换 |

恢复 COS SQLite 快照后须运行 `PRAGMA integrity_check`、重启 `sky-admin.service` 与
`sky-scheduler.service`，再验证 `/api/ping` 与目标业务接口。
