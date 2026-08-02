# 08 — 外部 API 参考文档

> 外部 API 参考 · Clash of Clans 第三方数据平台
> 整理日期：2026-08-02

---

## 一、War Report API

### 1.1 概述

| 属性 | 值 |
|------|-----|
| **API 基础地址** | `https://api.warreport.app` |
| **认证** | 无需 API Key |
| **协议** | OpenAPI 3.1.0 |
| **文档** | `https://api.warreport.app/`（Swagger UI）、`/openapi.json` |
| **归属要求** | 使用须注明 War Report |
| **官方性质** | 非 Supercell 官方 |

### 1.2 接口列表（10 个）

| # | 方法 | 路径 | 描述 |
|---|------|------|------|
| 1 | GET | `/locations/global/rankings/players` | 赛季末 Top 200 玩家 |
| 2 | GET | `/locations/global/rankings/players/countries` | Top 200 玩家按国家分组 |
| 3 | GET | `/locations/global/rankings/clans` | 赛季末 Top 200 部落 |
| 4 | GET | `/locations/global/rankings/clans/countries` | Top 200 部落按国家分组 |
| 5 | GET | `/armies` | 热门军队组合 |
| 6 | GET | `/armies/heroes` | 英雄使用率 |
| 7 | GET | `/armies/equipment` | 装备使用率 |
| 8 | GET | `/clans/{clanTag}/videos` | 部落相关 YouTube 视频 |
| 9 | GET | `/battle-stats` | 每日传奇联赛攻击统计 |
| 10 | GET | `/battle-stats/dates` | 可用日期列表 |

### 1.3 使用示例

```bash
# 最新赛季 Top 200 玩家
curl -s https://api.warreport.app/locations/global/rankings/players

# 指定赛季部落排名
curl -s "https://api.warreport.app/locations/global/rankings/clans?season=2026-07-01"

# 热门军队
curl -s "https://api.warreport.app/armies?season=2026-07-01"

# 最近一天战斗统计（Top 10，不含英雄明细）
curl -s "https://api.warreport.app/battle-stats?top=10&heroes=false"

# 7 天范围统计
curl -s "https://api.warreport.app/battle-stats?from=2026-07-01&to=2026-07-07&top=10"

# 可用日期
curl -s https://api.warreport.app/battle-stats/dates

# 部落视频
curl -s https://api.warreport.app/clans/2QQ/videos
```

### 1.4 数据范围

仅覆盖**传奇联赛（Legend League）**，不包含 CWL 部落联赛战绩、部落成员等。

---

## 二、ClashKing API ⭐

### 2.1 概述

ClashKing 是一个开源 Clash of Clans 生态系统（Discord Bot + 移动 App + Web Dashboard + API），提供**历史战争记录、CWL 数据、玩家搜索**等 Supercell 官方 API 不提供的数据。

| 属性 | 值 |
|------|-----|
| **API 基础地址** | `https://api.clashk.ing` |
| **认证** | 公开端点无需认证（部分管理端点需 OAuth2） |
| **协议** | OpenAPI（FastAPI + Swagger UI） |
| **文档** | `https://api.clashk.ing/docs`（Swagger UI）、`/openapi.json` |
| **GitHub** | `https://github.com/ClashKingInc/ClashKingAPI` |
| **速率限制** | 30 req/s（普通）、5 req/s（POST/大型请求） |
| **缓存时间** | ~300 秒（5 分钟） |
| **归属要求** | 使用须注明 ClashKing，推荐创作者代码 "ClashKing" |
| **许可证** | GPL-3.0 |
| **CDN** | `https://assets.clashk.ing`（游戏图标、图片等资源） |

### 2.2 接口分类

#### 🔑 认证（Auth）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/token` | 否 | OAuth2 密码流登录 |
| GET | `/users/me` | OAuth2 | 获取当前用户信息 |

#### ⚔️ 部落战（War）⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/war/{clan_tag}/previous` | 历史战争记录（可指定时间范围） |
| GET | `/war/{clan_tag}/previous/{end_time}` | 特定结束时间的部落战 |
| GET | `/war/{clan_tag}/basic` | 基本战争信息（可能绕过私人日志） |

