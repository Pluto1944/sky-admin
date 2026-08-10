# 部落战战绩统计（War Stats）设计文档

## 1. 需求概述

在小程序部落主页面的"战绩"按钮进入的战绩页面中，增加"部落战"标签，展示普通部落战的进攻/防守三星率统计表。与联赛战绩（league-stats）共用一个页面，通过顶部标签切换。

每行一个成员，每列对应一个滚动窗口的三星率：

| 列 | 名称 | 含义 |
|---|---|---|
| 1 | 进攻(前5场) | 最近 5 场普通部落战进攻三星率 |
| 2 | 进攻(前15场) | 最近 15 场普通部落战进攻三星率（滚动累计） |
| 3 | 进攻(前45场) | 最近 45 场普通部落战进攻三星率（滚动累计） |
| 4 | 防守(前5场) | 最近 5 场普通部落战防守三星率 |
| 5 | 防守(前15场) | 最近 15 场普通部落战防守三星率（滚动累计） |
| 6 | 防守(前45场) | 最近 45 场普通部落战防守三星率（滚动累计） |

**滚动窗口定义**：以当前日期为基准，按 `end_time` 倒序取最近 N 场普通部落战，将该窗口内所有场次的数据累加计算。

**为什么用"场次"而非"月份"**：
- 部落战约 2 天一场，频率远高于 CWL（每月一次）
- 用月份做窗口（上月/前3月/前6月）粒度太粗，一场部落战的好坏被几十场稀释
- 用场次更贴合部落战节奏：
  - 前 5 场 ≈ 最近 ~10 天的表现（短期状态）
  - 前 15 场 ≈ 最近 ~1 个月的表现（中期趋势）
  - 前 45 场 ≈ 最近 ~3 个月的表现（长期水平）

**三星率计算公式**：
- 进攻三星率 = 窗口内进攻三星次数 / 窗口内总进攻次数
- 防守三星率 = 窗口内被对手三星次数 / 窗口内被进攻总次数

---

## 2. 与联赛战绩的关键差异

### 2.1 数据来源

| 维度 | 联赛战绩 (CWL) | 部落战战绩 (Clan War) |
|------|---------------|----------------------|
| 筛选逻辑 | `is_cwl_war()` 为 True | `is_cwl_war()` 为 **False** |
| 数据表 | `league_results` | `war_results`（新建） |
| 部落标签 | 来自 `league_teams.clan_tag`（多个队伍部落） | 固定使用 `#2QQ`（战营） |
| 频率 | 每月一次（7天连续） | 约 2 天一场 |
| 统计窗口 | 按月份（上月/前3月/前6月） | 按场次（前5场/前15场/前45场） |
| 窗口基准 | `period`（YYYY-MM） | `end_time`（ISO 8601，精确到天） |

### 2.2 满星前统计（核心差异）

**背景**：当前版本部落战难度较低，经常出现"满星后还有剩余攻击"的情况。满星后的攻击属于"垃圾时间"，不能反映真实水平，不计入统计。

**满星定义**：部落层面的满星。设参赛人数为 `n`（`teamSize`），满星 = `n * 3` 星。即所有敌方基地都被三星。

**统计规则**：

对于每一场部落战：

1. 收集我方（`clan` 方）和对手（`opponent` 方）所有成员的攻击，按全局攻击序号 `order` 升序排列
2. 初始化我方累计星数 = 0，对手累计星数 = 0
3. 遍历每次攻击（按 `order` 升序）：

   **进攻统计**（攻击来自我方成员）：
   - 当前攻击发生**前**，我方累计星数 < 满星（`teamSize * 3`） → 计入进攻统计
   - 当前攻击发生**后**，更新我方累计星数（`+= stars`）
   - 当前攻击发生**前**，我方累计星数 ≥ 满星 → **跳过**（垃圾时间）

   **防守统计**（攻击来自对手成员）：
   - 当前攻击发生**前**，对手累计星数 < 满星（`teamSize * 3`） → 计入防守统计
   - 当前攻击发生**后**，更新对手累计星数（`+= stars`）
   - 当前攻击发生**前**，对手累计星数 ≥ 满星 → **跳过**（垃圾时间）

   **进攻与防守独立判断，互不影响**：即使对手已经满星，我方仍在追星的攻击依然计入进攻统计；反之亦然。

**示例**（15v15 部落战，满星 = 45 星）：

