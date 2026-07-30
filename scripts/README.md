# scripts 目录使用文档

## 时间语义（重要）

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份（报名表为该月联赛报名） | `--period 2026-08` |
| `import-result` | 联赛月份（战绩所属月） | `--period 2026-08` |
| `fetch_cwl_data.py` | CWL 实际发生月（拉哪月传哪月） | `--period 2026-07` |
| `arrange` | 联赛月份（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛月份（一站式入口） | `2026-08` |

规则：**registrations.period = 联赛月份，results.period = CWL/战绩实际发生月。**

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
2. 拉取 CWL 星数 → `results` 表（CWL 月 = 2026-07，自动推算 = 联赛-1）
3. 编排名单 + 升降级 → 腾讯在线文档（联赛月份 = 2026-08）

前置：`.env` 中配置 `COC_API_TOKEN` + `TENCENT_DOC_*` + `REG_DOC_FILE_ID` + `ROSTER_DOC_FILE_ID`

---

### `fetch_cwl_data.py` — 拉取 CWL 战绩 + 导入 results 表

```bash
# 拉取 7 月 CWL 数据 + 导入 results 表（为 8 月联赛准备）
python scripts/fetch_cwl_data.py --period 2026-07

# 仅拉 JSON，不导入 DB
python scripts/fetch_cwl_data.py --period 2026-07 --fetch-only
```

回退逻辑：
1. COC API 拉取 → JSON → 导入 results 表
2. API 失败 → 检查本地 JSON 是否存在 → 导入
3. 全部失败 → 告警，编排时自动跳过升降级

升降级参与规则：只有**相邻两支队伍都成功拉到数据**时，该对相邻队伍才参与升降级。

---

### `fetch_cwl_data.sh` — 仅拉 JSON 的便捷包装

```bash
scripts/fetch_cwl_data.sh --period 2026-07
```

等价于 `python scripts/fetch_cwl_data.py --fetch-only --period 2026-07`

---

## 辅助脚本

### `probe_cwl_data.py` — COC API 端点探测

```bash
python scripts/probe_cwl_data.py '#2QQ'
python scripts/probe_cwl_data.py '#2GGGGGGG' --warlog-limit 10
```

测试 warlog / leaguegroup / warDetail 端点，验证数据可用性。

---

### `register_and_arrange.sh` — 全流程细节

```
register_and_arrange.sh 2026-08          ← 用户参数：联赛月份
  │
  ├─ REG_PERIOD = 2026-07                ← 自动推算：联赛-1（CWL 月，用于 fetch + sheet 名）
  │
  ├─ [1] import-reg --period 2026-08     ← 联赛月份
  │       registrations.period = 2026-08
  │       sheet 名按 REG_PERIOD(2026-07) 推算
  │
  ├─ [2] fetch_cwl_data.py --period 2026-07 ← CWL 实际发生月
  │       → COC API 拉 7月 CWL → JSON
  │       → results.period = 2026-07
  │
  └─ [3] arrange --period 2026-08        ← 联赛月份
          → 读 registrations(2026-08) + results(2026-07)
          → 升降级 → 导出 "名单_2026-08"
```

---

## 其他运维脚本

| 脚本 | 说明 |
|------|------|
| `load_env.sh` | 公共环境变量加载器，被其他脚本 source |
| `sync_and_export.sh` | 长期维护：COC 同步 → 导出玩家档案 |
| `probe_coc_clan.py` | 探测 COC 部落成员（调试用） |
| `dump_clans_to_xlsx.py` | 导出 COC 部落数据到本地 xlsx（调试用） |
