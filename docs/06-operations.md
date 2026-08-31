# 06 — 运维手册

> 月度循环、脚本说明、数据目录

---

## 一、月度循环时间线

| 频率 | 操作 | 任务 |
|------|------|------|
| 每 6 小时 | COC API 同步成员（自动） | `scheduler.py` → `coc_sync` |
| 每天 | 拉取部落战数据（自动） | `scheduler.py` → `war_results` |
| 每 30 分钟 | 同步互刷统计数据（自动） | `scheduler.py` → `farm_stats` |
| 每月 12 号 | 拉取 CWL 战绩（自动） | `scheduler.py` → `cwl` |
| 每月底 | 报名导入 → 编排+升降级 → 发布 | `register_and_arrange.sh` |
| 日常 | 查看/管理调度任务 | `scheduler.py --list` 等 |

> 周期任务统一由 `scripts/scheduler.py`（systemd 服务 `sky-scheduler`）接管，详见 [`15-scheduler.md`](./15-scheduler.md) 与 [`deploy/README.md`](../deploy/README.md)。旧的 `sky-sync-*.timer` + `manage-cron.sh` 方案已废弃。

---

## 二、register_and_arrange.sh（报名一体化入口）

报名导入按目标联赛月份作为完整快照处理：导入前仅清理
`registrations` 中该月份的旧记录，再写入当前报名表与战营成员，避免已从报名表
移除的账号残留。导入前会检查多个报名昵称是否解析到同一个 COC Tag；发现冲突
会告警并提示人工核对，但不会因此中止整次导入。

**场景**：每月开赛前跑一次，串联"报名导入 → 名单编排"全流程。

### 流程

```
register_and_arrange.sh 2026-08
  │
  ├─ [1] import-reg --period 2026-08
  │     腾讯文档报名表 → registrations(period=2026-08)
  │
  ├─ [2] fetch_cwl_data.py --period 2026-07
  │     COC API → league_results + results（双写）
  │
  └─ [3] arrange --period 2026-08
        → 读 registrations(2026-08) + league_results(2026-07) + league_teams(2026-07)
        → 基准重建（阶段0~6）+ 贪心填充（阶段7~9）
        → 导出腾讯文档 "名单_2026-08"
```

### 编排流程（v3.0）

```
arrange(period)
  ├─ _write_league_teams() 幂等写入当月配置
  ├─ _fetch_clan_info() 从 COC API 获取部落名和首领
  ├─ _load_accounts() 加载报名 + 注入分数/奖杯
  ├─ sort_accounts() 分组+排序
  ├─ _load_combat_star_data() 从 league_results 读星数
  ├─ _load_prev_combat_from_results() 从 league_results 读上月名单
  ├─ _load_prev_teams_config() 从 league_teams 读上月配置
  ├─ build_final_list() 基准重建+升降级（阶段0~6）
  ├─ build_teams() 贪心填充+白名单+管理员（阶段7~9）
  ├─ 构建 ordered_with_team + 注入 movement 标识
  ├─ 回写 team_name → registrations
  └─ arrange_and_export() 导出 Excel（Part1-4）
```

### 参数与环境变量

| 参数 | 来源 | 说明 |
|------|------|------|
| `PERIOD` | 命令行 `$1` 或 `LEAGUE_PERIOD` | 月份 `YYYY-MM`，含格式校验 |
| `REG_DOC_FILE_ID` | `.env` 必填 | 报名表在线文档 fileId |
| `ROSTER_DOC_FILE_ID` | `.env` 必填 | 名单写入在线文档 fileId |
| `REG_SHEET` | `.env` 可选 | 报名子表名；留空自动推算 |
| `ROSTER_SHEET` | `.env` 可选 | 名单写入子表名；默认 `名单_<period>` |

### 设计要点

- `set -euo pipefail` 严格错误处理
- 所有凭证从 `.env` 加载
- 第 [1] 步 `coc-sync` 当前已注释（战营成员变化不频繁）
- 报名子表名自动推算：`YYYYMMDD-YYYYMMDD（收集结果）`
- **排除名单 `EXCLUDED_CAMP_NAMES`** 在导入阶段 + 排序阶段双阶段生效

### 每月完整流程（以 8 月联赛为例）

```bash
# 一站式（推荐）
scripts/register_and_arrange.sh 2026-08

# 或分步执行：
# 1) 拉上月 CWL 战绩（CWL 月 = 联赛-1）
python scripts/fetch_cwl_data.py --period 2026-07

# 2) 导入报名表（联赛月份）
python cli.py import-reg 报名表.xlsx --period 2026-08

# 3) 编排名单（联赛月份）
python cli.py arrange --period 2026-08 -o 2026-08名单.xlsx
```

---

## 三、sync_and_export.sh（长期维护：COC 同步 → 导出档案）

