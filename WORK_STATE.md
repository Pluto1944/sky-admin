# 工作状态（2026-08-02）

## 当前进度

- [x] COC API 探测 + 6 队 CWL 数据拉取 + #2QQ 手工补录
- [x] 升降级算法实现（promotion.py，12 单测）
- [x] roster 集成 + 月份语义梳理
- [x] fetch_cwl_data.py 合并拉取+导入+回退+升降级参与总结
- [x] api_client.py 正式添加 get_clan_warlog / get_cwl_war / get_league_group
- [x] 135 测试全绿（15 个测试文件）
- [x] register_and_arrange.sh 一键全流程
- [x] Part4 网格发布：publish-results 命令 + publish_to_results.sh
- [x] **v3.0 基准重建**：baseline_rebuilder.py（阶段0~6）+ team_builder.py（阶段7~9），team_filler.py 已删除
- [x] **league_teams 表**：队伍配置按月快照，替代旧 TEAMS_LAST
- [x] **league_results 表**：联赛战绩结构化存储，双写到旧 results 表
- [x] **cur_team 格式**：`"{team_index} {team_alias} {coc_name}"`
- [x] **team_name 回写格式**：`"{team_index} {team_alias} {coc_name} {clan_tag}"`
- [x] **ARRANGEMENT_OUTPUT_HEADERS**：13 列（含 team_name）
- [x] **管理意愿**：报名表新增 `willing_to_manage` 字段解析与落库
- [x] **管理员三级分配**：config 优先 → 队伍内报名意愿者 → 留空
- [x] **Part4 部落信息**：col3=部落名、col4=首领（通过 COC API 获取）
- [x] **管理员后缀**：col5 管理信息追加"开战/捐兵给一份额外"
- [x] **fetch_cwl_data.py**：不依赖 config.py TEAMS，从 league_teams 表获取队伍信息
- [x] 文档全面更新（所有 docs/ + README + WORK_STATE + scripts/README）

## 时间语义（最终版）

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份（报名表为该月联赛报名） | `--period 2026-08` |
| `import-result` | 联赛月份（战绩所属月） | `--period 2026-08` |
| `fetch_cwl_data.py` | CWL 实际发生月（拉哪月传哪月） | `--period 2026-07` |
| `arrange` | 联赛月份（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛月份（一站式入口） | `2026-08` |

规则：**registrations.period = 联赛月份，results.period = CWL/战绩实际发生月，league_teams.period = 联赛月份，league_results.period = CWL 实际发生月。**
编排 N 月联赛时读 registrations(N) + league_results(N-1) + league_teams(N-1)。

## 全链路逻辑（v3.0）

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
  │       → 查 league_teams(2026-07) 获取队伍信息
  │       → COC API 拉 7月 CWL → league_results + results（双写）
  │
  └─ [3] arrange --period 2026-08        ← 联赛月份
          → 读 registrations(2026-08) + league_results(2026-07) + league_teams(2026-07)
          → build_final_list() 基准重建（阶段0~6，含升降级）
          → build_teams() 贪心填充（阶段7~9）
          → 导出 "名单_2026-08"
```

## 操作命令

```bash
# 一站式（推荐）
scripts/register_and_arrange.sh 2026-08

# 分步执行
python scripts/fetch_cwl_data.py --period 2026-07        # 拉上月 CWL 星数
python cli.py import-reg 报名表.xlsx --period 2026-08    # 导入报名（联赛月份）
python cli.py arrange --period 2026-08 -o 2026-08名单.xlsx       # 编排
```

## 脚本体系

| 脚本 | 用途 | period |
|------|------|--------|
| `register_and_arrange.sh` | 一键全流程（报名+拉取+编排） | 联赛月份 |
| `publish_to_results.sh` | 发布 Part4 到公示文档 | 联赛月份 |
| `fetch_cwl_data.py` | 拉取 CWL 战绩+导入 DB+回退 | CWL 实际发生月 |
| `sync_and_export.sh` | 每日 COC 同步+导出档案 | — |

## 升降级参数

```
PROMOTION_RELEGATION_CONFIG = {
  "count": 2, promotion_min_stars: 21, relegation_max_stars: 18
}
```

## 文件清单

### v3.0 新增
- modules/cwl_registration/baseline_rebuilder.py（阶段 0~6）
- modules/cwl_registration/team_builder.py（阶段 7~9，替代 team_filler.py）
- tests/cwl_registration/test_baseline_rebuilder.py
- tests/cwl_registration/test_team_builder.py
- shared/db/connection.py：league_teams + league_results 表 DDL

### v3.0 删除
- modules/cwl_registration/team_filler.py（已由 team_builder.py 替代）
- TEAMS_LAST 配置（已由 league_teams 表替代）

### v2.x 新增（历史记录）
- modules/cwl_registration/promotion.py
- tests/cwl_registration/test_promotion.py
- scripts/fetch_cwl_data.py
- scripts/README.md
