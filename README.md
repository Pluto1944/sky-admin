# sky-admin · 联赛报名与名单编排管理系统

按账号管理部落联赛的**报名导入 → 名单编排 → 战绩回写 → 结果发布**，长期跟踪账号状态。设计细节见 [`DESIGN.md`](./DESIGN.md)。

## 环境

- Python 3.9+
- 安装依赖：

```bash
pip install -r requirements.txt        # 运行依赖 (pandas, openpyxl)
pip install -r requirements-dev.txt    # 测试依赖 (pytest, pytest-cov)
```

## 每月使用流程

```bash
# 0.（首次/每期）通过 COC API 同步部落成员，以真实 Tag 权威建档
python cli.py coc-sync                              # 同步 config.CLANS 里全部 enabled 部落
python cli.py coc-sync --clan '#2QQ' --clan '#XX'   # 临时只同步指定部落（覆盖配置）

# 1. 导入报名表（写入 registrations 报名事实；按昵称反查真实 Tag 缓存，并刷新账号报名状态）
python cli.py import-reg 报名表.xlsx --period 2026-07

# 2. 生成实战/壳子名单、队伍分配并导出（同一 sheet：排序名单 + 队伍明细 + Part4 网格）
python cli.py arrange --period 2026-07 -o 名单.xlsx

# 3. 将 Part4 编排结果发布到公示文档
python cli.py publish-results --period 2026-07 --file-id <docId>

# 4. 联赛结束后导入战绩，更新历史分
python cli.py import-result 战绩表.xlsx --period 2026-07

# 查看账号档案（可按状态过滤）
python cli.py accounts --status active

# 导出 player 库到腾讯在线文档，供人工核对（-o 为 fileId，或读 TENCENT_DOC_FILE_ID）
python cli.py player-export --to tencent -o <fileId>

# 清空并重建数据库（历史数据清零，带二次确认；-y 跳过确认）
python cli.py reset-db
```

## 账号身份与两阶段数据流

- **主键 = COC 真实 Tag**：`accounts.player_tag` 为 COC 官方 Tag（`#XXXX`），名实相符。`accounts` **只由 `coc_sync`（COC 权威）与 `war_result`（历史分）填充**，报名侧只读、绝不建行。
- **COC 为权威建档源**：`coc-sync` 先跑，把部落全员按真实 Tag 建档；战绩再在其上**增量更新**历史分，字段分组、互不覆盖（COC 组 vs 战绩组）。
- **报名事实自成一表（B 方案）**：`registrations` 是**自包含的报名事实源**——自持 `account_name`（报名昵称，主标识）/ `player_name`（主号归属），唯一键为 `(account_name, period)`，与 `accounts` **解耦、无外键**。`player_tag` 降为「命中真实账号时缓存的关联」，可空、无 FK。
- **昵称 → 真实 Tag 反查（只读增强）**：导入报名时按 `account_name` 只读反查已建档的真实 Tag，命中就把它缓存进 `registrations.player_tag`（供排序阶段直接取历史分）。
- **两类差集**：
  - COC 有、报名无 → 正常（该账号本月没报名）。
  - 报名有、COC 无 → 报名照常入 `registrations`，`player_tag` 留空、排序时该账号得 0 分（新人本就没战绩），**主表零污染、不再临时建档、不再需要合并**。等 `coc-sync` 后续同步到这个人，下次排序按昵称即可自动命中真实得分——零合并、零告警。

## 报名表列名（默认，可在 config.py 调整）

> 主键 `player_tag` 为 **COC 真实 Tag**（由 `coc-sync` 建档）。报名表本身**无 Tag 列**，靠"游戏昵称"反查真实账号；下列为报名表实际列。

| 列 | 说明 |
|----|------|
| 主号游戏昵称 | 归属人（主号） |
| 游戏昵称 | 账号名，用于反查真实 Tag |
| 匹配值 | 本月匹配值 |
| 想实战？ | 是 / 否（普通账号有效；战营默认实战） |
| 提交时间 | 同名去重取最新 |

## 项目结构（v2.0 领域模块）

```
cli.py                       # 命令行入口
shared/                      # 基础设施：config/common、columns、io_adapter、db/connection
modules/
  player/                    # ① 玩家中枢：PlayerService（账号读写唯一入口）+ repository + status_rule
  cwl_registration/          # ② CWL 报名：importer(报名→registrations) + roster(报名快照→名单+队伍分配，含排除名单过滤) + sorter + rank_score + team_filler
  war_result/                # ③ 战绩：importer(→历史分) + history_score + repository
  coc_sync/                  # ④ COC 同步：api_client(底层HTTP) + mapper(纯函数映射) + config(部落清单) + service(唯一API编排出口)
scripts/                     # 运维脚本：register_and_arrange.sh（报名一体化）/ publish_to_results.sh（发布公示）/ sync_and_export.sh（长期维护）/ load_env.sh（凭证加载）
tests/                       # 按模块归类：shared / player / cwl_registration / war_result / coc_sync
```

