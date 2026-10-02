# sky-admin 项目协作指南

本文件是 `sky-admin` 的工程约束和开发导航。修改任何功能前，先阅读对应实现、相关测试和本文件列出的匹配文档；当文档、代码和 Git 历史不一致时，以**当前可运行代码与最近提交**为准，并在同一变更中修正文档或明确标注其为历史内容。

## 1. 项目范围与运行形态

`sky-admin` 是 COC 联盟运营系统，涵盖：

- COC 联盟成员权威同步、成员流动与账号档案；
- CWL 报名导入、稳定编排、升降级、名单与公示表输出；
- CWL / 普通部落战战绩统计、互刷部落去速本统计、当前部落战看板；
- 腾讯文档读写、FastAPI 服务、微信小程序登录与账号绑定；
- X/SocialData 阵型采集与微信公众号草稿发布。

技术栈：Python 3.10+、FastAPI、SQLite、pandas/openpyxl；前端为 Vue 2 + uni-app + webpack 4，目标为微信小程序。

生产请求链路：`微信小程序 -> https://api.skycoc.cc -> Nginx -> FastAPI(127.0.0.1:8000) -> SQLite`。

生产常驻服务由 systemd 管理：

- `sky-admin.service`：`uvicorn api_server.app:app --host 127.0.0.1 --port 8000 --workers 2`；
- `sky-scheduler.service`：`scripts/scheduler.py` 常驻调度器。

## 2. 变更安全与仓库卫生

- 动手前运行 `git status --short --branch`；保留用户已有改动，绝不覆盖无关 diff。
- 变更保持最小且按业务边界组织；不要借机重构相邻模块。
- 不提交 `.env`、私钥、Token、文档 ID、数据库、日志、`__pycache__`、`.pytest_cache`、`uni-app/node_modules`、`uni-app/dist` 或 `modules/war_layout/runtime/` 中的运行数据。
- 不执行 `git reset --hard`、`git checkout --`、递归删除，或 `python cli.py reset-db`，除非用户明确指定精确目标。
- 涉及 SQLite schema / 大批量写入 / 月度编排前，确认数据目标；生产库 `data/league.db` 的迁移或高风险操作前先做一致性备份。
- 不将密钥、原始 HTTP 授权头、完整 `.env`、包含用户隐私的聊天/截图内容写进终端输出、日志、测试夹具或文档。

## 3. 文档使用与可信度

优先阅读与改动相符的文档，并同步更新它：

| 主题 | 首选文档 |
| --- | --- |
| 总体架构、模块归属、已知缺口 | `docs/01-architecture.md` |
| 数据库、字段所有权、period | `docs/02-database.md` |
| 数据表生命周期、缓存重建与任务冗余审计 | `docs/23-data-task-audit.md` |
| CWL 排序、基准重建、队伍填充 | `docs/03-sorting.md`、`docs/04-promotion-relegation.md` |
| 名单 Part1–4 与腾讯文档公示 | `docs/05-roster-output.md` |
| 月度操作和异常处理 | `docs/06-operations.md`、`docs/17-cwl-arrangement-sop.md` |
| 配置集中化 | `docs/07-config-migration.md`（迁移设计已落地；以 `config/` 实现为准） |
| 外部战绩来源 | `docs/08-warreport-api.md`、`docs/09-fetch_cwl_data_design.md` |
| FastAPI、认证、部署接口 | `docs/10-api-server.md` |
| 小程序、隐私与构建 | `docs/11-uni-app.md` |
| CWL / 普通战 / 互刷统计 | `docs/12-league-stats.md`、`docs/13-war-stats.md`、`docs/14-farm-clans.md` |
| 周期调度 | `docs/15-scheduler.md` 与 `scripts/scheduler.py` |
| 当前部落战看板 | `docs/18-current-war-dashboard.md` |
| 部署、systemd、证书和恢复 | `deploy/README.md` |
| 阵型采集与公众号草稿 | `modules/war_layout/DESIGN.md`、`IMPLEMENTATION_PLAN.md` |

以下内容只作背景或历史记录，不能直接当作当前行为：

- `docs/periodic-scripts.md`：已废弃的 timer/cron 方案；
- `docs/11-uni-app.md` 中的“旧架构 / 待开发”段落；
- `WORK_STATE.md`、`docs/CHANGELOG.md`：时间点快照；
- `docs/16-codex-proxy.md`：Codex/代理运维说明，不是应用功能规范；
- 外部 API 的路径、限流和权限会变动，使用前以供应商官方文档和当前客户端代码复核。

## 4. 架构边界

### 4.1 领域模块