**当前状态**：步骤 [1]（COC 同步成员）已由调度器任务 `coc_sync` 自动执行（每 6 小时）。如需导出到腾讯文档（步骤 [2]），需单独手动执行。

### 流程

```
[1] COC API → player 数据库（建档 / 更新 / 退部对账）
[2] player 数据库 → 腾讯在线文档（导出玩家档案）
```

### 对应 CLI 命令

| 步骤 | 命令 | 对应代码 | 是否自动化 |
|------|------|---------|-----------|
| [1] | `python cli.py coc-sync` | `coc_sync/service.py` → `player/service.py` | 是（调度器 `coc_sync` 任务） |
| [2] | `python cli.py player-export --to tencent -o <fileId>` | `player/exporter.py` | 否（手动触发） |

> 调度任务的详细管理方式（状态查看、手动执行、日志查询、重启等）请参见 [`15-scheduler.md`](./15-scheduler.md) 与 [`deploy/README.md`](../deploy/README.md)。

---

## 四、fetch_cwl_data.py（CWL 战绩拉取）

v2.4 新增，合并拉取+导入+回退。

**功能**：
- 对 6 支实战队伍调用 leaguegroup API 获取 warTag
- 逐场拉明细 → 存 JSON
- 导入 results 表（双写到 league_results + results）
- API 失败自动回退到本地 JSON
- 按队伍级缓存（<2h 跳过）
- `--period` 为 CWL 实际发生月，`--fetch-only` 仅拉 JSON

## 五、发布脚本

### publish_to_results.sh（v2.6）

发布 Part4 网格到公示文档：

```bash
python cli.py publish-results --period 2026-08
```

需 `registrations` 表已有编排数据。前 20 行固定文字硬编码，Part4 复用 `arrange()` 结果保证一致性。

---

## 六、数据目录结构

```
data/
├── league.db                    # SQLite 主数据库
├── cwl_202607/                  # CWL 战绩 JSON 缓存（兜底用）
│   ├── 0_泰坦二.json
│   └── ...
```

---

## 七、公共环境变量加载器 `load_env.sh`

被其它脚本 `source` 引用，从项目根 `.env` 安全读取凭证：

- **安全解析**：逐行读取 `KEY=VALUE`，不使用 `source .env`（防注入）
- **环境变量优先**：已 export 的变量优先，不被 .env 覆盖
- **Key 合法性校验**：仅允许 `[A-Za-z_][A-Za-z0-9_]*` 格式
- **兼容 CRLF**：自动去除 `\r`
- 加载失败（.env 不存在）直接报错退出

---

## 九、凭证管理约定

- 所有凭证（`COC_API_TOKEN` / `TENCENT_DOC_ACCESS_TOKEN` / `TENCENT_DOC_CLIENT_ID` / `TENCENT_DOC_OPEN_ID` / 文档 fileId）**只放 `.env`，不写进脚本、不提交仓库**
- 首次使用：`cp .env.example .env` 然后填入真实凭证
- 腾讯文档 `access_token` 约 30 天过期，到期需手动更新
- 调试时可临时 `export` 覆盖 .env 中的值

---

## 十、CLI 命令参考

| 命令 | 说明 | period 语义 |
|------|------|------------|
| `import-reg` | 导入报名表 → registrations | 联赛月份 |
| `arrange` | 编排名单 + 导出 Excel | 联赛月份 |
| `publish-results` | 发布 Part4 到公示文档 | 联赛月份 |
| `import-result` | 导入战绩 → results | 联赛月份 |
| `coc-sync` | COC API 同步 → accounts | — |
| `player-export` | 导出玩家档案 | — |
| `accounts` | 查看账号列表 | — |
| `reset-db` | 清空数据库 | — |

---

## 十一、period 语义总结

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份 | `--period 2026-08` |
| `import-result` | 联赛月份 | `--period 2026-08` |
| `fetch_cwl_data.py` | CWL 实际发生月 | `--period 2026-07` |
| `arrange` | 联赛月份 | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛月份 | `2026-08` |

> `registrations.period` = 联赛月份，`results.period` = CWL/战绩实际发生月，`league_teams.period` = 联赛月份，`league_results.period` = CWL 实际发生月。
> 编排 N 月联赛时：读 `registrations(N)` + `league_results(N-1)` + `league_teams(N-1)`。

---

## 十二、月度操作 Checklist

### 每月开赛前（月底）

- [ ] 确认 `coc-sync` 已执行（保持 accounts 数据最新）
- [ ] 确认报名收集表已关闭，子表已生成
- [ ] 检查 `.env` 中 `REG_DOC_FILE_ID`、`ROSTER_DOC_FILE_ID` 已配置
- [ ] 检查腾讯文档 access_token 未过期（30 天有效期）
- [ ] 检查 `EXCLUDED_CAMP_NAMES` 排除名单是否需要更新
- [ ] 检查 `TEAMS` 配置是否为本月最新（队伍数、容量、reserved_slots）
- [ ] 检查 `BLACK_LIST` 和 `WHITE_LIST` 是否需要更新