```
order=1: 我方玩家A 打 对手X → 3星 → 我方累计=3  (< 45) → 计入进攻统计
order=2: 对手玩家Y 打 我方B → 2星 → 对手累计=2  (< 45) → 计入防守统计
...
order=43: 我方玩家C 打 对手Z → 3星 → 我方累计=42→45 (≥ 45) → 不计入！(垃圾时间)
order=44: 对手玩家W 打 我方D → 3星 → 对手累计=44→47 (≥ 45 后才发生) → 不计入！(垃圾时间)
order=45: 我方玩家E 打 对手V → 1星 → 我方累计=45→46 (≥ 45) → 不计入！(垃圾时间)
```

### 2.3 `order` 字段说明

ClashKing API 返回的 `attacks` 数组中每条攻击记录都有 `order` 字段（整数，从 1 开始），该字段**贯穿整场战争全局递增**，不区分我方/对手阵营，双方攻击交错排列。

经 API 实际验证：`order` 从 1 到 `teamSize * attacksPerMember`（普通部落战每人 2 次攻击，即 `teamSize * 2`）。

---

## 3. 数据库变更

### 3.1 新建 `war_results` 表

```sql
CREATE TABLE IF NOT EXISTS war_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_tag        TEXT NOT NULL,           -- 部落标签（固定 #2QQ）
    player_tag      TEXT NOT NULL,           -- 玩家标签（FK → accounts）
    account_name    TEXT,                    -- 游戏昵称
    town_hall_level INTEGER,                -- 大本等级（采集时记录）
    end_time        TEXT NOT NULL,           -- 战争结束时间（ISO 8601，如 "20260809T122220.000Z"）
    total_stars     INTEGER DEFAULT 0,       -- 总星数
    attacks         INTEGER DEFAULT 0,       -- 进攻次数（满星前的有效进攻）
    offense_3stars  INTEGER DEFAULT 0,       -- 进攻三星次数（满星前）
    defense_3stars  INTEGER DEFAULT 0,       -- 防守被三星次数（满星前）
    defense_total   INTEGER DEFAULT 0,       -- 被进攻总次数（满星前）
    fetched_at      TEXT,                    -- 数据拉取时间（ISO 8601）
    raw_metrics     TEXT,                    -- JSON 扩展字段
    UNIQUE(clan_tag, player_tag, end_time),
    FOREIGN KEY(player_tag) REFERENCES accounts(player_tag)
);
```

**表结构对比**：

| 字段 | `league_results` | `war_results` | 说明 |
|------|-----------------|---------------|------|
| `period` | ✅ | ❌ | league_results 用 period 做月份，war_results 用 end_time 做场次标签 |
| `team_index` | ✅ | ❌ | CWL 特有的队伍编号，普通部落战不需要 |
| `team_alias` | ✅ | ❌ | CWL 特有的队伍别名，普通部落战不需要 |
| `team_name` | ✅ | ❌ | CWL 特有的 COC 部落名，普通部落战不需要 |
| `category` | ✅ | ❌ | 固定 combat，普通部落战不需要 |
| `clan_tag` | ✅ | ✅ | 两者都有，但 war_results 固定为 `#2QQ` |
| `end_time` | ❌ | ✅ | war_results 的核心时间字段，精确到单场战争，作为唯一键一部分 |
| 其他字段 | ✅ | ✅ | `player_tag`, `account_name`, `town_hall_level`, 战绩字段相同 |

**唯一约束**：`UNIQUE(clan_tag, player_tag, end_time)` — 同一场战争中同一玩家只有一条记录。`end_time` 精确到天/秒，避免了多场战争的数据覆盖问题。

### 3.2 raw_metrics JSON 扩展

```json
{
    "total_stars": 18,
    "offense_3stars": 5,
    "offense_total": 7,
    "defense_3stars": 2,
    "defense_total": 7,
    "clan_tag": "#2QQ",
    "team_size": 45,
    "enemy_clan": "敌方部落名",
    "total_possible_attacks": 90
}
```

---

## 4. 代码变更清单

### 4.1 文件：`shared/db/connection.py`

**变更**：新增 `war_results` 表 DDL + 迁移逻辑。

- 新增 `_WAR_RESULTS_DDL` 常量
- 在 `_CHILDREN_DDL` 中加入 `_WAR_RESULTS_DDL`
- 在 `_migrate()` 中检测旧库是否存在 `war_results` 表，不存在则建表

### 4.2 文件：`modules/coc_sync/clashking/client.py`