- `modules/player`：账号与成员领域的唯一公共入口。除该模块外，业务模块不得直接更新 `accounts`；使用 `PlayerService`。
- `modules/cwl_registration`：报名导入、排序、基准重建、升降级、队伍构建、名单输出与发布。使用 `baseline_rebuilder.py`（阶段 0–6）和 `team_builder.py`（阶段 7–9）；`team_filler.py` 是退役历史设计，不得新增依赖。
- 手工 `import-result` 与旧 `results` 表已经退役；CWL 历史战绩只使用结构化的 `league_results`。`accounts.history_score` 暂保留为兼容字段，当前没有自动写入方，未经明确业务公式不得顺带启用或修改排序语义。
- `modules/coc_sync`：COC 官方数据的权威同步、成员去重、联盟内转移与退部对账；`CocSyncService` 是首选编排入口。已有 roster / farm 的旧式直接客户端调用只作兼容，不要复制到新功能。
- `modules/coc_sync/current_war.py`：纯转换层；不得在其中加入网络或数据库 I/O。
- `modules/war_layout`：独立的阵型采集与公众号发布子系统，使用单独运行库；不要与主 `league.db` 混用。
- `shared/db`：唯一的主 SQLite 连接、DDL 与幂等迁移位置。业务模块不得自行散落 schema 或新开独立主库连接。
- `shared/io_adapter`：本地 xlsx 与腾讯文档的抽象边界；新增表格 I/O 复用 `ExcelIO`，不要把厂商调用塞进业务纯函数。
- `api_server`：FastAPI 应用、路由、依赖注入、JWT/微信认证。
- `uni-app`：小程序 UI；所有后端请求统一经 `uni-app/utils/api.js`。

### 4.2 纯函数与 I/O

排序、升降级、状态推断、COC mapper、战绩聚合、当前战争规范化、去速本计算等业务算法应保持纯函数：输入明确、输出确定、无网络/数据库/环境变量副作用。I/O、Repository、HTTP 客户端与编排器通过依赖注入连接，测试可使用内存库和 fake。

## 5. 数据模型与不可破坏的业务语义

- `accounts.player_tag` 必须是 COC 真实 Tag；COC 是账号创建和部落归属的权威来源。
- `registrations` 是自包含的月度报名事实：唯一键为 `(account_name, period)`；`player_tag` 只是可空关联缓存，不得加回 `accounts` 外键。
- 报名中找不到 COC 账号时仍可写 `registrations`，但不得创建临时账号；排序时该账号按既定缺省分处理。
- `accounts` upsert 维持 `COALESCE` 语义：某来源传来的 `NULL` 不能抹掉其它来源已拥有的字段。
- 结果导入需要 `accounts` 外键时，未知账号必须跳过并告警，不得伪造 Tag。
- `team_index` 是每期唯一、从 0 开始的队伍身份；`team_alias` 可重复；`team_name` 是 COC 名称；`clan_tag` 是 API 身份。队伍类别仅为 `combat` / `shell`。
- `membership_status`（是否仍在联盟）与 `status`（报名状态）是不同维度，任何同步或退部逻辑不得互相覆盖。

### Period 语义

所有命令边界校验 `YYYY-MM`，禁止混用下列月份：

| 字段 / 命令 | 含义 |
| --- | --- |
| `registrations.period`、`league_teams.period`、`import-reg`、`arrange`、`publish-results` | 即将参赛的联赛月份 |
| `league_results.period`、`fetch_cwl_data.py` | CWL 实际发生月份 |
| 普通战 `war_results.end_time` | 单场战争结束时间，不是月份事实 |

编排月份 `N` 必须读取 `registrations(N)`、`league_results(N-1)` 与 `league_teams(N-1)`。

## 6. CWL 编排与统计规则

### CWL 编排

标准流程：导入并标准化报名 → 同昵称保留最新 → 合并战营成员 → 保存报名事实 → 排序 → 以上月数据基准重建与升降级 → 贪心建队 → 白名单与管理员分配 → 回写并输出 Part1–4。

- 业务敏感配置集中在 `config/settings.yaml`，包括部落、黑白名单、队伍容量、预留位置、排序权重、升降级阈值与队伍顺序；不要重新引入散落 Python 配置模块。
- 实战队伍必须先于壳子队伍；白名单最后执行且优先级最高。涉及名单稳定性时，升级者不得跌破目标、降级者不得回到原队；冲突应保留白名单并产生可见告警。
- `league_teams` 是月度快照，不能把当前 YAML 队伍配置替代历史月份快照。
- Part4 和公示写入属于外部可见副作用：先验证编排结果，发布独立执行，不把它隐含进普通读操作。

### 战绩统计

- 联赛统计基于 `league_results`，按月窗口计算进攻 / 防守三星率；普通战统计基于 `war_results`，按每位玩家自己的最近 5/15/45 场计算。
- 普通战“满星前”规则不可简化：进攻仅统计我方达到 `team_size * 3` 星前的攻击；防守仅统计对手达到同一满星阈值前的攻击。两边各自按全局 `order` 排序累加。
- 互刷统计 API 只读 `farm_stats` 缓存，不可在请求路径直接批量调用 COC API；去速本算法使用双方 `mapPosition` 阶段判断，但只统计本方成员。
- 当前部落战从官方 `currentwar` 获取后先规范化并缓存到 `current_war_cache`；单个部落失败要隔离，不能抹掉其他部落结果。

## 7. API、认证与小程序

