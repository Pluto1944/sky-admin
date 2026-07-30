# 工作状态（2026-07-30）

## 当前进度

- [x] COC API 探测 + 6 队 CWL 数据拉取 + #2QQ 手工补录
- [x] 升降级算法实现（promotion.py，12 单测）
- [x] roster 集成 + 月份语义梳理
- [x] fetch_cwl_data.py 合并拉取+导入+回退+升降级参与总结
- [x] 135 测试全绿
- [x] register_and_arrange.sh 一键全流程
- [x] 文档全面更新 + scripts/README.md 使用文档

## 时间语义（最终版）

| 接口 | period 含义 | 示例 |
|------|------------|------|
| `import-reg` | 联赛月份（报名表为该月联赛报名） | `--period 2026-08` |
| `import-result` | 联赛月份（战绩所属月） | `--period 2026-08` |
| `fetch_cwl_data.py` | CWL 实际发生月（拉哪月传哪月） | `--period 2026-07` |
| `arrange` | 联赛月份（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛月份（一站式入口） | `2026-08` |

规则：**registrations.period = 联赛月份，results.period = CWL/战绩实际发生月。**
编排 N 月联赛时读 registrations(N) + results(N-1)。

## 全链路逻辑

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
| `register_and_arrange.sh` | 一键全流程 | 联赛月份 |
| `fetch_cwl_data.py` | 拉取+导入DB+回退 | CWL 实际发生月 |
| `fetch_cwl_data.sh` | 仅拉JSON | CWL 实际发生月 |

## 升降级参数

```
PROMOTION_RELEGATION_CONFIG = {
  "count": 2, promotion_min_stars: 21, relegation_max_stars: 18
}
```

## 文件清单

### 新增
- modules/cwl_registration/promotion.py
- tests/cwl_registration/test_promotion.py
- scripts/fetch_cwl_data.py + fetch_cwl_data.sh
- scripts/probe_cwl_data.py
- scripts/README.md
- data/cwl_202607/*.json (7 files)

### 修改
- modules/cwl_registration/config.py, roster.py, repository.py
- modules/war_result/repository.py
- modules/player/service.py
- cli.py, tests/cwl_registration/test_roster.py
- scripts/register_and_arrange.sh
- DESIGN.md, CODE_REVIEW.md, docs/promotion_relegation_design.md
