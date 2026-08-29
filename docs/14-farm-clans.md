# 互刷部落功能设计文档

> 版本: v1.3 | 日期: 2026-08-12

---

## 1. 功能概述

在"部落"主页面新增"互刷"按钮，点击后进入互刷部落专属页面。该页面展示所有互刷（`farm`）类别部落的实时配置信息和去速本后的配置信息，用于对比分析部落中速本情况。

---

## 2. 配置变更

### 2.1 部落类别标签

在 `config/settings.yaml` 的 `coc_sync.clans` 中为每个部落新增 `category` 字段，四种类别：

| Key | 含义 | 说明 |
|-----|------|------|
| `combat` | 战营 | 实战联赛部落 |
| `normal` | 混营实战 | 混合实战部落 |
| `farm` | 互刷 | 互刷部落 |
| `flat` | 偷矿 | 偷矿部落 |

**配置示例**：

```yaml
coc_sync:
  clans:
    - tag: "#2QQ"
      name: "云深不知处 战营"
      category: combat
      enabled: true
    - tag: "#LQR"
      name: "秋雨不问梧桐意"
      category: normal
      enabled: true
    - tag: "#YCOC"
      name: "Minecraft(互刷一营)"
      category: farm
      enabled: true
    - tag: "#9V9"
      name: "清风追明月(互刷二营)"
      category: farm
      enabled: true
    # ... 其他互刷部落同理
```

### 2.2 默认值

为兼容现有配置，`category` 字段缺失时默认为 `"normal"`（混营实战）。

### 2.3 加载代码变更

`config/__init__.py` 中确保加载 `category` 字段，并在 `loader.py` 中增加对 `category` 值的校验（合法值: `combat`, `normal`, `farm`, `flat`）。

---

## 3. 前端交互

### 3.1 入口

在 `uni-app/pages/clan/clan.vue` 的 TopBar 按钮数组中新增"互刷"按钮：

```javascript
topButtons: [
  { key: 'record', icon: '⚔️', text: '战绩', action: 'onRecord' },
  { key: 'farm', icon: '🔄', text: '互刷', action: 'onFarm' },
  { key: 'filter', icon: '⏬', text: '筛选', action: 'onFilter' },
  { key: 'search', icon: '🔍', text: '搜索', action: 'onSearch' }
]
```

点击后跳转到新页面 `pages/clan/farm`。

### 3.2 互刷页面 (`pages/clan/farm.vue`)

页面从上到下依次展示所有 `category=farm` 的部落，每个部落展示：

#### 3.2.1 标题行

```
部落名字 #TAG   互刷标签   人数:{当前人数}/50
```

- 部落名字：从 `settings.yaml` 中的 `name` 字段取
- 部落标签：显示 clan tag（如 `#YCOC`），灰色小字
- 互刷标签：显示 `category` 的中文映射（互刷）
- 人数：从部落实时数据中取当前成员数
- **排序**：按配置文件中的部落顺序排列（一营 → 八营），而非字母序

#### 3.2.2 表格一：部落实时配置（大本数目）

```
平均             18   17   16   15   14   13   12   11   other
{avg_th}         x    x    x    x    x    x    x    x    x
```

- 数据来源：COC 官方 API `GET /clans/{clanTag}/members`
- 统计方法：遍历部落成员列表，统计每个大本等级（townHallLevel）的成员数量
- 平均大本：`sum(各成员大本等级) / 成员总数`，保留 1 位小数
- `other`：大本 10 及 10 以下的合计（11 本单独列示）

#### 3.2.3 表格二：部落去速本后实时配置（大本数目）

```
平均             18   17   16   15   14   13   12   11   other
{avg_th}         x    x    x    x    x    x    x    x    x
```

- 数据来源：COC 官方 API `GET /clans/{clanTag}/currentwar`
- 如果部落当前无进行中的部落战（state 不是 inWar 或 preparation），显示提示文字 **"当前无部落战"**
- `other`：去速本后大本 10 及 10 以下的合计（11 本单独列示）

---

## 4. 后端 API 设计

### 4.3 成员速本候选（规划）

互刷页面的“成员”Tab 只展示配置中的 `category=farm` 部落，并按部落分别列出成员。第一阶段仅识别速本，不直接等同于可替换人员。

速本度定义为：

```text
速本度 = 当前大本等级 - 去速本后大本等级
```

速本度大于 0 的成员列为速本候选；0 表示正常。去速本等级沿用当前部落战按 `mapPosition` 的阶段归类算法。无有效部落战时不计算个人速本度。后续再结合职位、活跃度、参战情况和部落最低人数决定最终可替换人员。