- FastAPI 应用入口是 `api_server.app:app`；路由通过 `api_server/deps.py` 获取共享 `Database`，不要为每个请求创建不受控的数据库。
- 秘钥只从环境变量 / 根目录 `.env` 加载。生产必须显式设置强 `JWT_SECRET`；不得使用开发默认值。
- 修改微信绑定流程必须先验证账号身份与归属关系；绑定是完整性敏感功能。
- CORS、认证保护范围、公开 API 字段与缓存 TTL 均需审慎评审，不能为了调试随意放宽。
- 小程序登录必须由用户主动勾选协议；未同意前不得调用微信登录、创建账号或读取受登录影响的资料。协议页保留可点击访问。
- 小程序请求走 `utils/api.js`，正式后端域名是 `https://api.skycoc.cc`。新页面须注册到 `pages.json`，并遵循 uni-app 的 `scroll-view`/flex 表格限制。
- `uni-app` 依赖安装后，如兼容性补丁需要，运行 `bash patches/apply-patches.sh`；构建命令为 `npm run dev:mp-weixin` 与 `npm run build:mp-weixin`。

## 8. 阵型采集与公众号发布安全边界

- 只使用已配置的官方 X 或 SocialData 来源；遵守 SocialData 请求预算，避免添加未授权抓取方式。
- 每次运行先按时间窗口增量拉取、按指纹去重；每位作者最多发布 5 个阵型，保持这一上限与测试。
- 默认行为是创建微信公众号草稿，由管理员在后台确认发布。
- `WAR_LAYOUT_AUTO_MASS_SEND` 是群发的硬安全开关：为 `false` 时，调度器、CLI 或函数参数均不得绕过并调用群发接口；`--once all` 永远不包含 `war_layout`。
- 群发仅在获得公众号权限、显式启用该环境变量并经过业务确认后才可进行；保留 `clientmsgid`、提交状态和不确定结果，避免盲目重发。
- 阵型子系统的媒体目录、独立 SQLite、代理与微信 HTTP 配置均来自环境变量；不打印其凭证或代理地址中的敏感信息。

## 9. 调度、外部系统与生产操作

`scripts/scheduler.py` 是唯一的持续调度实现，状态存于 `sync_jobs`。当前任务为：

- `current_wars`（每 2 分钟检查，按部落状态限频）；
- `cwl_live`（活跃期每 2 分钟）；
- `cwl_assembly`（月初窗口每 5 分钟）；
- `farm_stats`（30 分钟）；
- `coc_sync`（6 小时）；
- `player_details`（每天）；
- `member_combat_stats`（每天，全量窗口过期校正）；
- `capital_member_stats`（每 6 小时检查业务窗口）；
- `clan_games_stats`（每 6 小时检查业务窗口）；
- `war_results`（每天）；
- `cwl`（每天触发，仅规则允许的日期实际抓取）；
- `war_layout`（北京时间固定时刻，默认草稿）。

- 执行同步、导入、部署或运维脚本前，先使用项目认可的环境加载器（例如 `source scripts/load_env.sh`）；不要在未加载完整环境时运行，也不要打印 `.env`。
- 月度导入与编排是显式业务操作，推荐入口为 `scripts/register_and_arrange.sh YYYY-MM`；腾讯文档玩家档案导出目前保持手动。
- 生产中不要手动启动竞争的 uvicorn，尤其是 `--reload`。代码或配置变更后的重启、日志和状态检查使用 systemd。
- 不修改 SSH、用户、权限、防火墙、DNS、Nginx 或 systemd 配置，除非用户明确授权并指定范围。Nginx 改动后先 `nginx -t`；服务变更前后检查状态与日志。
- 证书续签应使用 Certbot/systemd 已有机制验证；域名证书与历史 IP 证书不可混用。

## 10. 测试、构建与提交

- Python 使用仓库虚拟环境，例如 `venv/bin/python -m pytest <target>`；优先跑目标模块，再按风险扩大范围。
- 生产构建在 `uni-app/` 执行 `npm run build:mp-weixin`。Shell 改动运行 `bash -n <script>`。
- 每次提交前运行 `git diff --check`；只报告实际执行且观察到退出成功的测试或构建。
- 测试和脚本可能命中配置数据库：先确认数据库路径，避免把测试当作对生产数据的默认安全操作。
- 提交按独立业务目的拆分（例如前端、调度、阵型模块），不夹带构建产物或无关格式化；除非用户明确要求，不自动 commit 或 push。

## 11. 已知缺口：避免无关修复

以下事项需独立需求、规则确认和针对性测试，不能在相邻改动中悄然“修好”：

- `history_score` 当前为占位值；
- 部分排序 / 输入校验的边界场景仍待完善；
- 名单和发布脚本仍可补充更完整的阶段间校验；
- 文档中的旧 API、任务数量、TODO 和历史架构可能落后于当前代码，更新前必须复核实现与 Git 历史。

行为改变时，更新相应设计文档，并把被替代的方案明确标为历史，而不是留下相互矛盾的说明。
