# Part 4：联赛名单排布（备份留底）设计文档

> 日期: 2026-07-30  
> 关联: `roster.py`

---

## 1. 背景与目标

当前 `arrange_and_export` 输出一个 sheet（Part 1-3：完整排序 + 队伍分组 + 缺失情况），
但缺少一份**横向网格排布**的备份留底，类似人工在腾讯文档里"一队一区块"的手工排版。

**目标**：在 `arrange` 命令执行时，于 Part 3 之后同一 sheet 内追加 Part 4，作为备份留底。

---

## 2. 数据流

```
arrange_and_export(period, target, ...)
  │
  ├─ self.arrange(period, ...)  → ordered, team_results, movements, star_data
  │
  ├─ Part 1: 完整排序名单  ─┐
  ├─ Part 2: 队伍分组      ─┤  拼接为 combined_rows
  ├─ Part 3: 缺失情况      ─┤
  ├─ Part 4: 联赛名单排布   ─┘
  │
  └─ write_sheet(target, combined_rows, sheet=sheet_name)
```

Part 4 与 Part 1-3 在同一 sheet 内，复用同一次 `arrange()` 结果。

---

## 3. 布局规则

### 3.1 整体结构（单 sheet 内从上到下）

```
┌─ Part 1: 完整排序名单 ──────────────────────────┐
│  rank_order | league_type | team_name | ...       │
│  (N 行数据)                                       │
├─ 空白分隔 ──────────────────────────────────────┤
│  === 战队分配 ===                                │
├─ Part 2: 队伍分组 ──────────────────────────────┤
│  实战: 泰坦二 #2QQ ...                           │
│    (成员逐行)                                     │
│  ...                                              │
├─ Part 3: 缺失情况 ──────────────────────────────┤
│  === 缺席老兵（共N人...）===                      │
│  [转壳] / [未报名] / [离开]                       │
├─ 空白分隔 ──────────────────────────────────────┤
│  === 联赛名单排布（备份留底） ===                  │
├─ Part 4: 网格排布 ──────────────────────────────┤
│  实战: 泰坦二 #2QQ 管理:xxx 满员:15/15  │  │  │  │  │
│  player1   │ player2   │ player3   │ player4   │ player5   │
│  player6   │ player7   │ player8   │ player9   │ player10  │
│  player11  │ player12  │ player13  │ player14  │ player15  │
│  (空行)     │           │           │           │           │
│  实战: 冠一 一队 #2GGGGGGG 管理:yyy 满员:15/15│  │  │  │
│  ...                                              │
│  (空行)                                           │
│  壳子: 大一 #AAAAA 管理:aaa 满员:30/30 │  │  │  │  │
│  p1 600    │ p2 610    │ p3 580    │ p4 590    │ p5 600    │
│  ...                                              │
└──────────────────────────────────────────────────┘
```

### 3.2 详细规则

| # | 规则 | 说明 |
|---|------|------|
| 1 | **队伍顺序** | 按 `team_results` 原始顺序（实战在前、壳子在后），从上到下排布 |
| 2 | **抬头行** | `{cat}: {team_name} {clan_tag} 管理:{manager} 满员:{filled}/{member_count}` |
| 3 | **每行 5 格** | 固定 5 列，15 人队伍 3 行，30 人队伍 6 行；不足 5 人末尾留空 |
| 4 | **实战队伍** | 单元格只显示 `account_name` |
| 5 | **壳子队伍** | 单元格显示 `{account_name} {match_value}`（match_value 取整，空格分隔） |
| 6 | **队伍间分隔** | 一空行 |
| 7 | **列映射** | Part 4 使用 `ARRANGEMENT_OUTPUT_HEADERS` 前 5 列（`rank_order`, `league_type`, `team_name`, `movement`, `player_tag`），其余 7 列留空 |

### 3.3 壳子 `match_value` 取整

```python
int(m.get("match_value") or 0)
```

---

## 4. 代码变更

### 4.1 `roster.py` — 新增 `_build_part4_grid` 方法

```python
def _build_part4_grid(self, team_results: list[dict]) -> list[list[str]]:
    """构建 Part4 联赛名单排布网格（备份留底）。

    返回 list[list[str]]，每行 5 列（不足补齐空串）。
    """
    grid: list[list[str]] = []

    for i, tr in enumerate(team_results):
        cat = "实战" if tr["category"] == LEAGUE_COMBAT else "壳子"
        title = (
            f"{cat}: {tr['team_name']} "
            f"{tr.get('clan_tag', '')} "
            f"管理:{tr.get('manager', '')} "
            f"满员:{tr['filled_count']}/{tr['member_count']}"
        )
        grid.append([title, "", "", "", ""])

        members = tr["members"]
        is_shell = tr["category"] == LEAGUE_SHELL
        for j in range(0, len(members), 5):
            chunk = members[j:j + 5]
            row: list[str] = []
            for m in chunk:
                name = m.get("account_name", "")
                if is_shell:
                    mv = int(m.get("match_value") or 0)
                    row.append(f"{name} {mv}")
                else:
                    row.append(name)
            row.extend([""] * (5 - len(row)))
            grid.append(row)

        if i < len(team_results) - 1:
            grid.append(["", "", "", "", ""])

    return grid
```

### 4.2 `roster.py` — 修改 `arrange_and_export`

在 Part 3 末尾（L533 `combined_rows.append({h: None ...})` 之后）插入 Part 4 拼接逻辑：

```python
                        # 队伍之间空行
                        combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

        # ===== Part 4: 联赛名单排布（备份留底） =====
        _PART4_COLS = ARRANGEMENT_OUTPUT_HEADERS[:5]
        combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})
        combined_rows.append({
            **{h: None for h in ARRANGEMENT_OUTPUT_HEADERS},
            "rank_order": "=== 联赛名单排布（备份留底） ===",
        })

        grid = self._build_part4_grid(team_results)
        for row in grid:
            combined_rows.append({
                **{h: "" for h in ARRANGEMENT_OUTPUT_HEADERS},
                **{_PART4_COLS[k]: row[k] for k in range(min(5, len(row)))},
            })

        sheet_name = sheet or f"名单_{period}"
```

### 4.3 无需改动的文件

`cli.py`、`register_and_arrange.sh`、`.env` — **零改动**。

---

## 5. 影响范围

| 文件 | 变更类型 |
|------|---------|
| `modules/cwl_registration/roster.py` | 新增 `_build_part4_grid` 方法；`arrange_and_export` 中 Part 3 后追加 Part 4 |
| `docs/roster_part4_design.md` | 本文档（新增） |

无破坏性变更。

---

## 6. 测试要点

| # | 场景 | 预期 |
|---|------|------|
| 1 | 正常编排，有 CWL 星数 | Part 1-4 均在同一 sheet 输出 |
| 2 | 冷启动（无星数） | Part 4 正常产出（不依赖 star_data） |
| 3 | 15 人实战队 | 1 抬头 + 3 行成员（每行 5 人） |
| 4 | 30 人队伍 | 1 抬头 + 6 行成员 |
| 5 | 壳子队伍 | 单元格含 `名称 匹配值`，匹配值为整数 |
| 6 | 实战队伍 | 单元格只含 `名称` |
| 7 | 不足 5 人队伍 | 末尾单元格为空 |
