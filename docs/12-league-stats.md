# 联赛战绩统计（League Stats）设计文档

## 1. 需求概述

在小程序部落主页面的"战绩"按钮中，展示一张联赛进攻/防守三星率统计表。

每行一个成员，每列对应一个滚动窗口的三星率：

| 列 | 名称 | 含义 |
|---|---|---|
| 1 | 进攻(上月) | 上月 CWL 联赛进攻三星率 |
| 2 | 进攻(前3月) | 前 3 个月 CWL 联赛进攻三星率（滚动累计） |
| 3 | 进攻(前6月) | 前 6 个月 CWL 联赛进攻三星率（滚动累计） |
| 4 | 防守(上月) | 上月 CWL 联赛防守三星率 |
| 5 | 防守(前3月) | 前 3 个月 CWL 联赛防守三星率（滚动累计） |
| 6 | 防守(前6月) | 前 6 个月 CWL 联赛防守三星率（滚动累计） |

**滚动窗口定义**：以当前月份为基准，往前回推 N 个月，将该窗口内所有月份的 CWL 数据累加计算。例如现在是 2026-08，"前 3 月"窗口 = 2026-06、2026-07、2026-08 三个月的数据汇总。

**三星率计算公式**：
- 进攻三星率 = 窗口内进攻三星次数 / 窗口内总进攻次数
- 防守三星率 = 窗口内被对手三星次数 / 窗口内被进攻总次数

---

## 2. 数据来源

### 2.1 原始数据

ClashKing API 的 war log 返回每场 CWL 战争的完整数据，包含 `clan`（我方）和 `opponent`（对手）两方：

```json
{
  "endTime": "20260709T122220.000Z",
  "teamSize": 15,
  "clan": {
    "tag": "#2GGGGGGG",
    "name": "DIAMONDFIREINDO",
    "members": [
      {
        "tag": "#2QU99V0QQ",
        "name": "aram",
        "attacks": [
          { "defenderTag": "#OPPONENT_TAG", "stars": 3, "destructionPercentage": 100 }
        ]
      }
    ]
  },
  "opponent": {
    "tag": "#XXXXXXX",
    "name": "Enemy Clan",
    "members": [
      {
        "tag": "#ENEMY_TAG",
        "name": "enemy_player",
        "attacks": [
          { "defenderTag": "#2QU99V0QQ", "stars": 2, "destructionPercentage": 85 }
        ]
      }
    ]
  }
}
```

### 2.2 进攻与防守数据提取逻辑

**进攻数据**：遍历我方（clan/opponent 中 tag 匹配的部落）每个成员的 `attacks[]`：
- `attacks[].stars == 3` → 进攻三星次数 +1
- `len(attacks)` → 总进攻次数 +1

**防守数据**：遍历对手方每个成员的 `attacks[]`，检查 `attacks[].defenderTag` 是否指向我方成员：
- 如果 `defenderTag` 在我方成员集合中 → 该成员被进攻次数 +1
- 如果同时 `attacks[].stars == 3` → 该成员防守被三星次数 +1

### 2.3 历史数据冷启动

**问题**：现有 `data/cwl_202607/*.json` 只包含进攻数据（`total_stars`、`total_attacks`、`three_star_rate`），**没有防守数据**。

**解决策略**：
- 修改 `aggregate_players` 函数后，重新从 ClashKing API 拉取历史月份数据
- 每拉取一个月份，写入 `league_results` 表时带上 `offense_3stars`、`defense_3stars`、`defense_total`、`fetched_at`
- 历史 JSON 文件仅作兜底（无防守数据时防守列显示 `-`）

---

## 3. 数据库变更

### 3.1 league_results 表新增列

在现有 `league_results` 表上增加 4 列：

```sql
ALTER TABLE league_results ADD COLUMN offense_3stars INTEGER DEFAULT 0;
ALTER TABLE league_results ADD COLUMN defense_3stars INTEGER DEFAULT 0;
ALTER TABLE league_results ADD COLUMN defense_total  INTEGER DEFAULT 0;
ALTER TABLE league_results ADD COLUMN fetched_at    TEXT;
```

