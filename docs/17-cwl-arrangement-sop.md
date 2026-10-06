# CWL 联赛安排标准作业流程（SOP）

适用：每月联赛报名、编排和公示。以下以安排 `2026-09` 为例，实际月份替换为目标 `PERIOD`。

## 1. 明确月份语义

- `PERIOD` 是要安排的联赛月份，例如 `2026-09`。
- 报名表使用目标联赛月份；脚本自动推算报名收集 Sheet（`PERIOD - 1` 月）。
- CWL 战绩和升降级数据使用上一个实际发生月（`PERIOD - 1`）。

## 2. 先审计上月数据（只读）

在修改本月配置、导入报名或执行编排前，先打印上月每支队伍的状态：

- `team_index`、队伍别名、COC 真实部落名和 Tag；
- 实际参赛人数、`league_results` 战绩条数和缺失人数；
- 联赛结束后的新等级；
- 实际参赛部落与 `league_teams(PERIOD - 1)` 历史快照是否一致。

逐队确认上月实战结果完整。遇到临时换部落时，以实际参赛 Tag 修正对应月份的历史事实，不能直接
拿本月 YAML 覆盖上月快照；遇到五轮等缩短赛程时，确认 `attacks` 能反映实际轮次，使门槛按
12/15、15/15 换算。缺失或错配未解释清楚前，不进入本月编排。

## 3. 修改并核对配置

编辑 `config/settings.yaml` 的 `cwl_registration`：

- `teams`：按 `team_index` 顺序填写队伍、Tag、负责人、容量、`category` 和 `league_level`；
- `category` 仅使用 `combat` 或 `shell`；
- `excluded_camp_names`：战营成员排除名单；
- `black_list`：本月不参加联赛的账号；
- `white_list`：确需强制安排的账号，确认后再填写。

检查队伍 Tag 唯一、容量和分类正确。黑名单与排除名单都会在编排中生效。
`black_list` 按 `account_name` 精确匹配且区分大小写；同一昵称可能出现大小写变体时要分别配置。

## 4. 凭证和环境检查

确认 `.env` 已配置且有效：`COC_API_TOKEN`、腾讯文档凭证、`REG_DOC_FILE_ID`、`ROSTER_DOC_FILE_ID`。

腾讯文档默认使用官方 MCP：

```dotenv
TENCENT_DOC_BACKEND=mcp
TENCENT_DOCS_TOKEN=在腾讯文档授权页生成的Token
```

