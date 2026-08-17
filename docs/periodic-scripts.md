# 周期性数据更新脚本说明

> ⚠️ **本文档已废弃**，仅保留历史记录。周期调度方案已重新设计，请移步：
> - **[`15-scheduler.md`](./15-scheduler.md)** — 周期调度方案设计（含数据表与刷新脚本全景梳理）

---

## 废弃原因

本文档早期描述的 **systemd timer（`sky-sync-*.timer`）+ `manage-cron.sh` + `install-cron.sh`** 方案从未实际落地，与仓库现状不符：

| 旧文档描述 | 实际现状 |
|-----------|---------|
| `deploy/systemd/sky-sync-*.timer` | 不存在，`deploy/` 只有 `sky-admin.service`（FastAPI） |
| `scripts/manage-cron.sh` | 不存在 |
| `deploy/install-cron.sh` | 不存在 |
| 定时任务经 journald 管理 | 无 |

新方案改为**常驻 loop 进程 + `sync_jobs` 状态表 + `scheduler.py`**，详见 `15-scheduler.md`。

---

## 历史内容（保留存档）

<details>
<summary>点击展开旧方案正文</summary>

### 概述

项目中有 **4 张数据库表** 的数据需要通过外部 API 拉取，对应多个独立脚本负责周期性更新。

### 1. 部落成员档案同步（`accounts` 表）

| 项目 | 内容 |
|---|---|
| 脚本入口 | `cli.py coc-sync` |
| 数据来源 | Supercell 官方 COC API |
| 建议频率 | 每天 1 次 |

### 2. 互刷部落大本配置统计（`farm_stats` 表）

| 项目 | 内容 |
|---|---|
| 脚本 | `scripts/sync_farm_stats.py` |
| 建议频率 | 每 30 分钟 |

### 3. CWL 联赛战绩（`league_results` 表）

| 项目 | 内容 |
|---|---|
| 脚本 | `scripts/fetch_cwl_data.py --period YYYY-MM` |
| 建议频率 | 每月 1 次 |

### 4. 普通部落战战绩（`war_results` 表）

| 项目 | 内容 |
|---|---|
| 脚本 | `scripts/fetch_war_data.py --clan-tag "#2QQ"` |
| 建议频率 | 每天 1 次 |

</details>