最终表结构：

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| period | TEXT NOT NULL | CWL 月份，如 "2026-07" |
| team_index | INTEGER NOT NULL | 队伍编号 |
| team_alias | TEXT NOT NULL | 队伍别名 |
| team_name | TEXT | COC 真实部落名 |
| clan_tag | TEXT | 部落标签 |
| category | TEXT NOT NULL | 固定 "combat" |
| player_tag | TEXT NOT NULL | 玩家标签（FK → accounts） |
| account_name | TEXT | 游戏昵称 |
| total_stars | INTEGER | 总星数（已有） |
| attacks | INTEGER | 进攻次数（已有） |
| **offense_3stars** | **INTEGER DEFAULT 0** | **新增：进攻三星次数** |
| **defense_3stars** | **INTEGER DEFAULT 0** | **新增：防守被三星次数** |
| **defense_total** | **INTEGER DEFAULT 0** | **新增：被进攻总次数** |
| **fetched_at** | **TEXT** | **新增：数据拉取时间（ISO 8601）** |
| raw_metrics | TEXT | JSON 扩展字段（保留） |

唯一约束：`UNIQUE(period, team_index, player_tag)`

### 3.2 raw_metrics JSON 扩展

`raw_metrics` 在保留现有字段基础上新增：

```json
{
  "total_stars": 18,
  "offense_3stars": 5,
  "offense_total": 7,
  "defense_3stars": 2,
  "defense_total": 7,
  "team_name": "冠一 一队",
  "clan_tag": "#2GGGGGGG",
  "team_index": 1
}
```

**注意**：三星率不存入数据库，每次查询时实时计算（`offense_3stars / attacks`），因为它是派生值。

---

## 4. 代码变更清单

### 4.1 文件：`shared/db/connection.py`

**变更**：`_migrate()` 方法中新增对 `league_results` 表的列迁移。

```python
# 在 _migrate() 方法中新增：
lr_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(league_results)")}

if "offense_3stars" not in lr_cols:
    self.conn.execute("ALTER TABLE league_results ADD COLUMN offense_3stars INTEGER DEFAULT 0")
if "defense_3stars" not in lr_cols:
    self.conn.execute("ALTER TABLE league_results ADD COLUMN defense_3stars INTEGER DEFAULT 0")
if "defense_total" not in lr_cols:
    self.conn.execute("ALTER TABLE league_results ADD COLUMN defense_total INTEGER DEFAULT 0")
if "fetched_at" not in lr_cols:
    self.conn.execute("ALTER TABLE league_results ADD COLUMN fetched_at TEXT")
```

同时更新 `_LEAGUE_RESULTS_DDL`，新库直接建完整表。

### 4.2 文件：`modules/coc_sync/clashking/client.py`

**变更**：`aggregate_players()` 函数增加进攻/防守三星统计。

核心改动：
- `player_stats` 字典新增 `offense_3stars`、`defense_3stars`、`defense_total` 字段
- 遍历我方成员的 `attacks[]` 时，统计 `stars == 3` 的次数
- 遍历对手方成员的 `attacks[]` 时，检查 `defenderTag` 是否在我方成员集合中，若是则统计防守数据

返回值新增字段：
```python
{
    "tag": "#XXX",
    "name": "玩家名",
    "total_stars": 18,
    "total_attacks": 7,
    "offense_3stars": 5,    # 新增
    "defense_3stars": 2,    # 新增
    "defense_total": 7,     # 新增
}
```

**注意事项**：
- `total_attacks` 字段名保持不变（兼容现有调用方）
- 如果某场 war 中我方不在 clan 也不在 opponent（理论上不会发生），跳过该场
- **防守数据 tag 匹配**：`defenderTag` 是原始格式（带 `#`），需要建立 `normalized_tag → original_tag` 映射，避免防守数据写入空 tag 的新记录中（已修复）

### 4.3 文件：`scripts/fetch_cwl_data.py`

**变更**：写入 `league_results` 时带上新增列。

