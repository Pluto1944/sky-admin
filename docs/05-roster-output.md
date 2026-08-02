# 05 — 在线 Excel 输出（Part1-Part4 + 公示发布）

> 版本：v3.0
> 日期：2026-08-02
> 关联代码：`roster.py`、`config/settings.yaml`、`team_builder.py`、`baseline_rebuilder.py`

---

## 一、背景与目标

`arrange_and_export()` 是名单编排的最终输出入口，将编排结果写入腾讯文档的单个 sheet 中，从上到下包含 **4 个部分**。此外，`publish_part4_to_doc()` 提供独立的公示发布能力，将 Part4 网格写入另一个公示文档。

**目标**：
1. Part 1-4 在同一个 sheet 内按序输出，自上而下清晰分层
2. Part4 用独立 5 列写入，避免 Part1-3 的 13 列表头在底部产生多余空白列
3. 公示发布独立于编排工作文档，写入另一个腾讯文档供成员查看

---

## 二、数据流

### 编排输出整体流程

```
arrange_and_export(period, target)
  │
  ├─ self.arrange(period)            # 排序 + 基准重建 + 升降级 + 队伍填充
  │   → ordered, team_results, movements, star_data
  │
  ├─ 构建 combined_rows (dict 列表)   # Part1 + Part2 + Part3
  │
  ├─ write_sheet(target, combined_rows, headers=ARRANGEMENT_OUTPUT_HEADERS)
  │   → 写入 Part1-3 + 空行占位
  │
  └─ _append_part4_to_sheet(target, sheet_name, grid, title_indices)
      → 独立 5 列覆盖写入 Part4
```

### 公示发布数据流

```
publish_part4_to_doc(period, publish_doc_id)
  ├─ self.arrange(period)            → team_results
  ├─ _build_part4_grid(team_results) → grid (5 列)
  ├─ PUBLISH_FIXED_ROWS (前 20 行固定文字) + grid → combined_rows
  └─ _write_publish_sheet(publish_doc_id, sheet_name, combined_rows)
```

---

## 三、输出布局

### 整体结构（单 sheet 内从上到下）

```
┌─ Part 1: 完整排序名单 ──────────────────────────────┐
│  rank_order | league_type | cur_team | prev_team |    │
│  movement | player_tag | account_name | player_name |  │
│  team_name | account_type | trophies |               │
│  match_value | history_score                           │
├─ Part 2: 队伍分组明细 ────────────────────────────────┤
│  === 战队分配 ===                                      │
│  实战: 泰坦二 (冠二) #2QQ 苍穹·天空之城 领队:xxx ...    │
│  成员1 | 成员2 | ...                                   │
│  (空行)                                                │
│  实战: 冠一 一队 15/15  #2GGGGGGG 冠一 首领:zzz ...    │
│  ...                                                   │
├─ Part 3: 离队情况 ────────────────────────────────────┤
│  === 离队情况（共N人）===                              │
│  [实战缺失] N人（上月实战，本月未参加）                  │
│  account_name | player_tag | movement:缺失(N★) | ...   │
│  [黑名单] N人                                          │
│  account_name | player_tag | movement:黑名单            │
├─ Part 4: 网格排布（5 列独立写入）──────────────────────┤
│  === 联赛名单排布（备份留底） ===                       │
│  实战: 泰坦二 15/15  #2QQ  泰坦二  首领:xxx  管理:yyy  │
│  player1   │ player2   │ player3   │ player4   │ player5│
│  player6   │ player7   │ player8   │ player9   │ player10│
│  player11  │ player12  │ player13  │ player14  │ player15│
│  (空行)                                                │
│  壳子: 大一 30/30  #AAAAA  大一  首领:aaa  管理:bbb    │
│  p1 600    │ p2 610    │ p3 580    │ p4 590    │ p5 600 │
│  ...                                                   │
└────────────────────────────────────────────────────────┘
```

---

## 四、Part 1：完整排序名单

**数据来源**：`arrange()` 返回的 `ordered` 列表（排序后含升降级标识的完整名单）

**表头**：`ARRANGEMENT_OUTPUT_HEADERS`（13 列，定义于 `config/settings.yaml`）

```python
ARRANGEMENT_OUTPUT_HEADERS = [
    "rank_order",       # 排序序号
    "league_type",      # 联赛类型
    "cur_team",         # 当月队伍（"index alias coc_name" 拼接）
    "prev_team",        # 上月队伍（"index alias" 拼接）
    "movement",         # 升降级标识（v2.4）↑升级/↓降级/空
    "player_tag",       # 玩家标签
    "account_name",     # 账号名称
    "player_name",      # 玩家名称
    "team_name",        # COC 真实部落名称
    "account_type",     # 账号类型
    "trophies",         # 杯数
    "match_value",      # 匹配值
    "history_score",    # 历史积分
]
```

**构建逻辑**：按表头字段从每个 `ordered` 元素中取值，直接映射为 dict 列表：

```python
combined_rows: list[dict] = [
    {h: item.get(h) for h in ARRANGEMENT_OUTPUT_HEADERS}
    for item in ordered
]
```

---