成员级速本数据与部落级实时/去速本汇总由同一次 `sync_farm_stats.py` 统一获取和计算，写入同一条 `farm_stats.stats_json`。部落 Tab 读取 `realtime`/`despeed`，成员 Tab 读取 `replace_candidates`，两者必须使用同一场战争数据，并通过 `despeed_source`、`despeed_war_time` 标明来源和时间。当前阶段只使用 `currentwar` 的 `preparation`/`inWar` 数据；无有效部落战时 `replace_candidates` 为空，不将全部成员误判为速本。

### 4.1 `GET /api/clan/farm-config`

获取所有互刷部落的实时配置和去速本配置。**从 `farm_stats` 缓存表读取（毫秒级响应）**，数据由定时脚本 `scripts/sync_farm_stats.py` 定期刷新。

**请求参数**：无

**返回格式**：

```json
{
  "clans": [
    {
      "clan_tag": "#YCOC",
      "clan_name": "Minecraft(互刷一营)",
      "category": "farm",
      "member_count": 48,
      "realtime": {
        "avg_th": 14.2,
        "distribution": {
          "18": 0, "17": 2, "16": 5, "15": 8,
          "14": 12, "13": 10, "12": 6, "11": 3,
          "10": 2, "below_10": 0
        }
      },
      "despeed": {
        "has_war": true,
        "avg_th": 15.1,
        "distribution": {
          "18": 0, "17": 3, "16": 7, "15": 10,
          "14": 11, "13": 9, "12": 5, "11": 2,
          "10": 1, "below_10": 0
        }
      }
    }
  ],
  "updated_at": "2026-08-11T10:30:00+00:00"
}
```

- `realtime`：部落实时配置（从部落成员数据统计），distribution 包含 18-10 及 `below_10`
- `despeed`：去速本后配置（从部落战数据统计），仅统计本方成员
  - `has_war: false` 时表示当前无部落战（状态不是 `inWar` 或 `preparation`）
  - 前端表格列示 18-11 本，将 10、below_10 合并显示为 `other` 列
- `updated_at`：数据最后刷新时间，前端展示"数据更新于 MM-DD HH:mm"
- `clans` 按配置文件中的部落顺序排列（一营 → 八营）

### 4.2 API 实现文件

- 路由定义：`api_server/routes.py` — 从 `farm_stats` 表直接读取，毫秒级响应
- 业务逻辑：`modules/coc_sync/clashking/farm_stats.py` — 去速本算法和统计逻辑
- 数据缓存：`shared/db/connection.py` — `farm_stats` 表 DDL + 迁移
- 定时同步：`scripts/sync_farm_stats.py` — 从 COC API 拉取数据写入缓存表

---

## 5. 去速本算法详解

### 5.1 核心思想

部落战成员按排名从上到下排列（大本等级大致递减），但速本玩家会"插队"出现在排名靠后的位置——一个大本 14 的速本玩家可能排名在稳本 13 玩家之后。

算法通过分析部落战**双方**的成员排列，将速本玩家归类到它实际应属的大本阶段，从而得到"去速本后"的真实大本分布。

### 5.2 算法步骤

```
输入: 部落战双方成员列表（按 mapPosition 升序排列，即从高排名到低排名）
输出: 去速本后的大本分布 {th_level: count}

前提: 部落战排名从上到下大本等级递减（17→16→15→...）
      速本玩家会"插队"出现在不匹配的排名位置（比如TH16出现在14本区间）

1. 收集双方所有成员，合并为一个列表
2. 按 mapPosition 升序排列（从 1 开始，最高排名在前）
3. 初始化 current_stage_th = None, 分布 = {}
4. 遍历排序后的成员列表：
   a. 取该成员的 townHallLevel
   b. 如果 current_stage_th 为 None：
      - current_stage_th = townHallLevel  （第一阶段从第一个成员的大本开始）
   c. 如果 townHallLevel < current_stage_th：
      - 正常递减，进入新阶段：current_stage_th = townHallLevel
   d. 如果 townHallLevel >= current_stage_th：
      - 速本插队（TH 比当前阶段高或相等），保持当前阶段不变
   e. **仅本方成员**记入分布（对方成员只参与阶段判断）
5. 用去速本分布计算平均大本
```

### 5.3 算法示例

假设部落战双方成员（按排名从上到下）的大本等级序列：

```
17, 17, 16, 16, 16, 15, 14, 14, 16, 15, 14, 13, 15, 14, 13, 12, 12, 11, 13, 12, 11, 10, 10
```

