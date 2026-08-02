# scripts 目录使用文档

> 运维详情见 [`../docs/06-operations.md`](../docs/06-operations.md)

## 时间语义（重要）

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份（报名表为该月联赛报名） | `--period 2026-08` |
| `import-result` | 联赛月份（战绩所属月） | `--period 2026-08` |
| `fetch_cwl_data.py` | CWL 实际发生月（拉哪月传哪月） | `--period 2026-07` |
| `arrange` | 联赛月份（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛月份（一站式入口） | `2026-08` |

| `publish-results` | 联赛月份 | `--period 2026-08` |

规则：**registrations.period = 联赛月份，results.period = CWL/战绩实际发生月，league_teams.period = 联赛月份，league_results.period = CWL 实际发生月。**

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
2. 拉取 CWL 星数 → `league_results` + `results` 表（CWL 月 = 2026-07，自动推算 = 联赛-1）
3. 编排名单 + 基准重建 + 升降级 → 腾讯在线文档（联赛月份 = 2026-08）

前置：`.env` 中配置 `COC_API_TOKEN` + `TENCENT_DOC_*` + `REG_DOC_FILE_ID` + `ROSTER_DOC_FILE_ID`

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

### `fetch_cwl_data.py` — 拉取 CWL 战绩 + 导入 league_results + results 表

```bash
# 拉取 7 月 CWL 数据 + 导入 league_results + results 表（为 8 月联赛准备）
python scripts/fetch_cwl_data.py --period 2026-07
```

流程（两级降级）：
1. 查 `league_teams` 表获取当月 combat 队伍信息
2. ClashKing War Log API 拉取 → 直接写入 `league_results` + `results`（双写）
3. ClashKing 失败 → 降级本地 JSON（`data/cwl_YYYYMM/`）
4. league_teams 查不到 → 冷启动：读本地 JSON 导入

注意：Supercell 官方 API 的 `get_league_group` 只能查当前 CWL，不按月份过滤，已从降级链路移除。

升降级参与规则：只有**相邻两支队伍都成功拉到数据**时，该对相邻队伍才参与升降级。

---

## 其他运维脚本

| 脚本 | 说明 |
|------|------|
| `load_env.sh` | 公共环境变量加载器，被其他脚本 source |
| `sync_and_export.sh` | 长期维护：COC 同步 → 导出玩家档案 |
| `fetch_cwl_data.sh` | `fetch_cwl_data.py` 的便捷包装 |