### 执行流程

- [ ] 运行 `register_and_arrange.sh 2026-08`
- [ ] 检查 stderr 输出无异常告警（去重告警、未知账号告警）
- [ ] 打开腾讯文档"名单_2026-08" sheet 核对：
  - Part1 排序名单顺序合理
  - Part2 队伍分配人数正确
  - Part3 缺失老兵列表准确
  - Part4 网格排布整齐
- [ ] 确认升降级日志合理（无意外大幅波动）
- [ ] 运行 `publish_to_results.sh 2026-08` 发布到公示文档

### 每月 CWL 结束后（7号）

- [ ] 确认 COC API token 未过期
- [ ] 运行 `fetch_cwl_data.sh --period 2026-08` 拉取战绩
- [ ] 检查 `data/cwl_202608/` 目录下 JSON 文件齐全
- [ ] 确认 `league_results` 表数据已写入

### 日常维护

- [ ] 确认调度器正常运行：`sudo systemctl status sky-scheduler`
- [ ] 确认各任务状态：`venv/bin/python scripts/scheduler.py --list`
- [ ] 检查退部对账统计（退部人数是否异常）
- [ ] 腾讯文档 access_token 到期前 3 天续期
- [ ] 定期备份 `data/league.db`
- [ ] 修改调度相关代码后重启：`sudo systemctl restart sky-scheduler`

---

## 十三、异常场景处理

### COC API 调用失败

| 场景 | 影响 | 处理 |
|------|------|------|
| `coc-sync` 单部落失败 | 该部落成员本次不更新 | `FAIL_FAST` 隔离，其他部落正常；退部对账跳过失败部落 |
| `fetch_cwl_data.py` API 失败 | 无法拉取星数 | 自动回退到本地 JSON 缓存；全部失败则编排时自动跳过升降级 |
| `fetch_cwl_data.py` 部分队伍失败 | 缺星数队伍不参与升降级 | 相邻两队都成功才参与升降级配对 |

### 报名数据异常

| 场景 | 处理 |
|------|------|
| 报名表缺 `account_name` 列 | 该行跳过，不影响其他行 |
| 同昵称多次提交 | `_dedup_latest()` 按 `submit_time` 保留最新，stderr 告警 |
| 主号列为空 | `_fill_player_name_forward()` 前向填充兜底 |
| 战营成员未报名 | `_merge_camp()` 自动纳入（`match_value=None`） |
| 报名昵称无法反查 COC Tag | `player_tag` 留空，排序得 0 分 |

### 编排异常

| 场景 | 处理 |
|------|------|
| 冷启动（无上月数据） | 名单1 为空，全部由当月新人构成 |
| 无星数数据 | 跳过升降级，名单1 直接展开 |
| 本月队伍数变化 | 贪心填充自然消化：队多不满员，队少溢出入壳子 |
| 白名单人员未报名 | 强制插入到指定队伍开头 |
| 白名单超员 | 连锁后移到下一队 |
| 黑名单命中 | 阶段0 从所有数据源排除，记录到 Part3 |

### 脚本运行异常

| 场景 | 处理 |
|------|------|
| `.env` 文件不存在 | `load_env.sh` 报错退出 |
| `--period` 格式非法 | `register_and_arrange.sh` 格式校验，非法报错退出 |
| 导入 0 条报名数据 | 当前不校验，会继续生成空名单（建议加校验） |
| 腾讯文档 API 调用失败 | 命令报错退出（`set -e`） |

---

## 十四、常见问题排查

### 战营成员没出现在名单中

1. 检查 `EXCLUDED_CAMP_NAMES` 是否误排除
2. 检查 `coc-sync` 是否已执行（`accounts.clan_tag = '#2QQ'` 才有战营成员）
3. 检查该成员是否退部（`membership_status = left`）

### 排序结果与预期不符

1. 确认 `history_score` 当前恒为 0，排序实际只看匹配值
2. 战营账号按奖杯排序（非综合分）
3. 检查 `match_value` 是否正确导入（报名表列名是否被关键词命中）

### 升降级未生效

1. 确认上月 CWL 战绩已拉取（`fetch_cwl_data.py`）
2. 确认 `league_results` 表中有 `total_stars` 数据
3. 新人无星数数据，不参与升降级

### 腾讯文档写入失败

1. 确认 access_token 未过期（30 天有效期）
2. 确认 `fileId` 正确且当前用户有写入权限
3. 确认 sheet 名不包含非法字符
