# scripts 目录使用文档

> 运维详情见 [`../docs/06-operations.md`](../docs/06-operations.md)

## 时间语义（重要）

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份（报名表为该月联赛报名） | `--period 2026-08` |
| `fetch_cwl_data.py` | 从完整本地 CWL 原始档案重建实际发生月投影 | `--period 2026-07` |
| `arrange` | 联赛月份（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛月份（一站式入口） | `2026-08` |

| `publish-results` | 联赛月份 | `--period 2026-08` |

规则：**registrations.period = 联赛月份，league_teams.period = 联赛月份，league_results.period = CWL 实际发生月。**

示例：8 月联赛需要 8 月报名数据 + 7 月 CWL 星数
- 导入报名：`--period 2026-08`
- 拉 CWL 星数：`--period 2026-07`（上月 CWL）
- 安排联赛：`--period 2026-08`

---

## 核心脚本

### `register_and_arrange.sh` — 一键全流程（推荐）

每月跑一次。

```bash
# 安排 8 月联赛
scripts/register_and_arrange.sh 2026-08
```

内部三步：
1. 导入报名表 → `registrations`（联赛月份 = 2026-08；sheet 名按报名月 2026-07 推算）
2. 从完整本地 CWL 原始档案重建星数 → `league_results` 表（CWL 月 = 2026-07，自动推算 = 联赛-1）
3. 编排名单 + 基准重建 + 升降级 → 腾讯在线文档（联赛月份 = 2026-08）

前置：`.env` 中配置 `COC_API_TOKEN` + `TENCENT_DOC_*` + `REG_DOC_FILE_ID` + `ROSTER_DOC_FILE_ID`。推荐同时配置 `TENCENT_DOC_CLIENT_SECRET` 和 `TENCENT_DOC_REFRESH_TOKEN`，以便 Access Token 失效时自动刷新。

---

### `publish_to_results.sh` — 发布 Part4 网格到公示文档

```bash
scripts/publish_to_results.sh 2026-08
```

内部：
1. 调用 `publish-results --period 2026-08` 
2. 走完整 `arrange()` 流程，生成 Part4 网格
3. 拼接前 20 行固定文字 + Part4 网格 → 写入 `PUBLISH_DOC_FILE_ID`

前置：`registrations` 表已有编排数据（即 `arrange` 已执行过）。

---

### `fetch_cwl_data.py` — 从完整 CWL 原始档案重建 `league_results`

```bash
# 从完整的 7 月 CWL 原始档案重建 league_results（为 8 月联赛准备）
python scripts/fetch_cwl_data.py --period 2026-07
```

流程：读取 `league_teams`、`cwl_live_group_cache` 和 `cwl_live_war_cache`；只有一支队伍所在
分组的全部 `war_tag` 都为最终档案时，才替换该队当月的 `league_results`。它不访问 ClashKing，
不导入本地汇总 JSON，也不在档案不完整时清空已有投影。历史缺档先执行
`backfill_cwl_live.py`（默认 dry-run），由该脚本把完整逐场档案写入后再重建。

---

## 其他运维脚本

| 脚本 | 说明 |
|------|------|
| `load_env.sh` | 公共环境变量加载器，被其他脚本 source |
| `sync_and_export.sh` | 长期维护：COC 同步 → 导出玩家档案 |
| `fetch_cwl_data.sh` | `fetch_cwl_data.py` 的便捷包装 |
| `backfill_cwl_live.py` | 从 ClashKing 历史战争日志重建指定月份的联赛看板缓存；默认 dry-run，`--apply` 才写库 |
| `backfill_war_history.py` | 从 ClashKing 重建各自有部落最近 45 场普通战争完整详情；默认 dry-run，`--apply` 才写库 |
| `import_farm_fill_accounts.py` | 一次性从指定腾讯文档 Sheet 导入互刷填坑号；默认 dry-run，不进入周期调度 |
| `retire_normal_war_legacy.py` | 校验新版普通战事实后，备份并删除旧投影表；默认 dry-run，`--yes` 才执行 |
| `backup_to_cos.py` | 通过 SQLite Online Backup API 创建一致快照，上传到已挂载的 COS；`.env` 永不进入备份 |
| `archive_local_backups_to_cos.py` | 将 `data/backups` 的历史 SQLite 备份校验后归档 COS；默认 dry-run，显式清理时保留最新两份本地副本 |

---

### 历史联赛看板回填

实时看板上线前缺失的月份先执行只读校验：

```bash
source scripts/load_env.sh
venv/bin/python scripts/backfill_cwl_live.py --period 2026-09
```

确认全部月度队伍、轮次、对阵和已有历史汇总均通过，并完成 `data/league.db`
一致性备份后，再显式写入：

```bash
venv/bin/python scripts/backfill_cwl_live.py --period 2026-09 --apply
```

脚本不会覆盖目标月份已有的 `cwl_live_group_cache` 或 `cwl_live_war_cache`。
它是一次性运维修复工具，不替代 `scheduler.py` 的月初实时同步。

