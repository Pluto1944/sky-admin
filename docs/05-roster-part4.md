# 05 — Part4 联赛名单排布（备份留底 + 公示发布）

> 版本：v2.2
> 日期：2026-08-01
> 关联代码：`roster.py`

---

## 一、背景与目标

当前 `arrange_and_export` 输出一个 sheet（Part 1-3），但缺少一份**横向网格排布**的备份留底。

**目标**：
1. 在 `arrange` 命令执行时，于 Part 3 之后同一 sheet 内追加 Part 4
2. 通过 `publish-results` 命令将 Part4 网格发布到公示文档

---

## 二、数据流

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

**Part4 独立 5 列写入**，不经过 `ARRANGEMENT_OUTPUT_HEADERS` 的 dict 映射，避免中间空列。

### 公示发布数据流

```
publish_part4_to_doc(period, publish_doc_id)
  ├─ self.arrange(period)  → team_results
  ├─ _build_part4_grid(team_results) → grid (5 列)
  ├─ PUBLISH_FIXED_ROWS (前 20 行固定文字) + grid → combined_rows
  └─ _write_publish_sheet(publish_doc_id, sheet_name, combined_rows)
```

---

## 三、布局规则

### 整体结构（单 sheet 内从上到下）

```
┌─ Part 1: 完整排序名单 ──────────────────────────┐
│  rank_order | league_type | cur_team | ...        │
├─ Part 2: 队伍分组 ──────────────────────────────┤
├─ Part 3: 缺失情况 ──────────────────────────────┤
├─ Part 4: 网格排布（5 列独立写入）────────────────┤
│  === 联赛名单排布（备份留底） ===                  │
│  实战: 泰坦二 15/15  #2QQ  泰坦二  首领:xxx  管理:yyy 开战/捐兵给一份额外 │
│  player1   │ player2   │ player3   │ player4   │ player5   │
│  player6   │ player7   │ player8   │ player9   │ player10  │
│  player11  │ player12  │ player13  │ player14  │ player15  │
│  (空行)     │           │           │           │           │
│  实战: 冠一 一队 15/15  #2GGGGGGG  冠一  首领:zzz  管理:www 开战/捐兵给一份额外 │
│  ...                                              │
│  (空行)                                           │
│  壳子: 大一 30/30  #AAAAA  大一  首领:aaa  管理:bbb 开战/捐兵给一份额外 │
│  p1 600    │ p2 610    │ p3 580    │ p4 590    │ p5 600    │
│  ...                                              │
└──────────────────────────────────────────────────┘
```

### 详细规则

| # | 规则 | 说明 |
|---|------|------|
| 1 | **队伍顺序** | 按 `team_results` 原始顺序（实战在前、壳子在后） |
| 2 | **抬头行** | col1=队伍信息、col2=clan_tag、col3=部落名（COC API）、col4=首领（COC API）、col5=管理信息 |
| 3 | **每行 5 格** | 15 人队伍 3 行，30 人队伍 6 行 |
| 4 | **实战队伍** | 单元格只显示 `account_name` |
| 5 | **壳子队伍** | 单元格显示 `{account_name} {match_value}`（取整） |
| 6 | **队伍间分隔** | 一空行 |
| 7 | **写入方式** | Part4 独立 5 列写入，不经过 header dict 映射 |
| 8 | **部落信息缓存** | `_fetch_clan_info()` 批量获取，带缓存 |

### 壳子 `match_value` 取整

```python
int(m.get("match_value") or 0)
```

---

## 四、代码变更

### `_build_part4_grid` 方法

```python
def _build_part4_grid(self, team_results: list[dict]) -> tuple[list[list[str]], list[int]]:
    """构建 Part4 联赛名单排布网格。
    返回 (grid, title_row_indices): grid 每行 5 列
    """
    # 先收集所有 clan_tag，批量获取部落名称和首领
    all_tags = {tr.get("clan_tag", "") for tr in team_results}
    all_tags.discard("")
    clan_info = self._fetch_clan_info(all_tags)

    grid: list[list[str]] = []
    title_indices: list[int] = []

    for tr in team_results:
        cat = "实战" if tr["category"] == LEAGUE_COMBAT else "壳子"
        title_indices.append(len(grid))
        # 抬头 5 列
        cap_info = f"{tr['filled_count']}/{tr['member_count']}"
        col1 = f"{cat}: {tr['team_name']} {cap_info}"
        col2 = tr.get("clan_tag", "")
        clan_name, leader_name = clan_info.get(col2, ("", ""))
        col3 = clan_name
        col4 = f"首领:{leader_name}" if leader_name else ""
        col5 = f"管理:{tr.get('manager', '')} 开战/捐兵给一份额外"
        grid.append([col1, col2, col3, col4, col5])
        # 成员行：每行 5 人，实战只显示名称，壳子显示名称+匹配值
        ...
```

### `PUBLISH_FIXED_ROWS` 类常量

公示文档前 20 行固定文字直接硬编码（5 列）：

```python
PUBLISH_FIXED_ROWS: list[list[str]] = [
    ["苍穹联赛报名", "", "", "", ""],
    # ... 共 20 行
]
```

### `publish_part4_to_doc` 方法

```python
def publish_part4_to_doc(self, period: str, publish_doc_id: str) -> str:
    _ordered, team_results, _movements, _star_data = self.arrange(period)
    grid, _title_indices = self._build_part4_grid(team_results)
    combined_rows = self.PUBLISH_FIXED_ROWS + grid
    self._write_publish_sheet(publish_doc_id, sheet_name, combined_rows, ...)
```

### `ARRANGEMENT_OUTPUT_HEADERS`

已删除 `team_name` 列（被 `cur_team`/`prev_team` 替代）：

```python
ARRANGEMENT_OUTPUT_HEADERS = [
    "rank_order", "league_type", "cur_team", "prev_team", "movement",
    "player_tag", "account_name", "player_name", "account_type",
    "prev_rank", "trophies", "match_value", "history_score",
]
```

---

## 五、影响范围

| 文件 | 变更类型 |
|------|---------|
| `roster.py` | `_build_part4_grid`、`_append_part4_to_sheet`、`publish_part4_to_doc`、`PUBLISH_FIXED_ROWS`、`_fetch_clan_info`；Part4 独立写入 + 标题行增加部落信息 |
| `config.py` | `ARRANGEMENT_OUTPUT_HEADERS` 删除 `team_name` |
| `cli.py` | 新增 `publish-results` 命令 |
| `scripts/publish_to_results.sh` | 新增发布公示脚本 |

---

## 六、测试要点

| # | 场景 | 预期 |
|---|------|------|
| 1 | 正常编排，有 CWL 星数 | Part 1-4 均在同一 sheet 输出 |
| 2 | 冷启动（无星数） | Part 4 正常产出 |
| 3 | 15 人实战队 | 1 抬头 + 3 行成员（每行 5 人） |
| 4 | 30 人队伍 | 1 抬头 + 6 行成员 |
| 5 | 壳子队伍 | 单元格含 `名称 匹配值`，匹配值为整数 |
| 6 | 实战队伍 | 单元格只含 `名称` |
| 7 | 不足 5 人队伍 | 末尾单元格为空 |
| 8 | Part4 抬头行 5 列完整 | col1=队伍信息、col2=clan_tag、col3=部落名、col4=首领、col5=管理 |
| 9 | COC API 查询失败 | 部落名/首领为空，不影响整体输出 |
| 10 | tag 格式非法 | 跳过 API 查询，不报 404 |