遍历过程：

| 序号 | TH | 阶段 | 归类到 |
|------|-----|------|--------|
| 1 | 17 | 阶段1(17) | 17 |
| 2 | 17 | 阶段1 | 17 |
| 3 | 16 | 阶段2(16) | 16 |
| 4 | 16 | 阶段2 | 16 |
| 5 | 16 | 阶段2 | 16 |
| 6 | 15 | 阶段3(15) | 15 |
| 7 | 14 | 阶段4(14) | 14 |
| 8 | 14 | 阶段4 | 14 |
| 9 | 16 | — | **归到阶段4(14)** ← 速本 |
| 10 | 15 | — | **归到阶段4(14)** ← 速本 |
| 11 | 14 | 阶段4 | 14 |
| 12 | 13 | 阶段5(13) | 13 |
| 13 | 15 | — | **归到阶段5(13)** ← 速本 |
| 14 | 14 | — | **归到阶段5(13)** ← 速本 |
| 15 | 13 | 阶段5 | 13 |
| 16 | 12 | 阶段6(12) | 12 |
| 17 | 12 | 阶段6 | 12 |
| 18 | 11 | 阶段7(11) | 11 |
| 19 | 13 | — | **归到阶段7(11)** ← 速本 |
| 20 | 12 | — | **归到阶段7(11)** ← 速本 |
| 21 | 11 | 阶段7 | 11 |
| 22 | 10 | 阶段8(10) | 10 |
| 23 | 10 | 阶段8 | 10 |

**去速本后分布**：
- 17本: 2人
- 16本: 3人
- 15本: 1人
- 14本: 5人 (原本3人 + 速本2人)
- 13本: 4人 (原本1人 + 速本3人)
- 12本: 2人
- 11本: 4人 (原本1人 + 速本3人)
- 10本: 2人

**对比原始分布**：
- 17:2, 16:4, 15:3, 14:4, 13:3, 12:3, 11:2, 10:2

去速本后，速本的大本等级被"提升"到了它所处排名阶段对应的大本等级，从而更真实地反映部落的匹配实力。

### 5.4 平均大本计算

去速本后的平均大本 = `sum(归类后各等级 × 对应人数) / 总人数`

例如上例：`(17×2 + 16×3 + 15×1 + 14×5 + 13×4 + 12×2 + 11×4 + 10×2) / 23 ≈ 13.4`

---

## 6. 数据架构

### 6.1 缓存策略

为避免每次请求都实时调 COC API（8 个部落 × 2 次 API = 16 次调用，耗时 8+ 秒），采用**定时缓存 + 读库**方案：

```
┌──────────────┐     定时拉取      ┌─────────────┐     读库      ┌──────────────┐
│ COC 官方 API  │ ←────────────── │ sync_farm_  │ ──────────── │  farm_stats  │
│ 16 次/周期    │                │ stats.py    │              │  缓存表       │
└──────────────┘                 └─────────────┘              └──────┬───────┘
                                                                     │
                                                              GET /api/clan/
                                                              farm-config
                                                                     │
                                                              ┌──────┴───────┐
                                                              │  routes.py   │
                                                              │  毫秒级响应   │
                                                              └──────────────┘
```

- **响应速度**：8 秒 → 3.8 毫秒（快 2000+ 倍）
- **刷新频率**：定时脚本每 30 分钟拉取一次
- **数据新鲜度**：前端显示"数据更新于"时间戳

### 6.2 同步脚本

```bash
# 单次同步
python3 scripts/sync_farm_stats.py

# 后台循环模式（每 30 分钟）
source .env && nohup python3 scripts/sync_farm_stats.py --loop > /dev/null 2>&1 &

# 自定义间隔（分钟）
python3 scripts/sync_farm_stats.py --loop --interval 60
```

### 6.3 数据流（完整）

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  uni-app     │     │  FastAPI 后端    │     │  COC 官方 API     │
│  farm.vue    │     │  routes.py      │     │  api.clashofclans │
└──────┬───────┘     └────────┬────────┘     └────────┬─────────┘
       │                      │                       │
       │ GET /api/clan/farm-config (毫秒级)            │
       │─────────────────────>│                       │
       │                      │ SELECT farm_stats     │
       │                      │ 直接从缓存表读取       │
       │<─────────────────────│                       │
       │  返回 JSON            │                       │
       │                      │                       │
       │ 渲染页面              │                       │
