# CHANGELOG

> 版本更新记录

---

## v1.4 — 周期调度器 + 双服务对等化（2026-08-17）

- **新增周期调度器**：`scripts/scheduler.py` 统一管理 4 类周期刷新任务（`farm_stats`/`coc_sync`/`war_results`/`cwl`），状态落 `sync_jobs` 表，详见 `docs/15-scheduler.md`
- **新增 systemd 单元**：`deploy/sky-scheduler.service`，与 `sky-admin` 平级，`deploy/deploy.sh` 一键部署两个服务
- **服务运维文档对等化**：`deploy/README.md` 中 sky-admin 与 sky-scheduler 的服务管理/日志/测试/故障排查完全对等
- **备案过渡期方案归档**：`deploy/README.md` 补充「备案前 IP 直连」临时方案说明与切换指引
- **废弃旧方案**：`docs/periodic-scripts.md` 标注 systemd timer + cron 旧方案已废弃，保留存档

---

## v1.3 — 互刷页面表格优化（2026-08-12）

- **新增 TH11 列**：互刷部落表格新增"11"列单独列示，`other` 仅统计 10 本及以下
- **布局修复**：解决微信小程序中表格右边界被裁剪的问题
  - 移除 `scroll-view` 的 padding，改用内层 `.scroll-inner` 容器包裹内容
  - 新增 `.table-body` 容器统一表格背景色，避免 flex 行背景未撑满
  - `.clan-card` 增加 `box-sizing: border-box` 和 `width: 100%`
  - 单元格 `padding` 从 `8rpx` 收紧到 `4rpx`，`width` 从 `56rpx` 收紧到 `52rpx`

---

## v3.0 — 基准重建（2026-08）

- **排序重构**：从"完全重排 + 升降级微调"改为"以上月实战名单为锚点做基准重建"
  - 新增 `baseline_rebuilder.py`：阶段 0~6（黑名单过滤 → 构建 7 个临时名单 → 基准重建+升降级 → 删除缺失 → 插入战营新增 → 插入普通营新增 → 追加壳子）
  - 新增 `team_builder.py`：阶段 7~9（贪心填充 → 白名单 → 管理员）
  - `team_filler.py` 已删除，由 `team_builder.py` 完全替代
- **排序键调整**：战营按奖杯降序（原综合分），普通营按综合分降序
- **新增配置**：`BLACK_LIST`、`WHITE_LIST`、`NEW_COMBAT_INSERT_START`、`NEW_NORMAL_INSERT_START`
- **新表**：`league_teams`（队伍配置快照）、`league_results`（联赛战绩结构化存储）
- **双写过渡**：`league_results` 写入时同时双写到旧 `results` 表
- **cur_team 格式**：从 `"{team_index} {team_alias}"` 升级为 `"{team_index} {team_alias} {coc_name}"`
- **TEAMS_LAST 已删除**：由 `league_teams` 表替代，每月 `arrange()` 幂等写入配置快照
- **升降级内嵌**：`promotion.py` 从独立调用改为被 `baseline_rebuilder` 阶段 2b 调用（在 prev_slots 上执行配对交换）
- **registrations.team_name 回写格式**：`"{team_index} {team_alias} {coc_name} {clan_tag}"`
- **fetch_cwl_data.py**：不依赖 `config/settings.yaml` TEAMS，从 `league_teams` 表获取队伍信息

---

## v2.8 — 管理意愿 + 部落信息

- **管理意愿**：报名表新增 `willing_to_manage` 字段，解析落库 `registrations.willing_to_manage`
- **管理员三级分配**：`_assign_managers()` 改造为 config 优先 → 报名意愿兜底 → 留空
- **Part4 部落信息**：抬头行 5 列全部填充——col1 队伍信息、col2 clan_tag、col3 部落名（COC API）、col4 首领、col5 管理

---

## v2.7 — 列结构优化

- `ARRANGEMENT_OUTPUT_HEADERS` 为 13 列（含 `team_name`）
- Part4 改为独立 5 列写入（`_append_part4_to_sheet`），不经过 header dict 映射，避免中间空列
- `insert_normal_new` 从二分插入改为追加到实战区末尾（壳子区之前）
- `NEW_NORMAL_INSERT_START` 已废弃
- Part4 抬头行管理信息放第 5 列

---

## v2.6 — 发布简化