## 五、Part 2：队伍分组明细

**位置**：Part 1 之后，两空行 + `"=== 战队分配 ==="` 标题行分隔

**数据来源**：`team_results` 列表（每支队伍的分配结果）

**结构**：逐队展示，每队包含抬头行 + 成员行 + 队间空行

### 抬头行格式

抬头信息填入 `rank_order` 列，其余列为空，格式为：

```
实战: 泰坦二 (冠二) #2QQ 苍穹·天空之城 领队:xxx 首领:yyy 管理:zzz 开战/捐兵给一份额外 满员:15/15
```

抬头行构建逻辑：

```python
combat_label = {LEAGUE_COMBAT: "实战", LEAGUE_SHELL: "壳子"}
cat = combat_label.get(tr["category"], tr["category"])
# 满员信息：有预留空位时显示 "已填/总-预留+预留"
if tr["reserved_empty"] > 0:
    cap_info = f"{tr['filled_count']}/{tr['member_count'] - tr['reserved_empty']}+{tr['reserved_empty']}"
else:
    cap_info = f"{tr['filled_count']}/{tr['member_count']}"
# 部落信息（通过 COC API 获取）
clan_name, leader_name = clan_info.get(clan_tag, ("", ""))
# 联赛段位
league_info = f"({tr.get('league_level')}) " if tr.get("league_level") else ""
# 配置领队
config_leader = f"领队:{tr.get('leader', '')} " if tr.get("leader") else ""
# COC 首领
clan_leader = f"首领:{leader_name} " if leader_name else ""
# 拼接
title = f"{cat}: {tr['team_name']} {league_info}{clan_tag} {clan_name} {config_leader}{clan_leader}管理:{tr.get('manager', '')} 开战/捐兵给一份额外 满员:{cap_info}"
```

### 成员行

每个成员按 `ARRANGEMENT_OUTPUT_HEADERS` 字段填入，`team_name` 列统一填入 COC 真实名称。

---

## 六、Part 3：离队情况

**位置**：Part 2 之后（仅在有人离队或被黑名单过滤时才展示）

**数据来源**：
- `_last_removed_list`：上月实战、本月未参加的人员
- `_last_black_hits`：黑名单命中的人员

**结构**：

```
=== 离队情况（共N人）===
  [实战缺失] N人（上月实战，本月未参加）
  account_name | player_tag | movement:缺失(N★) | team_name | prev_team
  ...
  [黑名单] N人
  account_name | player_tag | movement:黑名单
```

- 缺失人员展示：`account_name`、`player_tag`、`movement`（含星数信息如 `缺失(3★)`）、`team_name`、`prev_team`
- 黑名单人员展示：`account_name`、`player_tag`、`movement` 为 `黑名单`
- 两类之间用空行分隔
- 若无人离队且无黑名单命中，则**不展示** Part 3

---

## 七、Part 4：联赛名单排布（备份留底）

**写入方式**：独立 5 列写入，不经过 `ARRANGEMENT_OUTPUT_HEADERS` 的 dict 映射

**原因**：避免 Part1-3 的 13 列表头在 Part4 区域产生多余的空白列，保持表格整洁。

### 写入流程（两阶段）

**阶段 1** — `write_sheet` 预留空行占位：

```python
grid, title_indices = self._build_part4_grid(team_results)
part4_row_count = 2 + len(grid)  # 空行 + 标题 + grid

# 追加空行占位
for _ in range(part4_row_count):
    combined_rows.append({h: None for h in ARRANGEMENT_OUTPUT_HEADERS})

self.excel_io.write_sheet(target, combined_rows, headers=ARRANGEMENT_OUTPUT_HEADERS, sheet=sheet_name)

# 追加 Part4（5 列 grid，覆盖空行占位）
self._append_part4_to_sheet(target, sheet_name, grid, title_indices)
```

**阶段 2** — `_append_part4_to_sheet` 用 `updateRangeRequest` 覆盖写入：
- 计算起始行（总行数 - Part4 行数）
- 构建 5 列矩阵（空行 + 标题行 + grid 行）
- 抬头行红色字体
- 分片写入（按 `_MAX_UPDATE_ROWS` / `_MAX_UPDATE_CELLS` 限制）

### `_build_part4_grid` 构建规则

```python
def _build_part4_grid(self, team_results: list[dict]) -> tuple[list[list[str]], list[int]]:
```

| # | 规则 | 说明 |
|---|------|------|
| 1 | **列数** | 固定 5 列 |
| 2 | **抬头行** | col1=队伍信息+满员、col2=clan_tag、col3=部落名（COC API）、col4=首领（COC API）、col5=管理信息 |
| 3 | **队伍顺序** | 按 `team_results` 原始顺序（实战在前、壳子在后） |
| 4 | **每行 5 人** | 15 人队伍 = 3 行成员，30 人队伍 = 6 行成员 |
| 5 | **实战队伍** | 单元格只显示 `account_name` |
| 6 | **壳子队伍** | 单元格显示 `{account_name} {match_value}`（匹配值取整） |
| 7 | **不足 5 人** | 末尾单元格补空字符串 |
| 8 | **队伍间分隔** | 一空行（最后一队除外） |
| 9 | **部落信息** | 通过 `_fetch_clan_info()` 批量 COC API 查询 + 缓存 |
| 10 | **返回值** | `(grid: list[list[str]], title_indices: list[int])` |