**变更**：新增 `aggregate_regular_war_players()` 函数。

核心逻辑：

```python
def aggregate_regular_war_players(regular_wars: list[dict], clan_tag: str) -> list[dict]:
    """从普通部落战列表中汇总指定部落的玩家战绩（只统计满星前的数据）。

    与 aggregate_players() 的关键区别：
    - 筛选非 CWL 战斗（is_cwl_war 为 False 的）
    - 按 order 字段排序所有攻击，只统计满星前的攻击/防守数据
    - 满星 = teamSize * 3

    Args:
        regular_wars: 非 CWL 的战争列表
        clan_tag: 目标部落标签

    Returns:
        [{tag, name, total_stars, total_attacks, offense_3stars, defense_3stars, defense_total,
          end_time, town_hall_level, team_size, enemy_clan}, ...]
    """
```

**满星前统计伪代码**：

```
对每场 war:
    teamSize = war["teamSize"]
    max_stars = teamSize * 3  # 满星阈值
    
    # 确定我方和对手方
    if clan.tag == our_tag:
        our_side = clan, enemy_side = opponent
    else:
        our_side = opponent, enemy_side = clan
    
    # 收集所有攻击，统一按 order 排序
    all_attacks = []
    for m in our_side.members:
        for a in m.attacks:
            all_attacks.append({"order": a.order, "side": "our", "player_tag": m.tag, 
                                "name": m.name, "stars": a.stars, ...})
    for m in enemy_side.members:
        for a in m.attacks:
            all_attacks.append({"order": a.order, "side": "enemy", "defenderTag": a.defenderTag,
                                "stars": a.stars, ...})
    
    all_attacks.sort(key=lambda x: x["order"])
    
    our_stars = 0   # 我方累计星数
    enemy_stars = 0 # 对手累计星数
    
    for attack in all_attacks:
        if attack["side"] == "our":
            if our_stars < max_stars:
                # 满星前 → 计入进攻统计
                record offense (stars, offense_3stars if stars==3)
            our_stars += attack["stars"]
        else:
            if enemy_stars < max_stars:
                # 满星前 → 计入防守统计
                record defense (defense_total++, defense_3stars++ if stars==3)
            enemy_stars += attack["stars"]
```

**注意**：此函数不直接处理"按场次筛选"，筛选逻辑在数据采集层（`fetch_war_data.py`）处理。函数只负责给定一批战争数据，汇总玩家战绩。

### 4.3 文件：`scripts/fetch_war_data.py`（新建）

**部落战数据采集脚本**。

流程：
1. 从配置读取 `camp_clan_tag: "#2QQ"`
2. 调用 `fetch_war_log("#2QQ")` 拉取 war log
3. 筛选 `not is_cwl_war(war)` 的普通部落战
4. 调用 `aggregate_regular_war_players()` 汇总战绩
5. 写入 `war_results` 表（`ON CONFLICT DO NOTHING` 保证幂等）

**关键设计**：

```python
def main():
    parser = argparse.ArgumentParser(description="拉取普通部落战数据并写入 war_results 表")
    parser.add_argument("--clan-tag", default="#2QQ", help="部落标签")
    parser.add_argument("--limit", type=int, default=100, help="API 拉取条数上限")
    args = parser.parse_args()

    # 1. 拉取 war log（ClashKing 返回最近 N 场，按 endTime 降序）
    wars = fetch_war_log(args.clan_tag, limit=args.limit)
    
    # 2. 筛选普通部落战（非 CWL）
    regular_wars = [w for w in wars if not is_cwl_war(w)]
    
    # 3. 汇总玩家战绩（满星前统计）
    players = aggregate_regular_war_players(regular_wars, args.clan_tag)
    
    # 4. 写入数据库（ON CONFLICT DO NOTHING 保证幂等）
    _write_to_db(players, args.clan_tag)
```

**回填策略**：

- **历史数据回填（一次性）**：运行 `python scripts/fetch_war_data.py --limit 200`，拉取 ClashKing 返回的全部历史 war log 并回填
- **后续增量更新**：每次运行 `python scripts/fetch_war_data.py`，自动拉取最新 war log，`ON CONFLICT DO NOTHING` 保证已存在的记录不会被重复写入
- **采集频率**：手动触发。测试通过后再考虑改为定时任务

### 4.4 文件：`api_server/routes.py`

**变更**：新增 `GET /api/clan/war-stats` API 端点。