- 新增 `publish-results` 命令 + `publish_to_results.sh`，将 Part4 网格发布到公示文档
- 前 20 行固定文字硬编码为 `PUBLISH_FIXED_ROWS` 类常量
- Part4 数据复用 `arrange()` 结果保证与编排名单完全一致
- 删除 ~170 行复杂的模板匹配逻辑（`_get_template_fixed_rows`、`_assemble_publish_content`、`_rebuild_team_results`）

---

## v2.5 — period 语义统一

- 所有 CLI 接口的 `--period` 统一为**联赛月份**（实际打 CWL 的月份）
- `registrations.period` 从报名时间改为联赛时间，与 `arrange --period` 对齐
- `fetch_cwl_data.py` 保持传入 CWL 实际发生月（编排 N 月联赛时传 N-1 月）
- `arrange()` 不再需要为读 registrations 做 `_prev_period()` 转换，仅在读上月 CWL 星数时使用

---

## v2.4 — 升降级

- 新增**实战队伍升降级系统**（`promotion.py`，纯函数，12 个单测）
  - 在 `fill_teams()` 后根据 CWL 星数在相邻实战队伍间交换人员
  - ≤18 星逐级下沉，21 满星逐级上升
- `fetch_cwl_data.py` 合并 COC API 拉取 + results 表导入 + 冷启动回退
- `war_result/repository.py` 新增 `get_results_by_period()`
- `player/service.py` 新增 `resolve_name_by_tag()`
- 详见 `04-promotion-relegation.md`

---

## v2.3 — 队伍分配

- 新增**自动队伍填充**（`team_filler.py`，纯函数，36 个单测）
  - 按 `TEAMS` 配置将排序后人员逐队分配到具体部落队伍
  - 支持实战最低匹配值门槛（低于阈值的 combat → shell）
  - 支持预留位置（`reserved_slots`：>0 留空位 / <0 多招备选）
  - 最后一个实战队边界处理（③a 刚好 / ③b 溢出入壳子 / ③c 缺口<5 从壳子协调 / ③d 缺口≥5 不协调）
- `registrations` 新增 `team_name` 列
- `ARRANGEMENT_OUTPUT_HEADERS` 新增 `cur_team`/`prev_team` 列

---

## v2.2 — 报名解耦（B 方案）

- `registrations` 从"accounts 的子表"升级为**自包含的报名事实源**
  - 自持 `account_name`（报名昵称，主标识）/ `player_name`
  - `player_tag` 降为**可空的关联缓存、去外键**
  - 唯一键 `(player_tag, period)` → `(account_name, period)`
- 报名导入**不再写 accounts、不再临时建档、不再合并**
  - `accounts` 全由 COC 权威建档 + 战绩历史分填充
  - 报名侧只读反查真实 Tag 做缓存
  - "报名有 / COC 无"的新人照常入 `registrations`、排序得 0 分
- **退休部件**：`is_provisional` 临时建档、`merge_provisional` 合并、`unmatched.py` 未匹配钩子、coc-sync 残留告警
- 新增**战营排除名单 `EXCLUDED_CAMP_NAMES`**：导入阶段 + 排序阶段双阶段过滤

---

## v2.1 — 表结构瘦身

- accounts 从 21→16 列，只留账号级事实
- 按月维度字段（`account_type` / `camp_order` / `latest_match_value` / `join_combat`）下沉 registrations
- `last_reg_period` 改为读取时派生（`MAX(period)` 子查询）
- 旧库经回填 + 重建表迁移

---

## v2.0 — 领域模块架构

- 从"技术分层"（`core` / `io_adapter` / `db`）重构为"业务领域分模块"
  - `player` 中枢（`PlayerService` 为账号读写唯一入口）
  - `cwl_registration` 报名
  - `war_result` 战绩
  - `coc_sync` COC 同步
  - `shared` 基础设施
- 账号身份采用**走 A：COC 真实 Tag 作主键**
- `coc_sync` 为权威建档源
- 测试改用真实内存 `Database(":memory:")` + `FakeExcelIO` / `FakeCocApiClient`

---

## v1.x — 初始版本

- 技术分层架构（`core` / `io_adapter` / `db`）
- 本地 xlsx 读写
- 基础报名导入、排序编排、战绩导入
- 腾讯文档 API 预留接口
