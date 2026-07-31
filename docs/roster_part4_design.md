# Part 4：联赛名单排布（备份留底 + 公示发布）设计文档

> 日期: 2026-07-31  
> 版本: v2.1
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
  │
  ├─ write_sheet(target, combined_rows, sheet=sheet_name)  ← Part1-3
  │
  └─ _append_part4_to_sheet(target, sheet_name, grid)  ← Part4 独立追加
```

Part 4 与 Part 1-3 在同一 sheet 内，复用同一次 `arrange()` 结果。
**Part4 不再通过 dict 映射写入 combined_rows**，而是先让 write_sheet 预留空行占位，
再用 `updateRangeRequest` 覆盖写入 5 列 grid，避免受 `ARRANGEMENT_OUTPUT_HEADERS` 中多余列影响。

### 2.1 公示发布数据流

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
│  rank_order | league_type | cur_team | ...        │
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
├─ Part 4: 网格排布（5 列独立写入）────────────────┤
│  === 联赛名单排布（备份留底） ===                  │
│  实战: 泰坦二 15/15   #2QQ             管理:xxx  │
│  player1   │ player2   │ player3   │ player4   │ player5   │
│  player6   │ player7   │ player8   │ player9   │ player10  │
│  player11  │ player12  │ player13  │ player14  │ player15  │
│  (空行)     │           │           │           │           │
│  实战: 冠一 一队 15/15  #2GGGGGGG       管理:yyy│
│  ...                                              │
│  (空行)                                           │
│  壳子: 大一 30/30   #AAAAA             管理:aaa  │
│  p1 600    │ p2 610    │ p3 580    │ p4 590    │ p5 600    │
│  ...                                              │
└──────────────────────────────────────────────────┘
```

### 3.2 详细规则

| # | 规则 | 说明 |
|---|------|------|
| 1 | **队伍顺序** | 按 `team_results` 原始顺序（实战在前、壳子在后），从上到下排布 |
| 2 | **抬头行** | `{cat}: {team_name} {cap_info}` 占第 1 列，`clan_tag` 占第 2 列，`管理:{manager}` 占第 5 列，第 3、4 列留空 |
| 3 | **每行 5 格** | 固定 5 列，15 人队伍 3 行，30 人队伍 6 行；不足 5 人末尾留空 |
| 4 | **实战队伍** | 单元格只显示 `account_name` |
| 5 | **壳子队伍** | 单元格显示 `{account_name} {match_value}`（match_value 取整，空格分隔） |
| 6 | **队伍间分隔** | 一空行 |
| 7 | **写入方式** | Part4 独立 5 列写入，不经过 `ARRANGEMENT_OUTPUT_HEADERS` 的 dict 映射，避免 `cur_team`/`prev_team` 等列产生中间空列 |

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
        # 抬头 5 列：队伍信息 | clan_tag | (空) | (空) | 管理
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

### 4.2 `roster.py` — 修改 `arrange_and_export`（v2.1）

Part4 独立写入，不混入 `combined_rows`：

```python
        # ===== Part 4: 联赛名单排布（备份留底） =====
        grid, title_indices = self._build_part4_grid(team_results)
        part4_row_count = 2 + len(grid)  # 空行 + 标题 + grid

        # 追加空行占位，让 write_sheet 预留空间
        for _ in range(part4_row_count):
            combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

        sheet_name = sheet or f"名单_{period}"
        self.excel_io.write_sheet(
            target, combined_rows,
            headers=ARRANGEMENT_OUTPUT_HEADERS, sheet=sheet_name,
        )

        # 追加 Part4（5 列 grid，覆盖空行占位）
        self._append_part4_to_sheet(target, sheet_name, grid, title_indices)
```

### 4.3 `roster.py` — `_append_part4_to_sheet` 方法（v2.1 新增）

用 `updateRangeRequest` 从占位行开始覆盖写入 Part4 数据，不删表重建，保持 Part1-3 原有格式不变。

### 4.4 `roster.py` — `PUBLISH_FIXED_ROWS` 类常量

公示文档前 20 行固定文字直接硬编码为类常量（5 列，与 Part4 grid 对齐）：

```python
PUBLISH_FIXED_ROWS: list[list[str]] = [
    ["苍穹联赛报名", "", "", "", ""],
    # ... 共 20 行
]
```

### 4.5 `roster.py` — `publish_part4_to_doc` 方法

```python
def publish_part4_to_doc(self, period: str, publish_doc_id: str) -> str:
    _ordered, team_results, _movements, _star_data = self.arrange(period)
    grid, _title_indices = self._build_part4_grid(team_results)
    combined_rows = self.PUBLISH_FIXED_ROWS + grid
    self._write_publish_sheet(publish_doc_id, sheet_name, combined_rows, ...)
```

### 4.6 `config.py` — `ARRANGEMENT_OUTPUT_HEADERS`（v2.1）

已删除 `team_name` 列（被 `cur_team`/`prev_team` 替代）：

```python
ARRANGEMENT_OUTPUT_HEADERS = [
    "rank_order",
    "league_type",
    "cur_team",         # 当月队伍
    "prev_team",        # 上月队伍
    "movement",         # 升降级标识
    "player_tag",
    "account_name",
    "player_name",
    "account_type",
    "prev_rank",
    "trophies",
    "match_value",
    "history_score",
]
```

### 4.7 `cli.py` — `publish-results` 命令

```python
p_pub = sub.add_parser("publish-results", ...)
p_pub.add_argument("--period", required=True)
p_pub.add_argument("--file-id", default=None)
```

---

## 5. 影响范围

| 文件 | 变更类型 |
|------|---------|
| `modules/cwl_registration/roster.py` | `_build_part4_grid`（管理信息放第 5 列）、`_append_part4_to_sheet`（新增）、`publish_part4_to_doc`、`PUBLISH_FIXED_ROWS`、`_write_publish_sheet`；`arrange_and_export` 中 Part4 独立写入 |
| `modules/cwl_registration/config.py` | `ARRANGEMENT_OUTPUT_HEADERS` 删除 `team_name`，保留 `cur_team`/`prev_team` |
| `cli.py` | 新增 `publish-results` 命令 |
| `scripts/publish_to_results.sh` | 新增发布公示脚本 |
| `docs/roster_part4_design.md` | 本文档（更新至 v2.1） |

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
| 8 | Part4 中间无空列 | 抬头行第 3、4 列为空，第 5 列为管理信息；成员行 5 列名字紧凑 |