MCP Token 按腾讯文档空间授权，有效期 1 年；到期或泄露后在
[腾讯文档 MCP 授权页](https://docs.qq.com/open/auth/mcp.html)重置。不要把 Token 粘贴到聊天、日志或 Git。

保留的 OpenAPI v3 可用于 MCP 故障时回退。确认旧凭证仍有效后，将
`TENCENT_DOC_BACKEND` 改为 `openapi`；恢复 MCP 时改回 `mcp`。也可只对单次命令临时覆盖：

```bash
TENCENT_DOC_BACKEND=openapi bash scripts/register_and_arrange.sh YYYY-MM
```

写入失败后先检查腾讯文档中的实际结果，再决定是否重跑或切换后端。程序不会在写操作中途自动
切换后端，以免请求结果不明确时重复写入。OpenAPI 配置 `TENCENT_DOC_CLIENT_SECRET` 和
`TENCENT_DOC_REFRESH_TOKEN` 后仍支持自动刷新 Access Token。

2026-10-06 已完成 MCP 生产验收：成功读取正式报名文档的 36 个 Sheet 和合并单元格，导入
233 条十月报名，重建九月 243 条战绩，完整写入并回读中间名单。创建、覆盖、清空、扩缩表、
样式、冻结和筛选此前也已在临时文档逐项验证；正式公示文档未用于测试写入。

## 5. 备份数据库

在任何导入或编排前备份 `data/league.db`，例如：

```bash
cp -p data/league.db /tmp/league.db.before-arrange-YYYY-MM
```

## 6. 执行一体化安排（不发布公示表）

```bash
source scripts/load_env.sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    bash scripts/register_and_arrange.sh YYYY-MM
```

脚本包含三步：

1. 清理目标月份 `registrations` 旧快照，导入当前报名 Sheet，并合并当前 `#2QQ` 战营成员；
2. 拉取上月 CWL 星数，写入 `league_results`；
3. 执行 `arrange`，更新安排文档 `ROSTER_DOC_FILE_ID`。

导入时同一 COC Tag 对应多个报名昵称只告警并继续，不会中止；需在输出中记录并人工核对。

## 7. 编排结果检查

确认终端报告：

- 总人数、已分配人数、未分配人数；
- 实战/壳子人数；
- 每队实际人数与容量；
- 黑名单命中记录；
- 升降级和离队/缺失名单；
- 关键账号没有重复 Tag 或错误部落归属。

特别检查：黑名单账号不应出现在最终名单；`excluded_camp_names` 不应进入战营名单。

还要把升降级日志与离队/缺失名单做交叉核对。升降级只评价上月表现，不以本月是否报名过滤候选：
先依据上月实际名单和战绩完成配对，再删除本月缺席者。缺席的下队满星成员仍占用晋级名额，
与其配对的上队成员保留降级；缺席的上队降级成员被删除后，与其配对的下队成员仍保留升级。
同表现候选沿用上月队内顺序，每对最多交换 2 人；下队没有满星候选时不执行对应降级。

同月重跑时，程序会清空该月全部报名记录的旧 `league_type`、`rank_order`、`team_info`，再只回写
本次实际分配；修改黑名单、排除名单或报名后可以直接重跑，但仍需重新核对输出并单独更新公示表。

上述重跑只适用于正式发布前的编排阶段。正式表发布并由管理员人工修改后，正式表与数据库报名
快照已经是两个事实源：`arrange` 会重新读取最新报名和当前配置，不会把正式表的换人、占位号、
补位或手工换队反向导入数据库。因此，发布后的测试重跑只能写中间文档，必须与正式表逐队对比，
不得因为命令成功就再次发布。若需要稳定复现月初名单，应使用冻结的报名/配置快照，或先设计正式
名单回写与锁定机制。

十月验收中，月初正式表为 243 人，本次按最新报名重排为 230 人；新增实战队按普通队伍填入真实
成员，加上报名变化和正式表人工调整，造成大量队伍变化。这是当前重建语义的结果，不是 MCP 读写
错误。正式表及其活动 `cwl_roster_snapshots` 快照仍是开赛后的展示与集结核对依据。

## 8. 发布公示报名表（可选、单独执行）

确认安排无误后，才执行：

```bash
source scripts/load_env.sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    bash scripts/publish_to_results.sh YYYY-MM
```

该步骤写入 `PUBLISH_DOC_FILE_ID` 指定的公示文档，与安排文档分开。MCP 后端会原地清空并覆盖
同名 Sheet；OpenAPI 后端仍使用删表重建，文档只有一个 Sheet 时应先保留或新建备用 Sheet。
发布完成后打开公示文档，确认当月同名 Sheet、队伍数量和最终人数与审核通过的工作名单一致。

## 9. 开赛和匹配检查

每支队伍开始搜索后，由当月负责人记录“已点击搜索”；系统随后通过 COC 官方
`/clans/{clanTag}/currentwar/leaguegroup` 检查是否已匹配完成。两者是不同事实：

- 官方返回当月 `season`、小组部落和轮次，表示已经匹配完成；`preparation` 表示进入准备日；
- 官方只返回 `{"state":"notInWar"}` 时，可能尚未点击搜索，也可能已经搜索但仍在匹配；
- `currentwar` 在搜索阶段也可能只返回 `notInWar`，不能用它补判“搜索中”；
- 官方赛季可能是 `YYYY-MM-DD`，判断月份前先规范化为 `YYYY-MM`；
- 页面和检查报告统一写“尚未生成联赛分组，可能正在搜索对手”，不得写成确定的“尚未开启”。

因此，每月开赛检查应分别报告“负责人确认已搜索”和“官方确认已匹配”两列。系统可以自动确认
后者，前者只能来自负责人确认或独立的人工操作记录。

## 10. 失败处理

- 报名导入失败：不要继续编排，检查文档 Sheet、凭证和网络；确认数据库备份可用。
- COC API 失败或超时：检查 API Key IP 白名单；可稍后重试，不要使用代理绕过项目要求。
- 编排成功但公示发布失败：安排数据仍可能已写入数据库/安排文档，只重试 `publish_to_results.sh`。
- 任何重试前确认目标月份，避免误操作其他月份。

## 11. 完成记录

记录执行日期、目标月份、导入条数、上月战绩条数、最终人数、黑名单命中、未分配人数、公示发布状态和备份路径。凭证值不记录。