#### 🏆 CWL 联赛 ⭐⭐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/cwl/{clan_tag}/group` | **当前赛季 CWL 小组信息** |
| GET | `/cwl/{clan_tag}/{season}` | **特定赛季 CWL 信息**（`season` 格式 `YYYY-MM`） |

#### 👤 玩家（Player）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/player/{player_tag}/stats` | 玩家全部统计数据 |
| GET | `/player/{player_tag}/legends` | 传奇联赛统计数据 |
| GET | `/player/{player_tag}/historical/{season}` | 历史事件数据 |
| GET | `/player/{player_tag}/warhits` | 部落战攻击记录 |
| GET | `/player/{player_tag}/raids` | 突袭记录 |
| GET | `/player/{player_tag}/legend_rankings` | 历史传奇排名 |
| GET | `/player/{player_tag}/wartimer` | 部落战计时器 |
| GET | `/player/{player_tag}/join-leave` | 加入/离开部落历史 |
| GET | `/player/to-do` | 批量待办事项（最多 50 个 tag） |
| GET | `/player/search/{name}` | 按名称搜索玩家 |
| GET | `/player/full-search/{name}` | 按名称+条件搜索玩家 |

#### 🏰 部落（Clan）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/clan/{clan_tag}/basic` | 部落基本信息 |
| GET | `/clan/{clan_tag}/join-leave` | 赛季加入/离开记录 |
| GET | `/clan/{clan_tag}/historical` | 历史玩家事件数据 |
| GET | `/clan/search` | 按条件搜索部落（位置/等级/人数/奖杯等） |

#### 📊 传奇联赛（Legends）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/legends/clan/{clan_tag}/{date}` | 指定日期部落成员传奇统计数据 |
| GET | `/legends/streaks` | 最佳传奇连胜记录 |
| GET | `/legends/trophy-buckets` | 各奖杯区间玩家数量 |
| GET | `/legends/eos-winners` | 每月传奇联赛排名第一玩家 |

#### 📈 排名（Rankings）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ranking/live/legends` | 实时传奇联赛排名 |
| GET | `/ranking/legends/{player_tag}` | 特定玩家实时排名 |
| GET | `/ranking/player-trophies/{location}/{date}` | 历史玩家奖杯排名 |
| GET | `/ranking/player-builder/{location}/{date}` | 历史夜世界排名 |
| GET | `/ranking/clan-trophies/{location}/{date}` | 历史部落奖杯排名 |
| GET | `/ranking/clan-builder/{location}/{date}` | 历史部落夜世界排名 |
| GET | `/ranking/clan-capital/{location}/{date}` | 历史部落首都排名 |

#### 🏅 排行榜（Leaderboards）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/leaderboard/players/capital` | 玩家首都属性排行榜 |
| GET | `/leaderboard/clans/capital` | 部落首都掠夺排行榜 |

#### 🏗️ 部落首都（Clan Capital）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/capital/{clan_tag}` | 部落突袭周末日志 |
| GET | `/capital/stats/district` | 地区统计数据 |
| GET | `/capital/stats/leagues` | 首都联赛统计数据 |
| POST | `/capital/bulk` | 批量获取突袭周末日志（最多 100 个部落） |

#### ⏱️ 战争时间线（War Timeline）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/timeline/{clan_tag}/{timestamp}` | 指定时间戳的部落战 |
| GET | `/timeline/{clan_tag}` | 部落战信息（HTML） |

#### 📋 列表/元数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/list/seasons` | 最近 N 个赛季列表 |
| GET | `/list/townhalls` | 当前大本营等级列表 |
| GET | `/builderbaseleagues` | 夜世界联赛及图标 |

#### 🌐 全局数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/global/counts` | 全局计数（战争中部落/玩家/传奇玩家数等） |
| GET | `/boost-rate` | 超级部队强化率 |
| GET | `/json/{type}` | 游戏数据 JSON（用 `/json/list` 查看类型） |

### 2.3 使用示例