```
GET /api/clan/war-stats
```

不需要传参（不像 league-stats 需要 `period` 参数），因为统计窗口始终以"当前时间"为基准取最近 N 场。

**返回格式**：

```json
{
    "stats": [
        {
            "player_tag": "#2QU99V0QQ",
            "account_name": "aram",
            "town_hall_level": 17,
            "offense_5": 0.714,
            "offense_15": 0.650,
            "offense_45": 0.600,
            "defense_5": 0.286,
            "defense_15": 0.330,
            "defense_45": 0.350
        }
    ]
}
```

**实现逻辑**：

1. 查询当前 `registrations.account_type = 'combat'` 的成员（取最新 period）
2. 从 `war_results` 表按 `end_time DESC` 查询 `clan_tag = '#2QQ'` 的所有记录
3. 在 Python 中按 `player_tag` 分组，按 `end_time` 排序，截取最近 5/15/45 场的数据
4. 聚合各窗口的三星率

**核心 SQL**：

```sql
-- 查询所有战营成员的部落战数据，按 end_time 倒序
SELECT wr.player_tag, wr.account_name, wr.town_hall_level,
       wr.end_time, wr.attacks, wr.offense_3stars,
       wr.defense_3stars, wr.defense_total
FROM war_results wr
WHERE wr.clan_tag = '#2QQ'
  AND wr.player_tag IN (
      SELECT a.player_tag
      FROM registrations r
      JOIN accounts a ON a.account_name = r.account_name
      WHERE r.period = ? AND r.account_type = 'combat'
  )
ORDER BY wr.end_time DESC
```

**Python 聚合逻辑**（与 league-stats 不同，按场次而非月份）：

```python
# 1. 获取该玩家参与的所有战争，按 end_time 倒序排列
# 2. 取前 5 场 → 累计 offense_3stars / attacks → offense_5
# 3. 取前 15 场 → 累计 offense_3stars / attacks → offense_15
# 4. 取前 45 场 → 累计 offense_3stars / attacks → offense_45
# 5. 防守同理

# 注意：每个玩家参与的战争列表不同（有人可能某场没参加），
# 所以是按每个玩家各自的参与场次截取，而非全局前 N 场
```

**与 `league_stats` 的差异**：

| 维度 | `league-stats` | `war-stats` |
|------|---------------|-------------|
| 数据表 | `league_results` | `war_results` |
| 窗口类型 | 按月份（上月/前3月/前6月） | 按场次（前5场/前15场/前45场） |
| 参数 | `?period=YYYY-MM` | 无需参数（始终以当前时间为基准） |
| 聚合逻辑 | 按 period 分桶累加 | 按 end_time 排序截取前 N 场 |
| 部落筛选 | 无需（period 粒度已区分） | `clan_tag = '#2QQ'` |
| 每个玩家窗口 | 相同（同一个月窗口） | 不同（每人的"最近N场"不同） |

### 4.5 文件：`uni-app/pages/clan/stats.vue`

**变更**：在页面顶部 TopBar 下方增加两个标签切换按钮："部落战" / "联赛"。根据标签动态切换列定义。

**改造前**：
```
┌─────────────────────────────────┐
│ ← 联赛战绩                      │  ← TopBar
├─────────────────────────────────┤
│ 昵称 │ 本 │ 进攻上月 │ ...      │  ← 表格
```

**改造后**：
```
┌─────────────────────────────────┐
│ ← 战绩                          │  ← TopBar（标题改为"战绩"）
├─────────────────────────────────┤
│  [部落战]  [联赛]               │  ← 新增标签切换栏
├─────────────────────────────────┤
│ 昵称 │ 本 │ 进攻近7场 │ ...     │  ← 表格（列定义根据标签切换）
```

**具体改动**：

1. TopBar title 改为 `"战绩"`（去掉"联赛"前缀）
2. 新增 `tab` data 属性：`'war' | 'league'`，默认 `'war'`
3. 新增标签切换 UI（两个按钮，选中态高亮）
4. 列定义根据 `tab` 动态切换：

   **部落战标签**（`tab === 'war'`）：
   ```
   列: 进攻(前5场) | 进攻(前15场) | 进攻(前45场) | 防守(前5场) | 防守(前15场) | 防守(前45场)
   字段: offense_5 | offense_15 | offense_45 | defense_5 | defense_15 | defense_45
   ```

   **联赛标签**（`tab === 'league'`）：
   ```
   列: 进攻(上月) | 进攻(前3月) | 进攻(前6月) | 防守(上月) | 防守(前3月) | 防守(前6月)
   字段: offense_1m | offense_3m | offense_6m | defense_1m | defense_3m | defense_6m
   ```