### 壳子 `match_value` 取整

```python
mv = int(m.get("match_value") or 0)
row.append(f"{name} {mv}")
```

---

## 八、公示发布

### `publish_part4_to_doc` 方法

将 Part4 网格发布到公示文档（独立的腾讯文档），与编排工作文档分开。

**流程**：

```python
def publish_part4_to_doc(self, period: str, publish_doc_id: str) -> str:
    # 1. 计算 sheet 名 → "{short_year}.{month}月联赛 报名结果"
    #    如 "26.8月联赛 报名结果"
    y, m = period.split("-")
    short_year = y[2:]
    month_num = str(int(m))
    sheet_name = f"{short_year}.{month_num}月联赛 报名结果"

    # 2. 走完整编排流程（与 arrange_and_export 数据一致）
    _ordered, team_results, _movements, _star_data = self.arrange(period)

    # 3. 生成 Part4 网格（5 列）
    grid, title_indices = self._build_part4_grid(team_results)

    # 4. 拼接：前 20 行固定文字 + Part4 网格
    combined_rows = self.PUBLISH_FIXED_ROWS + grid

    # 5. 写入目标文档（队伍抬头行红色字体）
    self._write_publish_sheet(publish_doc_id, sheet_name, combined_rows, ...)
```

### `PUBLISH_FIXED_ROWS` 固定公告

公示文档前 20 行固定文字（不随月份变化），包含联赛说明、暗号、开战时间、额外规则、报名链接等。

### `_write_publish_sheet` 写入逻辑

- 先查是否已有同名 sheet，有则删后重建
- 无则新建 sheet（指定行列数）
- 抬头行红色字体（通过 `highlight_rows` 指定）
- 直接写入 2D 数据，跳过 dict 转换

---

## 九、关键方法对照

| 方法 | 位置 | 功能 |
|------|------|------|
| `arrange_and_export()` | `roster.py` | 编排+导出主入口，输出 Part1-4 到单个 sheet |
| `_build_part4_grid()` | `roster.py` | 构建 Part4 5 列网格 + 抬头行索引 |
| `_append_part4_to_sheet()` | `roster.py` | 用 `updateRangeRequest` 将 Part4 覆盖写入已有 sheet |
| `_fetch_clan_info()` | `roster.py` | 批量 COC API 查询部落名称和首领，带缓存 |
| `publish_part4_to_doc()` | `roster.py` | 将 Part4 网格发布到公示文档 |
| `_write_publish_sheet()` | `roster.py` | 直接将 2D 数据写入腾讯文档（跳过 dict 转换） |
| `ARRANGEMENT_OUTPUT_HEADERS` | `config/settings.yaml` | Part1-3 的 13 列输出表头定义 |
| `PUBLISH_FIXED_ROWS` | `roster.py` | 公示文档前 20 行固定公告（类常量） |

---

## 十、影响范围

| 文件 | 变更类型 |
|------|---------|
| `roster.py` | `arrange_and_export`、`_build_part4_grid`、`_append_part4_to_sheet`、`publish_part4_to_doc`、`_write_publish_sheet`、`PUBLISH_FIXED_ROWS`、`_fetch_clan_info` |
| `config/settings.yaml` | `ARRANGEMENT_OUTPUT_HEADERS`（13 列，含 `team_name`） |
| `cli.py` | 新增 `publish-results` 命令 |
| `scripts/publish_to_results.sh` | 新增发布公示脚本 |

---

## 十一、测试要点

| # | 场景 | 预期 |
|---|------|------|
| 1 | 正常编排，有 CWL 星数 | Part 1-4 均在同一 sheet 输出 |
| 2 | 冷启动（无星数） | Part 1-4 正常产出 |
| 3 | 有人离队 | Part 3 展示缺失人员，含星数信息 |
| 4 | 有黑名单命中 | Part 3 展示黑名单人员 |
| 5 | 无人离队且无黑名单 | Part 3 不展示 |
| 6 | 15 人实战队 | Part4: 1 抬头 + 3 行成员（每行 5 人） |
| 7 | 30 人队伍 | Part4: 1 抬头 + 6 行成员 |
| 8 | 壳子队伍 | Part4 单元格含 `名称 匹配值`，匹配值为整数 |
| 9 | 实战队伍 | Part4 单元格只含 `名称` |
| 10 | 不足 5 人队伍 | Part4 末尾单元格为空 |
| 11 | Part4 抬头行 5 列完整 | col1=队伍信息、col2=clan_tag、col3=部落名、col4=首领、col5=管理 |
| 12 | COC API 查询失败 | 部落名/首领为空，不影响整体输出 |
| 13 | tag 格式非法 | 跳过 API 查询，不报 404 |
| 14 | 公示发布 | 前 20 行固定公告 + Part4 网格，抬头行红色字体 |
| 15 | 公示 sheet 已存在 | 删后重建，内容为最新 |