```bash
# 获取部落 CWL 当前小组信息
curl -s https://api.clashk.ing/cwl/%232QQ/group

# 获取部落特定赛季 CWL 信息
curl -s "https://api.clashk.ing/cwl/%232QQ/2026-07"

# 搜索玩家
curl -s https://api.clashk.ing/player/search/PlayerName

# 获取玩家全部统计
curl -s https://api.clashk.ing/player/%23XXXXXXX/stats

# 获取部落历史战争记录
curl -s "https://api.clashk.ing/war/%232QQ/previous?limit=10"

# 获取特定时间的部落战
curl -s "https://api.clashk.ing/war/%232QQ/previous/1690000000"

# 获取部落基本信息
curl -s https://api.clashk.ing/clan/%232QQ/basic

# 获取部落加入/离开记录
curl -s "https://api.clashk.ing/clan/%232QQ/join-leave?limit=50"

# 获取最近 6 个赛季列表
curl -s "https://api.clashk.ing/list/seasons?last=6"

# 获取全局计数
curl -s https://api.clashk.ing/global/counts
```

### 2.4 速率限制

| 类型 | 限制 |
|------|------|
| 普通 GET 请求 | 30 req/s |
| POST 请求、大型请求 | 5 req/s |
| 数据缓存 | ~300 秒（5 分钟） |

---

## 三、与本项目的关联分析

### 3.1 功能匹配矩阵

| 本项目需求 | Supercell 官方 API | ClashKing API | War Report API |
|-----------|:---:|:---:|:---:|
| CWL 当前赛季信息 | ✅ | ✅ `/cwl/{tag}/group` | ❌ |
| CWL 历史赛季数据 | ❌ | ✅ `/cwl/{tag}/{season}` | ❌ |
| 部落成员同步 | ✅ | ❌ | ❌ |
| 玩家搜索/统计 | ✅ | ✅ 更强（历史数据） | ❌ |
| 历史战争记录 | ❌ | ✅ `/war/{tag}/previous` | ❌ |
| 传奇联赛趋势 | ❌ | ✅ | ✅ |
| 热门兵种统计 | ❌ | ❌ | ✅ `/armies` |
| 全球排名 | ✅ | ✅ | ✅ |
| 部落加入/离开历史 | ❌ | ✅ | ❌ |

### 3.2 关键发现：ClashKing 的 CWL 接口 ⭐

**ClashKing 提供历史 CWL 数据**，这正是 Supercell 官方 API 的盲区：

- `/cwl/{clan_tag}/group` — 当前赛季 CWL 小组
- `/cwl/{clan_tag}/{season}` — **历史赛季 CWL 数据**（`YYYY-MM` 格式）

这意味着如果某个月忘记运行 `fetch_cwl_data.py`，可以用 ClashKing API 作为**数据回补方案**。

### 3.3 推荐使用策略

| 场景 | 使用方案 |
|------|----------|
| **主力 CWL 数据源** | Supercell 官方 API（当前 `coc_sync` 模块） |
| **CWL 数据回补**（错过窗口期） | ClashKing `/cwl/{tag}/{season}` |
| **历史战争分析** | ClashKing `/war/{tag}/previous` |
| **玩家流动追踪** | ClashKing `/clan/{tag}/join-leave` |
| **传奇联赛趋势** | War Report `/battle-stats` 或 ClashKing `/legends/*` |
| **兵种 meta 分析** | War Report `/armies` |

---

## 四、CWL 数据获取的根本限制

根据 War Report FAQ 和 Supercell API 文档：

> Supercell 官方 API **不提供历史 CWL 赛季完整数据**——只能查"当前战争"和"最近战争日志预览"。War Report 依赖 ClashKing 每月 13 号导入 CWL 数据（因为部分部落 CWL 到 12 号才结束）。

**因此**：本项目 `fetch_cwl_data.py` 在 CWL 结束后**立即**通过 Supercell API 拉取并存库的做法是唯一可靠方案。ClashKing API 的 CWL 接口可作为**灾备回补**。

---

## 五、相关资源

| 资源 | 地址 |
|------|------|
| War Report 官网 | `https://warreport.app/` |
| War Report API | `https://api.warreport.app/` |
| War Report API 文档 | `https://api.warreport.app/openapi.json` |
| War Report FAQ | `https://warreport.app/about/docs/faq/` |
| ClashKing 官网 | `https://clashk.ing/` |
| ClashKing API | `https://api.clashk.ing` |
| ClashKing API 文档 | `https://api.clashk.ing/docs` |
| ClashKing GitHub | `https://github.com/ClashKingInc/ClashKingAPI` |
| ClashKing 资源 CDN | `https://assets.clashk.ing` |
| Supercell 官方 API | `https://developer.clashofclans.com/` |