改动位置：
- `_fetch_and_write()` 函数：INSERT/UPDATE 语句增加 `offense_3stars, defense_3stars, defense_total, fetched_at`
- `_cold_start_from_json()` 函数：同上
- `_fetch_via_local_json()` 函数：本地 JSON 可能没有防守数据，此时防守列写入 0

INSERT 语句变更示例：
```python
conn.execute(
    """INSERT INTO league_results
       (period, team_index, team_alias, team_name, clan_tag, category,
        player_tag, account_name, total_stars, attacks,
        offense_3stars, defense_3stars, defense_total, fetched_at,
        raw_metrics)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(period, team_index, player_tag) DO UPDATE SET
       ...
       offense_3stars = excluded.offense_3stars,
       defense_3stars = excluded.defense_3stars,
       defense_total = excluded.defense_total,
       fetched_at = excluded.fetched_at,
       ...""",
    (...)
)
```

### 4.4 文件：`api_server/routes.py`

**变更**：新增 API 端点 `GET /api/clan/league-stats`。

```
GET /api/clan/league-stats?months=6
```

**返回格式**：
```json
{
  "period": "2026-08",
  "updated_at": "2026-08-17T11:46:19+00:00",
  "stats": [
    {
      "player_tag": "#2QU99V0QQ",
      "account_name": "aram",
      "town_hall_level": 17,
      "offense_1m": 0.714,
      "offense_3m": 0.65,
      "offense_6m": 0.60,
      "defense_1m": 0.286,
      "defense_3m": 0.33,
      "defense_6m": 0.35
    }
  ]
}
```

> `updated_at` 为 `league_results` 表相关月份最近一次数据同步时间（`fetched_at` 最大值），供前端展示「数据更新于」。

**成员筛选规则**：

显示当月 `registrations.account_type = 'combat'`（战营成员）的**全部**成员：
- 有战绩数据的 → 正常显示三星率
- 没战绩数据的 → 各列显示 `-`（null）

**计算逻辑**：

1. 根据当前月份生成滚动窗口月份列表：
   - 上月窗口：最近 1 个完整月份（不含当月）
   - 前 3 月窗口：最近 3 个完整月份
   - 前 6 月窗口：最近 6 个完整月份

2. 以当月战营成员为基础，LEFT JOIN 查询 `league_results` 表中所有相关月份的数据：
   ```sql
   SELECT a.player_tag, a.account_name, a.town_hall_level,
          lr.period, lr.attacks, lr.offense_3stars,
          lr.defense_3stars, lr.defense_total
   FROM registrations r
   JOIN accounts a ON a.account_name = r.account_name
   LEFT JOIN league_results lr ON lr.player_tag = a.player_tag AND lr.period IN (?, ?, ?, ?, ?, ?)
   WHERE r.period = ?
     AND r.account_type = 'combat'
   ```

   > 用 `LEFT JOIN` 而非 `INNER JOIN`，确保没有 `league_results` 记录的成员也出现在结果中（对应字段为 NULL）。

3. 在 Python 中按 `player_tag` 分组聚合：
   - 对每条记录，根据其 `period` 判断属于哪个窗口
   - 累计各窗口的 `offense_3stars`、`attacks`、`defense_3stars`、`defense_total`
   - 计算三星率：`rate = 3stars / total`（除数为 0 时返回 `null`）

4. 返回所有战营成员的 6 列统计结果

**性能考量**：
- 6 个月数据约 6 × 7 天 × 15 人 × N 队 ≈ 数千行，Python 内存聚合完全可行
- 不按窗口分组多次查询，一次查询全部数据在内存中计算，避免 N+1 问题

### 4.5 文件：`uni-app/pages/clan/clan.vue`

**变更**：`onRecord()` 方法改为跳转到战绩页面。

```javascript
onRecord() {
    uni.navigateTo({ url: '/pages/clan/stats' })
},
```

### 4.6 新建文件：`uni-app/pages/clan/stats.vue`

战绩统计表格页面。

**页面结构**：
- 自定义顶部栏，标题"联赛战绩"
- 横向可滚动表格（`scroll-view scroll-x`）
- 固定首列（昵称 + 本数），其余 6 列可左右滑动
- 加载状态和空状态处理

