# 06 — 运维与月度操作

> 当前生产链路：`微信小程序 -> api.skycoc.cc -> Nginx -> sky-admin.service -> SQLite`。
> 常驻调度器是 `sky-scheduler.service`；不要再配置独立 cron 或手工常驻脚本。

## 日常检查

```bash
systemctl status sky-admin.service sky-scheduler.service
venv/bin/python scripts/scheduler.py --list
curl --fail https://api.skycoc.cc/api/ping
```

服务代码、配置或 schema 变更后：先运行目标测试和 `git diff --check`，再以 systemd 重启服务。
不要手工启动额外 uvicorn 或 scheduler。重启后检查 `/api/ping`、目标业务接口与
`PRAGMA integrity_check`。

COS 每天本机时间 03:15 创建一致恢复快照；03:35 将 `data/backups/` 的历史 SQLite 备份归档到
COS 并保留最新两份本地热备。高风险 SQLite 迁移、批量回填或物理删表前，额外执行：

```bash
venv/bin/python scripts/backup_to_cos.py --dry-run
venv/bin/python scripts/backup_to_cos.py
```

备份目录必须含最终 `manifest.json`；没有 manifest 的目录视为未完成，不能用于恢复。

## 月度 CWL 操作

`period` 的含义必须分清：

| 数据 / 命令 | period 含义 |
|---|---|
| `registrations`、`league_teams`、`import-reg`、`arrange` | 即将参赛的联赛月 N |
| `league_results`、`fetch_cwl_data.py`、`backfill_cwl_live.py` | 实际发生的 CWL 月 |

编排 N 月联赛时读取 `registrations(N)`、`league_results(N-1)` 和 `league_teams(N-1)`。

推荐流程：

1. 先确认上月原始 CWL 档案完整：分组目录的所有 `war_tag` 均为最终战争；
2. 运行 `venv/bin/python scripts/fetch_cwl_data.py --period N-1`，它只从本地完整档案重建
   `league_results`，不会访问第三方 API；
3. 导入报名并编排：`scripts/register_and_arrange.sh N`；
4. 审核 Part1–4 和升降级结果；外部公示是独立操作，确认后才运行发布脚本。

若缺少历史原始档案，先执行：

```bash
venv/bin/python scripts/backfill_cwl_live.py --period YYYY-MM
```

dry-run 必须覆盖全部当月队伍、分组和逐场战争，并与现有投影比对。确认无误后才添加 `--apply`。
该脚本会写入完整分组/逐场档案并重建投影；已有同月原始缓存时拒绝覆盖。

## 普通部落战

`current_wars` 按部落状态限频刷新官方 `currentwar`。只有完整的最终普通战才会归档到
`war_history_cache` 并物化 `member_war_facts`；每个启用部落保留最近 45 场。同步失败会保留
上次成功快照，不能以空响应覆盖。

补齐历史时使用：

```bash
venv/bin/python scripts/backfill_war_history.py --limit 100 --keep 45
venv/bin/python scripts/backfill_war_history.py --limit 100 --keep 45 --apply
```

默认是 dry-run；任一部落抓取或完整性检查失败即拒绝写入。旧 `war_results` 和
`member_combat_stats_cache` 已物理删除，不能重新创建或恢复旧聚合写入链路。

## 调度与异常

| 场景 | 正确处理 |
|---|---|
| 单个 COC 部落请求失败 | 保留该部落最后成功快照，记录 error/attempted_at；其他部落继续 |
| CWL 分组未完整 | 标记 `collecting` 或 `incomplete`，不写 `league_results` |
| 历史 CWL 缺档 | 用 `backfill_cwl_live.py` dry-run 后显式回填，不能导入第三方汇总数字 |
| SQLite 完整性异常 | 停止写入，使用最新有 manifest 的 COS 快照恢复并核验 |
| 小程序接口异常 | 先检查 `sky-admin.service`、本机 `/api/ping`、Nginx 日志，再检查域名和证书 |

敏感凭证只在 `.env` 中。运行脚本前用 `source scripts/load_env.sh` 或脚本内置安全加载器，
不要打印 `.env`、Token、OAuth Header 或用户隐私数据。

## 常用命令

```bash
# 只读查看任务状态
venv/bin/python scripts/scheduler.py --list

# 手动刷新一个本地缓存任务
venv/bin/python scripts/scheduler.py --once current_wars
venv/bin/python scripts/scheduler.py --once cwl_live --force

# 重建已有完整 CWL 原始档案的投影
venv/bin/python scripts/fetch_cwl_data.py --period 2026-09

# 验证生产数据库
source scripts/load_env.sh
venv/bin/python -c "from shared.db.connection import Database; import config; db=Database(config.DB_PATH); print(db.conn.execute('PRAGMA integrity_check').fetchone()[0])"
```