> 架构：按业务领域分模块，`player` 为数据中枢，其他模块只通过 `PlayerService` 读写账号；**所有 COC API 调用统一经 `CocSyncService` 封装**，其它模块/脚本不直接使用 `CocApiClient`。详见 [`DESIGN.md`](./DESIGN.md) §十三。

## 两个可插拔开放函数（后续自行完善）

- `modules/war_result/history_score.py :: compute_history_score()` — 历史战绩综合分，**占位待补公式**。
- `modules/cwl_registration/rank_score.py :: compute_rank_score()` — 名单排序综合分，**已给归一化加权默认实现**，可深入替换。

## 队伍分配（在排序名单基础上自动分区）

`arrange` 命令在生成排序名单后，会**自动按 `TEAMS` 配置将人员分配到各队伍**，并输出到同一 sheet 的下半部分。

### 队伍配置 (`TEAMS`)

每队包含以下字段：

| 字段 | 说明 |
|------|------|
| `name` | 队伍名称，如"实战一队" |
| `clan_tag` | 部落标签 `#XXXXX` |
| `leader` | 领队（默认空字符串） |
| `member_count` | 标准人数（15 或 30） |
| `league_level` | 联赛等级（默认空字符串） |
| `manager` | 管理员名称 |
| `category` | `combat`（实战）或 `shell`（壳子） |
| `reserved_slots` | 预留位置：`>0` 留空位 / `0` 不预留 / `<0` 多招备选 |

### 分配规则

1. **阈值过滤**：`match_value < COMBAT_MIN_MATCH_VALUE` 的**普通实战账号**强制参加壳子（战营账号 `account_type=combat` 不受阈值影响，始终留在实战池）
2. **按序填充**：按排序名单顺序依次分配到各队伍
3. **最后一个实战队边界处理**：
   - ③a 人数刚好 → 不做修改
   - ③b 实战人溢出 → 多的人注入壳子池，按匹配值重新排序
   - ③c 实战缺口 <5 → 从壳子池协调匹配值相近的成员过来
   - ③d 实战缺口 ≥5 → 不协调，队伍不满员

### 输出格式

同一 sheet 分为四个区域：
- **Part 1**：完整排序名单（含 `cur_team`/`prev_team` 列）
- **Part 2**：按队伍分组展示分配明细
- **Part 3**：缺席老兵列表
- **Part 4**：联赛名单排布网格（5 列横向排布，备份留底）

## 配置说明

| 配置项 | 位置 | 说明 |
|--------|------|------|
| `SORT_WEIGHTS` | `cwl_registration/config.py` | 排序权重：匹配值 0.6 / 历史分 0.4 |
| `CAMP_CLAN_TAG` | `cwl_registration/config.py` | 战营部落标签（`#2QQ`，成员即战营账号） |
| `EXCLUDED_CAMP_NAMES` | `cwl_registration/config.py` | 战营排除名单：不参与排序的账号昵称集合，在导入和排序两阶段过滤 |
| `TEAMS` | `cwl_registration/config.py` | 队伍配置列表：每队含名称/人数/联赛等级/标签/管理/类别(combat\|shell)/预留位置 |
| `COMBAT_MIN_MATCH_VALUE` | `cwl_registration/config.py` | 实战最低匹配值门槛：低于此值的普通实战账号强制转壳子（战营账号豁免） |
| `IO_ADAPTER` | `shared/config/common.py` | IO 适配器：`tencent`（腾讯文档）或默认本地 xlsx |

## 运行测试

```bash
pytest              # 全部用例
pytest --cov=.      # 带覆盖率
```

## 关于在线文档

分两步走，长期维护部落数据并同步到腾讯在线文档供人工核对：

```bash
# 第 1 步：COC 官方 API -> player 数据库（建档/更新/退部对账）
python cli.py coc-sync

# 第 2 步：player 数据库 -> 腾讯在线文档（-o 为文档 fileId，缺省读 TENCENT_DOC_FILE_ID）
python cli.py player-export --to tencent -o <fileId>

# 也可一条命令跑完两步（适合放进 cron 定时维护）
export TENCENT_DOC_FILE_ID=<fileId>
scripts/sync_and_export.sh
```

- `player-export --to tencent` 只影响本条命令，不改动全局 `IO_ADAPTER`；导出的是
  `player` 库的完整业务视图（含报名状态、历史分、部落身份等），带筛选/冻结（腾讯侧忽略）。
- 底层是 `shared/io_adapter/tencent_doc.py`（腾讯文档 OpenAPI v3）；如需让所有命令
  默认走在线文档，可把 `shared/config/common.py` 的 `IO_ADAPTER` 切为 `'tencent'`。

> ⚠️ **授权现状（重要）**：当前采用**调试 access_token（B 方案）**，**没有 refresh_token、不做自动刷新**。
> `TENCENT_DOC_ACCESS_TOKEN` **有效期约 30 天，到期需手动更新**：回腾讯文档开放平台「开发者信息」复制新 token，重新 `export` 环境变量即可。
> 所有凭证（COC / 腾讯）一律走**环境变量**，切勿写进脚本或提交仓库。