**表格列定义**：

| 序号 | 列名 | 字段 | 宽度 | 固定 |
|------|------|------|------|------|
| 0 | 昵称 | account_name | 160rpx | 是 |
| 1 | 本 | town_hall_level | 60rpx | 否 |
| 2 | 进攻(上月) | offense_1m | 140rpx | 否 |
| 3 | 进攻(前3月) | offense_3m | 140rpx | 否 |
| 4 | 进攻(前6月) | offense_6m | 140rpx | 否 |
| 5 | 防守(上月) | defense_1m | 140rpx | 否 |
| 6 | 防守(前3月) | defense_3m | 140rpx | 否 |
| 7 | 防守(前6月) | defense_6m | 140rpx | 否 |

**颜色规则**（以7场联赛为基准，按三星场数划分）：

| | 🟢 绿色 | 🟡 黄色 | 🔴 红色 |
|---|---|---|---|
| **进攻** | > 6场三星（>85.7%） | 5~6场三星（57.1%~85.7%） | ≤ 4场三星（≤57.1%） |
| **防守** | ≤ 4场被三星（≤57.1%） | 5~6场被三星（57.1%~85.7%） | > 6场被三星（>85.7%） |

- 无数据（null）：灰色 `#666`，显示 `-`

**排序功能**：
- 点击列头切换排序（升序 ↔ 降序）
- 默认按"进攻(6月)"降序排列
- 当前排序列显示排序箭头指示器（↑/↓）
- 无数据的条目排在最后

### 4.7 文件：`uni-app/pages.json`

**变更**：注册新路由。

```json
{
    "path": "pages/clan/stats",
    "style": {
        "navigationStyle": "custom",
        "navigationBarTitleText": "联赛战绩"
    }
}
```

### 4.8 文件：`uni-app/utils/api.js`

**变更**：新增接口方法。

```javascript
export function getLeagueStats(months = 6) {
    return request(`/api/clan/league-stats?months=${months}`)
}
```

---

## 5. 实施步骤

### 步骤 0：历史数据回填（前置步骤，一次性）

**背景**：当前 `league_results` 表中只有 2-3 个月的历史数据，且是通过旧版 `fetch_cwl_data.py` 写入的（缺少 `offense_3stars`、`defense_3stars`、`defense_total`、`fetched_at`）。在后续步骤改完 DB 迁移和采集层之后，需要将这些历史月份重新拉取一遍，补全新字段数据。

#### 5.0.1 回填脚本

`scripts/backfill_league_results.sh` 自动发现缺失月份并回填：

- 从 `league_teams` 表获取所有 `combat` 队伍月份
- 与 `league_results` 表中 `fetched_at IS NOT NULL` 的月份做差集
- 对缺失月份逐月调用 `fetch_cwl_data.py --period YYYY-MM` 拉取数据
- `ON CONFLICT DO UPDATE` 保证幂等

```bash
bash scripts/backfill_league_results.sh
```

#### 5.0.2 回填策略说明

| 场景 | 行为 |
|------|------|
| `league_teams` 有该月数据 | 正常走 ClashKing API → 写入完整数据（含防守数据） |
| `league_teams` 无该月数据（冷启动） | 走本地 JSON 兜底 → 防守数据为 0，`fetched_at` 标记为 `"local_json"` |
| ClashKing API 不可达 | 降级到本地 JSON，同上 |
| 某月本地 JSON 也不存在 | 该月回填失败，跳过 |

#### 5.0.3 回填结果（2026-08-09 执行）

成功回填 2026-01 ~ 2026-08 共 8 个月，全部通过 ClashKing API 拉取，含完整进攻/防守三星数据：

| 月份 | 人数 | 进攻三星 | 总进攻 | 防守三星 | 防守总次数 |
|------|------|----------|--------|----------|------------|
| 2026-01 | 67 | 355 | 459 | 270 | 453 |
| 2026-02 | 67 | 335 | 454 | 326 | 460 |
| 2026-03 | 82 | 437 | 558 | 320 | 558 |
| 2026-04 | 86 | 515 | 591 | 376 | 586 |
| 2026-05 | 92 | 595 | 643 | 471 | 637 |
| 2026-06 | 126 | 1131 | 1327 | 1009 | 1311 |
| 2026-07 | 146 | 733 | 1001 | 725 | 886 |
| 2026-08 | 132 | 707 | 875 | 725 | 872 |
| **总计** | **190 人** | **4808** | **5908** | **4222** | **5763** |