5. `fetchData()` 根据 `tab` 值调用不同 API：
   - `tab === 'war'` → `getWarStats()`
   - `tab === 'league'` → `getLeagueStats()`
6. 颜色阈值、排序逻辑、表格渲染保持不变

**标签切换 UI 结构**：

```vue
<view class="tab-bar">
    <view class="tab-item" :class="{ active: tab === 'war' }" @tap="switchTab('war')">
        <text>部落战</text>
    </view>
    <view class="tab-item" :class="{ active: tab === 'league' }" @tap="switchTab('league')">
        <text>联赛</text>
    </view>
</view>
```

### 4.6 文件：`uni-app/utils/api.js`

**变更**：新增 `getWarStats()` 方法。

```javascript
/**
 * 获取部落战战绩统计（按场次滚动窗口三星率）
 * @returns {Promise} { stats: [{ player_tag, account_name, town_hall_level, offense_5, ... }] }
 */
export function getWarStats() {
    return request('/api/clan/war-stats')
}
```

同时在 `export default` 中加入 `getWarStats`。

### 4.7 文件：`uni-app/pages/clan/clan.vue`

**变更**：无需改动。

战绩按钮 `onRecord()` 仍然跳转到 `pages/clan/stats`。进入页面后默认显示"部落战"标签，用户可通过标签切换到"联赛"。

### 4.8 文件：`uni-app/pages.json`

**变更**：无需改动。

`pages/clan/stats` 路由已存在，`navigationBarTitleText` 改为 `"战绩"`。

---

## 5. 实施步骤

### 步骤 0：历史数据回填（前置步骤，一次性）

**背景**：当前 `war_results` 表为空，需要从 ClashKing API 回填历史部落战数据。

```bash
# 拉取 #2QQ 部落的历史普通部落战数据（limit 设大以覆盖更多历史）
python scripts/fetch_war_data.py --clan-tag "#2QQ" --limit 200
```

**回填策略说明**：

| 场景 | 行为 |
|------|------|
| war_results 表中已有该场战争记录 | `ON CONFLICT DO NOTHING` 跳过，不重复写入 |
| ClashKing API 返回了新战争 | 正常拉取 → 满星前统计 → 写入 |
| ClashKing API 不可达 | 报错退出（无本地 JSON 兜底，部落战没有本地备份） |
| 某场战争中某玩家不在 accounts 表中 | 跳过该玩家（同 fetch_cwl_data.py 逻辑） |

**幂等性保证**：
- `UNIQUE(clan_tag, player_tag, end_time)` 约束保证同场战争同玩家不会重复
- `ON CONFLICT DO NOTHING` 静默跳过已存在记录
- 可安全地多次执行同一命令，只写入新数据

**后续增量更新**：
- 每次手动运行 `python scripts/fetch_war_data.py`，自动拉取最新 war log，只写入新战争数据

---

### 步骤 1：数据库迁移

修改 `shared/db/connection.py`：
- 新增 `_WAR_RESULTS_DDL` 常量
- 加入 `_CHILDREN_DDL`
- 在 `_migrate()` 中增加 `war_results` 表的存在性检查，不存在则建表

**风险**：低。纯新增表，不影响现有数据和功能。

### 步骤 2：新增聚合函数

在 `modules/coc_sync/clashking/client.py` 中新增 `aggregate_regular_war_players()` 函数。

**风险**：低。纯新增函数，不影响现有 `aggregate_players()` 和 `fetch_cwl_players()`。

### 步骤 3：新建数据采集脚本

新建 `scripts/fetch_war_data.py`。

**风险**：低。独立脚本，不依赖其他模块改动。

### 步骤 4：新增后端 API

在 `api_server/routes.py` 中新增 `GET /api/clan/war-stats`。

**风险**：低。新增端点，不影响现有 `league-stats`。

### 步骤 5：前端页面改造

- 修改 `stats.vue`：增加标签切换栏，根据选中标签动态切换列定义和 API 调用
- 修改 `api.js`：新增 `getWarStats()` 方法

**风险**：中。涉及现有 `stats.vue` 页面的改造，需要保证"联赛"标签下的行为与改造前一致。

