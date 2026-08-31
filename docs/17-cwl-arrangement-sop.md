# CWL 联赛安排标准作业流程（SOP）

适用：每月联赛报名、编排和公示。以下以安排 `2026-09` 为例，实际月份替换为目标 `PERIOD`。

## 1. 明确月份语义

- `PERIOD` 是要安排的联赛月份，例如 `2026-09`。
- 报名表使用目标联赛月份；脚本自动推算报名收集 Sheet（`PERIOD - 1` 月）。
- CWL 战绩和升降级数据使用上一个实际发生月（`PERIOD - 1`）。

## 2. 修改并核对配置

编辑 `config/settings.yaml` 的 `cwl_registration`：

- `teams`：按 `team_index` 顺序填写队伍、Tag、负责人、容量、`category` 和 `league_level`；
- `category` 仅使用 `combat` 或 `shell`；
- `excluded_camp_names`：战营成员排除名单；
- `black_list`：本月不参加联赛的账号；
- `white_list`：确需强制安排的账号，确认后再填写。

检查队伍 Tag 唯一、容量和分类正确。黑名单与排除名单都会在编排中生效。

## 3. 凭证和环境检查

确认 `.env` 已配置且有效：`COC_API_TOKEN`、`TENCENT_DOC_*`、`REG_DOC_FILE_ID`、`ROSTER_DOC_FILE_ID`。
凭证过期时手动更新 `.env`，禁止在聊天、日志或 Git 中暴露 token。

## 4. 备份数据库

在任何导入或编排前备份 `data/league.db`，例如：

```bash
cp -p data/league.db /tmp/league.db.before-arrange-YYYY-MM
```

## 5. 执行一体化安排（不发布公示表）

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

## 6. 编排结果检查

确认终端报告：

- 总人数、已分配人数、未分配人数；
- 实战/壳子人数；
- 每队实际人数与容量；
- 黑名单命中记录；
- 升降级和离队/缺失名单；
- 关键账号没有重复 Tag 或错误部落归属。

特别检查：黑名单账号不应出现在最终名单；`excluded_camp_names` 不应进入战营名单。

## 7. 发布公示报名表（可选、单独执行）

确认安排无误后，才执行：

```bash
source scripts/load_env.sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    bash scripts/publish_to_results.sh YYYY-MM
```

该步骤写入 `PUBLISH_DOC_FILE_ID` 指定的公示文档，与安排文档分开。若腾讯文档只有一个显示中的 Sheet，删除旧 Sheet 可能失败；应先保留或新建一个备用 Sheet 后重试。

## 8. 失败处理

- 报名导入失败：不要继续编排，检查文档 Sheet、凭证和网络；确认数据库备份可用。
- COC API 失败或超时：检查 API Key IP 白名单；可稍后重试，不要使用代理绕过项目要求。
- 编排成功但公示发布失败：安排数据仍可能已写入数据库/安排文档，只重试 `publish_to_results.sh`。
- 任何重试前确认目标月份，避免误操作其他月份。

## 9. 完成记录

记录执行日期、目标月份、导入条数、上月战绩条数、最终人数、黑名单命中、未分配人数、公示发布状态和备份路径。凭证值不记录。