> 2026-09 的 CWL 尚未开始，ClashKing API 无数据，届时自动拉取即可。

#### 5.0.4 后续每月回填

正常流程中，每月 `register_and_arrange.sh` 会自动调用 `fetch_cwl_data.py --period YYYY-MM` 拉取当月数据。但如果某月漏了或拉取失败，可手动补跑：

```bash
python scripts/fetch_cwl_data.py --period 2026-08
```

`league_results` 的 `ON CONFLICT DO UPDATE` 机制保证重复拉取不会产生重复数据，而是覆盖更新。

---

### 步骤 1：数据库迁移

修改 `shared/db/connection.py`，新增列迁移逻辑 + 更新 DDL。

**风险**：低。ALTER TABLE ADD COLUMN 是纯增量操作，不影响现有数据。

### 步骤 2：修改数据采集层

修改 `modules/coc_sync/clashking/client.py` 的 `aggregate_players` 函数，增加进攻/防守三星统计。

修改 `scripts/fetch_cwl_data.py`，写入新增列 + `fetched_at`。注意同时修改以下三处：

- `_fetch_and_write()`：INSERT/UPDATE 语句增加 4 个新列
- `_cold_start_from_json()`：同上，且需补充 `fetched_at` 写入
- `_fetch_via_local_json()`：返回值增加 `offense_3stars`、`defense_3stars`、`defense_total`（默认值 0）

**风险**：中。`aggregate_players` 的返回值结构变化会影响调用方，需确保所有使用方兼容。

### 步骤 3：新增后端 API

在 `api_server/routes.py` 新增 `GET /api/clan/league-stats`。

### 步骤 5：小程序前端

- 修改 `clan.vue` 的战绩按钮跳转
- 新建 `stats.vue` 战绩表格页面
- 注册路由 + API 方法

### 步骤 6：测试验证

- 启动 API 服务，验证 `/api/clan/league-stats` 返回正确
- 小程序端验证表格渲染、排序、颜色显示

---

## 6. 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 某成员某月无进攻记录 | `attacks = 0`，该月三星率为 `null`，不参与滚动窗口计算 |
| 某成员某月无防守记录 | `defense_total = 0`，防守三星率为 `null` |
| 滚动窗口内所有月份都无数据 | 返回 `null`，前端显示 `-` |
| 当月战营成员但从未打过 CWL | 出现在列表中，所有列显示 `-`（LEFT JOIN 结果全为 NULL） |
| 成员已不在当月战营报名中 | 不显示（筛选条件为当月 registrations.account_type = 'combat'） |
| ClashKing API 不可达 | 降级使用本地 JSON（防守数据缺失，显示 `-`） |
| 当月 CWL 未开始 | 上月窗口不包含当月，正常使用完整月份数据 |

---

## 7. 文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `shared/db/connection.py` | 修改 | DDL + migrate 新增 4 列 |
| `modules/coc_sync/clashking/client.py` | 修改 | aggregate_players 新增进攻/防守统计 + 修复 tag 匹配 bug |
| `scripts/fetch_cwl_data.py` | 修改 | 写入新增列 + fetched_at |
| `scripts/backfill_league_results.sh` | **新建** | 历史数据一次性回填脚本（自动发现缺失月份） |
| `api_server/routes.py` | 修改 | 新增 GET /api/clan/league-stats |
| `uni-app/pages/clan/clan.vue` | 修改 | 战绩按钮改为跳转 |
| `uni-app/pages/clan/stats.vue` | **新建** | 战绩表格页面 |
| `uni-app/pages.json` | 修改 | 注册新路由 |
| `uni-app/utils/api.js` | 修改 | 新增 getLeagueStats 方法 |