### 步骤 6：测试验证

- 启动 API 服务，验证 `/api/clan/war-stats` 返回正确
- 小程序端验证标签切换、列定义切换、数据加载、排序、颜色显示
- 验证"联赛"标签下行为与改造前完全一致（回归测试）

---

## 6. 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 某场部落战某成员无进攻记录 | `attacks = 0`，该场不贡献进攻数据 |
| 某场部落战某成员未被进攻 | `defense_total = 0`，该场不贡献防守数据 |
| 某成员参与场次 < 5 | offense_5/defense_5 用全部已有场次计算（例如只有3场就用3场） |
| 某成员参与场次 < 15 | offense_15/defense_15 用全部已有场次计算 |
| 某成员参与场次 < 45 | offense_45/defense_45 用全部已有场次计算 |
| 某成员从未打过部落战 | 出现在列表中，所有列显示 `-`（LEFT JOIN 结果全为 NULL） |
| 成员已不在当月战营报名中 | 不显示（筛选条件为当月 registrations.account_type = 'combat'） |
| ClashKing API 不可达 | 报错退出，无本地 JSON 兜底 |
| 某场战争在满星阈值之前就已结束（未满星） | 正常统计全部攻击（条件 `our_stars < max_stars` 始终为 true） |
| 某场战争 teamSize 非常规（如 10v10、45v45） | 满星 = teamSize * 3，逻辑不变 |
| 对手方攻击的 defenderTag 指向非我方成员 | 不计入防守统计（同现有 league_results 逻辑） |
| 战争结束后 ClashKing 返回的 order 值不连续 | 按实际 order 值排序即可，不依赖连续性 |
| 多场战争 end_time 相同（同一天结束） | UNIQUE 约束按 `(clan_tag, player_tag, end_time)` 区分，不会覆盖 |

---

## 7. 颜色阈值

与联赛战绩保持一致：

| | 🟢 绿色 | 🟡 黄色 | 🔴 红色 |
|---|---|---|---|
| **进攻** | > 85.7% | 57.1%~85.7% | ≤ 57.1% |
| **防守** | ≤ 57.1% | 57.1%~85.7% | > 85.7% |

- 无数据（null）：灰色 `#666`，显示 `-`

---

## 8. 文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `shared/db/connection.py` | 修改 | 新增 `war_results` 表 DDL + 迁移逻辑 |
| `modules/coc_sync/clashking/client.py` | 修改 | 新增 `aggregate_regular_war_players()` 函数 |
| `scripts/fetch_war_data.py` | **新建** | 部落战数据采集脚本 |
| `api_server/routes.py` | 修改 | 新增 `GET /api/clan/war-stats` 端点 |
| `uni-app/pages/clan/stats.vue` | 修改 | 增加标签切换栏（部落战/联赛）+ 动态列定义 |
| `uni-app/utils/api.js` | 修改 | 新增 `getWarStats()` 方法 |
| `docs/13-war-stats.md` | **新建** | 本设计文档 |

**与 `clan.vue` 和 `pages.json` 的关系**：
- `clan.vue` 的"战绩"按钮**无需改动**，仍跳转到 `pages/clan/stats`
- `pages.json` 的 `stats` 路由**无需改动**，仅 `navigationBarTitleText` 从"联赛战绩"改为"战绩"

---

## 9. 架构图

```mermaid
flowchart TB
    subgraph "数据来源"
        A[ClashKing API<br>/war/{clan_tag}/previous] --> B{is_cwl_war?}
        B -->|True| C[aggregate_players<br>全量统计]
        B -->|False| D[aggregate_regular_war_players<br>满星前统计]
    end

    subgraph "数据存储"
        C --> E[(league_results<br>按 period 分组)]
        D --> F[(war_results<br>按 end_time 分组)]
    end

    subgraph "数据采集"
        G[scripts/fetch_cwl_data.py] --> E
        H[scripts/fetch_war_data.py<br>新建] --> F
    end

    subgraph "API 层"
        I[GET /api/clan/league-stats<br>窗口: 上月/前3月/前6月] --> E
        J[GET /api/clan/war-stats<br>窗口: 前5场/前15场/前45场] --> F
    end

    subgraph "前端 stats.vue"
        K[标签切换栏<br>部落战 | 联赛]
        K -->|部落战<br>列: offense_5/15/45| J
        K -->|联赛<br>列: offense_1m/3m/6m| I
    end
```
