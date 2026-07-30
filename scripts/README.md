# scripts 目录使用文档

## 时间语义（重要）

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 报名时间（报名表提交月） | `--period 2026-07` |
| `fetch_cwl_data.py` | 报名时间（CWL 实际发生月） | `--period 2026-07` |
| `arrange` | 联赛时间（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛时间（一站式入口） | `2026-08` |

规则：**读数据的接口用实际发生月，安排联赛的接口用联赛所在月。**

示例：8 月联赛需要 7 月报名数据 + 7 月 CWL 星数
- 拉数据：`--period 2026-07`
- 安排：`--period 2026-08` / `2026-08`

---

## 核心脚本

### `register_and_arrange.sh` — 一键全流程（推荐）

每月跑一次。

```bash
# 安排 8 月联赛
scripts/register_and_arrange.sh 2026-08
```

内部三步：
1. 导入报名表 → `registrations`（报名时间，自动推算 = 2026-07）
2. 拉取 CWL 星数 → `results` 表（报名时间，自动推算 = 2026-07）
3. 编排名单 + 升降级 → 腾讯在线文档（联赛时间 = 2026-08）

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
register_and_arrange.sh 2026-08          ← 用户参数：联赛时间
  │
  ├─ REG_PERIOD = 2026-07                ← 自动推算：联赛-1
  │
  ├─ [1] import-reg --period 2026-07     ← 报名时间
  │       registrations.period = 2026-07
  │
  ├─ [2] fetch_cwl_data.py --period 2026-07 ← 报名时间
  │       → COC API 拉 7月 CWL → JSON
  │       → results.period = 2026-07
  │
  └─ [3] arrange --period 2026-08        ← 联赛时间
          → 读 registrations(2026-07) + results(2026-07)
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