战争日志偶尔会缺少单场，但 ClashKing 的专用 CWL 赛季档案仍可能完整保存整个分组。历史月份
可传入 `--prefer-archive`，优先读取专用赛季档案，并用现有 `league_results` 的星数与刀数逐玩家
交叉核对；专用档案不可用时才回退战争日志。dry-run 与正式写入必须分别执行：

```bash
venv/bin/python scripts/backfill_cwl_live.py --period 2026-08 --prefer-archive
venv/bin/python scripts/backfill_cwl_live.py --period 2026-08 --prefer-archive --apply
```

若同一自然月存在多套赛季档案，脚本默认拒绝选择。只有业务口径已经写入正式文档时，才可用
`--archive-season` 精确选择一套档案；显式选择失败时不会回退到可能混合多套赛季的战争日志。
2026-06 的已确认例外只统计月初赛季，命令如下：

```bash
venv/bin/python scripts/backfill_cwl_live.py --period 2026-06 --archive-season 2026-06
venv/bin/python scripts/backfill_cwl_live.py --period 2026-06 --archive-season 2026-06 --apply
```

月中赛季 `2026-06-16` 明确排除。以后出现同月多赛季时不得照搬此参数，必须重新确认业务口径。

如果同一 `clan_tag` 在一个自然月匹配到多套联赛赛季档案，当前缓存主键无法无损保存多个分组。
脚本必须拒绝写入，该月的 `appearances` / `missed_attacks` 继续保留 `NULL`，不能挑选其中一套，
也不能把未知解释为零。

### 最近普通部落战回填

先对所有启用自有部落执行只读校验：

```bash
source scripts/load_env.sh
venv/bin/python scripts/backfill_war_history.py
```

确认输出完整并备份 `data/league.db` 后，才执行：

```bash
venv/bin/python scripts/backfill_war_history.py --apply
```

`--apply` 只有在全部已启用部落均拉取成功后才开启事务写入；写入历史战争时不会删除
实时同步保存的准备日或战斗日快照。生产执行前仍须先备份 `data/league.db`。

脚本按部落幂等覆盖同一场战争并裁剪到最近 15 场；CWL 和不完整历史记录不会写入。

---

## `backup_to_cos.py` — 每日恢复备份

`sky-admin-cos-backup.timer` 每天本机时间 03:15 调用本脚本。它会创建主库和阵型库的
SQLite 一致性快照、Git bundle、非敏感恢复资料压缩包，并逐个校验 SHA-256 后写入
`/sky_coc/rebuild/sky-admin/<UTC 时间戳>/`。最后写入的 `manifest.json` 是成功完成标记；
没有该文件的目录不得用于恢复。

首次安装或排障时可只做本地验证：

```bash
venv/bin/python scripts/backup_to_cos.py --dry-run
```

脚本只接受活动的 `fuse.cosfs` 挂载，避免 COS 挂载失效时误写本机目录。`.env` 与所有
凭证均明确排除；恢复时需从安全的独立位置重新提供 `.env`。远端保留和清理由 COS 生命周期
策略负责，脚本不会删除任何已上传的备份目录。

---

## `archive_local_backups_to_cos.py` — 本地历史备份归档

`sky-admin-cos-archive.timer` 每天本机时间 03:35 执行，在 03:15 的恢复快照完成后，归档
`data/backups/` 中的静态 SQLite 备份到
`/sky_coc/archive/sky-admin/local-db-backups/<UTC 时间戳>/`。每个文件先执行
`PRAGMA integrity_check`，上传后校验 SHA-256，最后写入 `manifest.json`；只有全部成功后才删除
较旧的本地副本，并始终保留按修改时间最新的两份。

它不会处理活动 `league.db`、`.env`、运行目录、任意用户目录或 `recovery-quarantine`。手工验证：

```bash
venv/bin/python scripts/archive_local_backups_to_cos.py
venv/bin/python scripts/archive_local_backups_to_cos.py --apply --prune-local --keep-local 2
```

---

## `retire_legacy_results.py` — 删除已退役的旧战绩表

仅在不再需要手工 `import-result`、且移除旧表读写代码已经部署后使用。脚本先验证
每条旧 `results` 记录都能在结构化 `league_results` 找到对应玩家、月份和类别，再创建一份
新的已校验 COS 恢复备份，最后才在 SQLite 事务中删除旧表。

```bash
# 只做生产库预检，不写 COS、不改数据库
venv/bin/python scripts/retire_legacy_results.py --dry-run

# 预检通过后执行；COS 挂载失效或存在未迁移数据会拒绝删除
venv/bin/python scripts/retire_legacy_results.py --yes
```

该命令不可替代部署流程：先发布不再引用旧表的代码，再运行删除；切勿在旧版调度器或旧版
CLI 仍可能运行时提前删表。

---

## `scheduler.py` — 周期数据刷新调度器

统一管理 7 类周期任务，状态存 `sync_jobs` 表；`war_layout` 固定在北京时间每天 09:00 运行，其余任务使用间隔调度。其中 `cwl_live` 仅在北京时间每月 1～12 日访问官方联赛接口。

- **运维命令 / CLI 用法**：见 [`../deploy/README.md`](../deploy/README.md)「四、运维命令速查 → 2. sky-scheduler 服务管理」
- **设计文档**：见 [`../docs/15-scheduler.md`](../docs/15-scheduler.md)
