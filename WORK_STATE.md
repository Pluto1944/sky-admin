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
| `import-reg` | 报名时间（报名表提交月） | `--period 2026-07` |
| `fetch_cwl_data.py` | 报名时间（CWL 实际发生月） | `--period 2026-07` |
| `arrange` | 联赛时间（安排哪月联赛） | `--period 2026-08` |
| `register_and_arrange.sh` | 联赛时间（一站式入口） | `2026-08` |

规则：**读数据的接口用实际发生月，安排联赛的接口用联赛所在月。**

## 全链路逻辑

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

## 操作命令

```bash
# 一站式（推荐）
scripts/register_and_arrange.sh 2026-08

# 分步执行
python scripts/fetch_cwl_data.py --period 2026-07        # 拉星数
python cli.py import-registrations 报名表.xlsx --period 2026-07  # 导入报名
python cli.py arrange --period 2026-08 -o 2026-08名单.xlsx       # 编排
```

## 脚本体系

| 脚本 | 用途 | period |
|------|------|--------|
| `register_and_arrange.sh` | 一键全流程 | 联赛时间 |
| `fetch_cwl_data.py` | 拉取+导入DB+回退 | 报名时间 |
| `fetch_cwl_data.sh` | 仅拉JSON | 报名时间 |

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