```

**定时刷新链路**（后台异步）：

```
┌─────────────┐     ┌─────────────────┐
│ sync_farm_  │     │  COC 官方 API     │
│ stats.py    │     │  api.clashofclans │
└──────┬──────┘     └────────┬─────────┘
       │                      │
       │ GET /clans/{tag}/members  (×8)
       │──────────────────────>│
       │<──────────────────────│
       │ GET /clans/{tag}/currentwar  (×8)
       │──────────────────────>│
       │<──────────────────────│
       │                      │
       │ 去速本算法 + INSERT INTO farm_stats
       │──────────────> farm_stats 表
```

---

## 7. 实现计划

### 7.1 后端变更

| 序号 | 文件 | 变更内容 |
|------|------|----------|
| 1 | `config/settings.yaml` | 为所有 clan 添加 `category` 字段 |
| 2 | `config/__init__.py` | 确保 CLANS 导出包含 category 字段，新增辅助函数 `get_farm_clans()` |
| 3 | `config/loader.py` | 校验 category 字段合法性 |
| 4 | `modules/coc_sync/clashking/farm_stats.py` | **新建**：实现去速本算法、部落成员统计、战争数据拉取（走 COC 官方 API） |
| 5 | `api_server/routes.py` | 新增 `GET /api/clan/farm-config` 路由（从 farm_stats 缓存表读取） |
| 6 | `shared/db/connection.py` | 新增 `farm_stats` 表 DDL + 迁移逻辑 |
| 7 | `scripts/sync_farm_stats.py` | **新建**：定时同步脚本，从 COC API 拉取数据写入缓存表，支持 `--loop` 循环模式 |

### 7.2 前端变更

| 序号 | 文件 | 变更内容 |
|------|------|----------|
| 1 | `uni-app/pages/clan/clan.vue` | TopBar 新增"互刷"按钮 |
| 2 | `uni-app/pages/clan/farm.vue` | **新建**：互刷部落页面，展示实时/去速本配置表格 + 数据更新时间 |
| 3 | `uni-app/utils/api.js` | 新增 `getFarmConfig()` 函数 |
| 4 | `uni-app/pages.json` | 注册新页面路由 |

### 7.3 数据库变更

```sql
CREATE TABLE IF NOT EXISTS farm_stats (
    clan_tag     TEXT PRIMARY KEY,
    clan_name    TEXT,
    category     TEXT DEFAULT 'farm',
    member_count INTEGER DEFAULT 0,
    stats_json   TEXT NOT NULL,    -- 完整 JSON（含 realtime + despeed）
    updated_at   TEXT
);
```

### 7.4 依赖

- COC 官方 API（需 `COC_API_TOKEN` 环境变量）
- SQLite 数据库（`data/league.db`）
- 前端复用现有 TopBar 组件和 API 封装

---

## 8. 注意事项

1. **API 限流**：COC 官方 API 有速率限制，同步脚本串行调用每个部落的成员 + 部落战 API（共 16 次），间隔 0.3 秒。建议同步间隔不低于 30 分钟。

2. **缓存策略**：API 路由直接从 `farm_stats` 表读取，响应时间约 3-4 毫秒。数据由 `scripts/sync_farm_stats.py` 定时刷新，推荐每 30 分钟执行一次。

3. **小程序兼容**：
   - 不要使用 `<style scoped>`，小程序中 scoped 会导致 scroll-view 内样式失效
   - 不要嵌套 `scroll-view`（scroll-y 内再套 scroll-x），小程序不支持
   - 表格使用普通 `view` + `flex` 布局，表头在 scroll-view 外面

4. **错误处理**：
   - 单个部落 API 调用失败时，该部落在返回中标记 `error` 字段，不阻塞其他部落
   - 部落战状态为 `preparation` 或 `inWar` 时均计算去速本；状态为其他值时显示"当前无部落战"。若 `currentwar` 请求失败，`despeed.error` 保留错误信息，前端提示重新同步，避免与无战争混淆。
   - 缓存表为空时，API 返回 `{"clans": [], "updated_at": null}`

5. **配置兼容**：`category` 字段为可选，缺失时默认 `"normal"`，确保向后兼容。

6. **编译部署**：修改前端代码后需执行 `npm run build:mp-weixin` 重新编译，再用 `sync-to-local.sh` 同步到本地微信开发者工具。

7. **COC API 字段命名差异**：
   - `GET /clans/{tag}/members` 返回的成员字段为 `townHallLevel`（大写 H）
   - `GET /clans/{tag}/currentwar` 返回的成员字段为 `townhallLevel`（小写 h）
   - 去速本算法从 `currentwar` 读取数据，必须使用 `townhallLevel`，否则 TH 永远为 0
