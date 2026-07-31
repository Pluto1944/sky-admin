# Part 4：联赛名单排布（备份留底 + 公示发布）设计文档

> 日期: 2026-07-31  
> 版本: v2.0
> 关联: `roster.py`

---

## 1. 背景与目标

当前 `arrange_and_export` 输出一个 sheet（Part 1-3：完整排序 + 队伍分组 + 缺失情况），
但缺少一份**横向网格排布**的备份留底，类似人工在腾讯文档里"一队一区块"的手工排版。

**目标**：
1. 在 `arrange` 命令执行时，于 Part 3 之后同一 sheet 内追加 Part 4，作为备份留底。
2. 通过 `publish-results` 命令将 Part4 网格发布到公示文档，前 20 行固定文字硬编码，Part4 复用 `arrange()` 结果保证一致性。

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

### 2.1 公示发布数据流（v2.0 新增）

```
publish_part4_to_doc(period, publish_doc_id)
  │
  ├─ self.arrange(period)  → ordered, team_results, movements, star_data
  │     （与 arrange_and_export 走完全相同的排序/填充/升降级）
  │
  ├─ _build_part4_grid(team_results) → grid (5 列)
  │
  ├─ PUBLISH_FIXED_ROWS (前 20 行固定文字) + grid → combined_rows
  │
  └─ _write_publish_sheet(publish_doc_id, sheet_name, combined_rows)
```

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

### 4.1 `roster.py` — `_build_part4_grid` 方法

```python
def _build_part4_grid(self, team_results: list[dict]) -> tuple[list[list[str]], list[int]]:
    """构建 Part4 联赛名单排布网格。

    返回 (grid, title_row_indices):
      - grid: list[list[str]]，每行 5 列
      - title_row_indices: 抬头行在 grid 中的行索引列表
    """
    grid: list[list[str]] = []
    title_indices: list[int] = []

    for i, tr in enumerate(team_results):
        cat = "实战" if tr["category"] == LEAGUE_COMBAT else "壳子"
        title_indices.append(len(grid))
        # 抬头拆成 3 列：队伍信息 | clan_tag | 空 | 空 | 管理
        cap_info = f"{tr['filled_count']}/{tr['member_count']}"
        col1 = f"{cat}: {tr['team_name']} {cap_info}"
        col2 = tr.get("clan_tag", "")
        col3 = f"管理:{tr.get('manager', '')}"
        grid.append([col1, col2, "", "", col3])

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

    return grid, title_indices
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

### 4.3 `roster.py` — `PUBLISH_FIXED_ROWS` 类常量（v2.0 新增）

公示文档前 20 行固定文字直接硬编码为类常量，不再从模板 sheet 读取：

```python
PUBLISH_FIXED_ROWS: list[list[str]] = [
    ["苍穹联赛报名", "", "", "", ""],
    ["联赛开始，各部落暗号为999，加盟部落暗号找自己首领", "", "", "", ""],
    # ... 共 20 行
]
```

### 4.4 `roster.py` — `publish_part4_to_doc` 方法（v2.0 新增）

```python
def publish_part4_to_doc(self, period: str, publish_doc_id: str) -> str:
    # 1. 走完整 arrange() 流程
    _ordered, team_results, _movements, _star_data = self.arrange(period)
    # 2. 生成 Part4 网格
    grid, _title_indices = self._build_part4_grid(team_results)
    # 3. 拼接固定文字 + 网格
    combined_rows = self.PUBLISH_FIXED_ROWS + grid
    # 4. 写入
    self._write_publish_sheet(publish_doc_id, sheet_name, combined_rows, ...)
```

### 4.5 `cli.py` — `publish-results` 命令（v2.0 新增）

```python
p_pub = sub.add_parser("publish-results", ...)
p_pub.add_argument("--period", required=True)
p_pub.add_argument("--file-id", default=None)
```

---

## 5. 影响范围

| 文件 | 变更类型 |
|------|---------|
| `modules/cwl_registration/roster.py` | 新增 `_build_part4_grid`、`publish_part4_to_doc`、`PUBLISH_FIXED_ROWS`、`_write_publish_sheet`；`arrange_and_export` 中 Part 3 后追加 Part 4 |
| `cli.py` | 新增 `publish-results` 命令 |
| `scripts/publish_to_results.sh` | 新增发布公示脚本 |
| `docs/roster_part4_design.md` | 本文档（更新至 v2.0） |

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
