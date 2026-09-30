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

确认 `.env` 已配置且有效：`COC_API_TOKEN`、`TENCENT_DOC_*`、`REG_DOC_FILE_ID`、`ROSTER_DOC_FILE_ID`。
腾讯文档推荐配置 `TENCENT_DOC_CLIENT_SECRET` 和 `TENCENT_DOC_REFRESH_TOKEN`，Access Token 失效时会自动刷新并重试；Refresh Token 官方有效期为 1 年。调试 Access Token 无刷新能力，过期后仍需手动更新。禁止在聊天、日志或 Git 中暴露任何凭证。

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
2. 拉取上月 CWL 星数，写入 `league_results` 和 `results`；
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

还要把升降级日志与离队/缺失名单做交叉核对。当前流程先依据上月实际名单和战绩完成配对交换，
再删除本月缺席者；所以缺席的下队满星成员可能先占用晋级名额，随后被删除，而与其配对的上队
成员仍然降级。是否改成“本月没有合格补位者就不降级”尚未定案，发布前应人工识别并确认当月结果。

同月重跑时，程序会清空该月全部报名记录的旧 `league_type`、`rank_order`、`team_info`，再只回写
本次实际分配；修改黑名单、排除名单或报名后可以直接重跑，但仍需重新核对输出并单独更新公示表。

## 8. 发布公示报名表（可选、单独执行）

确认安排无误后，才执行：

```bash
source scripts/load_env.sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    bash scripts/publish_to_results.sh YYYY-MM
```

该步骤写入 `PUBLISH_DOC_FILE_ID` 指定的公示文档，与安排文档分开。若腾讯文档只有一个显示中的 Sheet，删除旧 Sheet 可能失败；应先保留或新建一个备用 Sheet 后重试。
发布完成后打开公示文档，确认当月同名 Sheet、队伍数量和最终人数与审核通过的工作名单一致。

## 9. 失败处理

- 报名导入失败：不要继续编排，检查文档 Sheet、凭证和网络；确认数据库备份可用。
- COC API 失败或超时：检查 API Key IP 白名单；可稍后重试，不要使用代理绕过项目要求。
- 编排成功但公示发布失败：安排数据仍可能已写入数据库/安排文档，只重试 `publish_to_results.sh`。
- 任何重试前确认目标月份，避免误操作其他月份。

## 10. 完成记录

记录执行日期、目标月份、导入条数、上月战绩条数、最终人数、黑名单命中、未分配人数、公示发布状态和备份路径。凭证值不记录。
