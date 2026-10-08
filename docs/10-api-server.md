# API Server 文档

## 概述

`api_server/` 是基于 FastAPI 构建的 RESTful API 服务，为苍穹联赛管理提供后端接口，同时支持微信小程序登录认证。

- **线上地址**: `https://api.skycoc.cc`
- **框架**: FastAPI
- **认证**: JWT (HS256, 30 天有效期)
- **数据库**: SQLite（与主项目共用 `data/` 下的 db 文件）

---

## 文件结构

```
api_server/
├── app.py      # FastAPI 应用工厂（CORS、路由挂载）
├── auth.py     # JWT 认证工具（生成/解析 token、require_user 依赖）
├── deps.py     # 依赖注入（Database、PlayerRepository 单例）
├── routes.py   # 路由定义（全部 API 端点）
└── __init__.py
```

---

## 启动方式

```bash
# 开发环境（注意：--reload 手动起进程前，先停掉 systemd 服务，避免端口冲突）
cd /home/ubuntu/YANG/sky-admin
sudo systemctl stop sky-admin
uvicorn api_server.app:app --host 0.0.0.0 --port 8000 --reload

# 生产环境（通过 deploy/ 下的 systemd 服务管理）
sudo systemctl start sky-admin
```

> ⚠️ **生产环境禁止手动 `uvicorn --reload` 起进程**。历史曾因手动起的 `0.0.0.0:8000 --reload` 进程占用端口，导致 systemd 的 `sky-admin` 服务崩溃循环（重启 11 万+ 次）。生产环境请始终通过 `systemctl` 管理，详见 [`deploy/README.md`](../deploy/README.md)。

---

## 环境变量

所有配置从项目根目录 `.env` 文件加载，`load_env()` 在 `app.py` 中调用。

| 变量 | 说明 | 示例 |
|------|------|------|
| `SKY_ADMIN_ENV` | 环境标识，`production` 时关闭 `/docs` | `production` |
| `WECHAT_APPID` | 微信小程序 AppID | `wx6a46dda85a013a34` |
| `WECHAT_SECRET` | 微信小程序 AppSecret | （32 位字符串） |
| `JWT_SECRET` | JWT 签名密钥 | （64 位随机字符串） |

---

## API 接口列表

### 1. 健康检查

```
GET /api/ping
```

无需认证。返回服务状态、已部署的 Git 发布版本和时间戳。API 进程启动时读取根目录
`VERSION` 并冻结运行身份；后续只更新磁盘文件但未重启服务时，`version` 仍如实返回旧进程
加载的版本。`VERSION` 必须与本次发布 Tag 一致。

**响应示例**：
```json
{
  "status": "ok",
  "service": "sky-admin-api",
  "version": "v1.1.1",
  "timestamp": "2026-08-08T08:00:00+00:00"
}
```

### 1.1 系统运行版本

```
GET /api/system/version
```

无需认证。聚合当前 API worker 的启动身份和 `sky-scheduler.service` 写入
`service_runtime` 的启动身份/心跳。`healthy` 表示调度器心跳未超过 15 分钟；`consistent`
只有在两个组件版本、Git commit 一致、心跳正常且启动时均无已跟踪未提交改动时才为 `true`。

```json
{
  "status": "ok",
  "release_version": "v1.3.0",
  "healthy": true,
  "consistent": true,
  "components": {
    "api": {
      "component": "api",
      "git_commit": "<full commit>",
      "git_describe": "v1.3.0",
      "tracked_dirty": false,
      "started_at": "2026-10-06T01:00:00+00:00",
      "health": "healthy"
    },
    "scheduler": {
      "component": "scheduler",
      "heartbeat_at": "2026-10-06T01:01:00+00:00",
      "health": "healthy"
    }
  }
}
```

---

### 2. 成员列表

```
GET /api/members
```

无需认证。从 `accounts` 和本地成员统计投影读取成员信息。接口在服务端完成筛选、排序和分页，
默认只返回仍在自有部落的成员第 1 页，每页 100 人；不会访问 COC API。

**查询参数**：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `page` | `1` | 页码，从 1 开始 |
| `page_size` | `100` | 每页人数，范围 1–100 |
| `membership_status` | `member` | `member` / `left` / `all` |
| `clan_tags` | 空 | 逗号分隔的部落标签，可多选 |
| `search` | 空 | 搜索昵称、玩家标签、部落标签、部落名或联赛名 |
| `sort_key` | `town_hall_level` | 前端表头支持的排序字段 |
| `sort_order` | `desc` | `asc` / `desc` |

筛选和排序作用于完整结果集，之后再截取当前页，因此切换页面不会破坏跨部落排名。无统计样本的
成员无论升序或降序都放在末尾。

**响应示例**：
```json
{
  "count": 50,
  "page": 1,
  "page_size": 100,
  "total_pages": 1,
  "clans": [
    { "tag": "#2QQ", "name": "云深不知处 战营" }
  ],
  "members": [
    {
      "player_tag": "#ABC123",
      "account_name": "玩家昵称",
      "exp_level": 150,
      "trophies": 3200,
      "league_name": "Champion III",
      "town_hall_level": 16,
      "clan_tag": "#CLAN01",
      "clan_role": "leader",
      "status": "active",
      "membership_status": "member",
      "last_synced_at": "2026-08-07T12:00:00",
      "updated_at": "2026-08-07T12:00:00"
    }
  ]
}
```

**错误码**：
- `422` — 页码、页大小、成员状态或排序字段不合法
- `500` — 数据库查询失败

#### 成员活动与贡献字段

`GET /api/members` 已返回 `donations`、`donations_received`、`season_attack_wins`、`last_activity_at`、`last_activity_reasons` 和 `activity_observed_since`。接口只读本地缓存，不在页面请求中逐玩家访问 COC API，也不向前端返回完整 `coc_raw`。

其中“最近活动”是检测到公开数据有效变化的时间，不是精确登录时间。赛季进攻由后端周期读取玩家详情后缓存，捐兵/收兵从成员 `coc_raw` 提取。完整响应和重置规则见 [22-member-activity.md](22-member-activity.md)。

接口同时返回 `war_recent_15` 和 `cwl_recent_3m` 两个结构化摘要。前者按 `player_tag` 汇总最近 90 天内、跨全部自有部落的最近最多 15 场参战普通战，包含战争数、三星数、实际/可用进攻数、三星率和出刀率；后者按 `player_tag` 汇总最近 3 个完整联赛月内全部自有联赛队伍的一星数、三星数、实际进攻数、一星率和三星率。两者都限制自有部落边界，但不按部落业务类型过滤；玩家当前 `clan_tag` 只用于展示和筛选。百分比必须伴随原始计数，无样本返回 `null`，前端显示 `-`。接口批量查询 `member_war_facts` 和 `league_results`，不扫描完整战争 JSON，也不依赖已删除的成员摘要缓存。当前前端尚未展示一星数据；该字段也不参与联赛排序、扣分或升降级。

`GET /api/clan/farm-config` 除互刷战争配置外，还为每个已配置互刷部落返回
`fill_accounts` 和 `inactive_members`。前者由本地 `farm_fill_accounts` 与当前 `accounts` 按玩家 Tag
关联，后者在当前成员中排除填坑号和首领后，按 `last_activity_at`、回退
`activity_observed_since` 从旧到新取最多 5 人。该公开接口沿用现有小程序访问范围，请求路径不会读取
腾讯文档；没有有效部落战时仍须返回填坑号和不活跃名单。

成员贡献还返回 `capital_recent_4w` 和 `clan_games`。都城摘要包含实际纳入周数、总掠夺、实际/可用刀数和每刀掠夺；竞赛摘要包含统计月份、本期积分、完整性、近 3 期平均和实际期数。无都城样本时不返回摘要；竞赛缺少前期基准时 `complete=false`，不得返回虚假的 0 分。两项都只读调度任务保存的本地事实。

---

### 2.1 自有部落概览

```
GET /api/clan/overview
GET /api/clan/overview/{clan_tag}
```

无需认证。汇总接口按 `config/settings.yaml` 中已启用部落的顺序返回卡片，包含类别、成员数、平均大本、人均奖杯、首领、当前赛季捐兵、最后同步时间，以及本地缓存的 `war_status` 和 `capital_status`。单部落详情额外返回大本分布、职位分布、捐出/收到/人均捐兵，以及 `profile`、`profile_status`、`profile_updated_at`。

两个接口只读本地缓存，不在 HTTP 请求中调用 COC API。成员聚合来自 `accounts` 中 `membership_status = 'member'` 的当前快照，捐兵数从 `coc_raw` 读取；状态分别来自 `current_war_cache` 和 `capital_raid_status_cache`；官方资料来自 `clan_profile_cache`，包含徽章、等级、加入方式、战争胜平负/连胜、战争与都城联赛、三类积分、地区、开战频率、加入门槛、官方标签和描述。资料同步失败但有旧缓存时 `profile_status=stale`。

`clan_profile_cache` 跟随 `coc_sync` 每 6 小时刷新。未同步的配置部落仍返回空卡片，不影响其他部落；详情标签不属于已启用自有部落时返回 `404`。

### 2.2 当前部落战汇总

```
GET /api/clan/current-wars
```

无需认证。返回 `config/settings.yaml` 中全部已启用自有部落的当前战争摘要、分类筛选元数据和缓存更新时间。接口只读取 `current_war_cache`，不会在 HTTP 请求中直接访问 COC。

每个部落的 `status` 为 `preparation`、`in_war`、`war_ended`、`cwl`、`not_in_war`、`sync_pending` 或 `error`。汇总响应不包含成员宽表 `rows`。

### 2.3 单个部落当前战争详情

```
GET /api/clan/current-wars/{clan_tag}
```

无需认证，但 `clan_tag` 必须属于已启用自有部落，否则返回 `404`。详情包含战争概要和按 `mapPosition` 对齐的 `rows`。每位成员包含按官方 `order` 排序的第一/第二刀、最佳防守，以及 `three_star_count / total_attacks` 防守次数数据。

这两个接口的数据由调度器 `current_wars` 每 2 分钟检查：战斗日每 2 分钟，准备日通常每 30 分钟且开战前 30 分钟内提升为每 2 分钟，无战争 / 已结束每 5 分钟，CWL 跳转状态每 30 分钟从 COC 刷新；小程序停留在页面时每 1 分钟读取一次缓存。完整设计见 [18-current-war-dashboard.md](18-current-war-dashboard.md)。

### 2.4 普通部落战历史

```
GET /api/clan/war-history?clan_tag=%232QQ
GET /api/clan/war-history/{clan_tag}/{war_key}
```

无需认证。汇总接口返回每个已启用自有部落最近 15 场已结束普通战争的轻量摘要、分类和部落筛选元数据；详情接口返回单场完整阵容与攻防宽表。接口只读 `war_history_cache`，不直接调用外部 API。CWL、未结束战争和外部部落标签不会出现在历史列表。

### 2.5 CWL 参赛部落汇总

```
GET /api/clan/cwl-live?period=YYYY-MM
```

无需认证。`period` 可选，默认北京时间当前月份。部落范围只读当月 `league_teams` 中的 `combat` 和 `shell` 队伍，返回队伍类别、轮次、排名、胜负、星数、摧毁率、缓存状态和更新时间。若该月存在正式名单快照，同时返回 `leader_name`（官方完整首领昵称，缺失时回退配置简称）和 `manager_names`（当月联赛管理）。响应中的 `available_periods` 始终包含当前月，并只加入所有参赛队 `raw_status=complete` 的历史月份；该列表直接读取已持久化的完整性结论，不在首页请求中重新解析历史战争 JSON。

### 2.6 单个 CWL 部落详情

```
GET /api/clan/cwl-live/{clan_tag}?period=YYYY-MM&round=4&view=war-day
GET /api/clan/cwl-live/{clan_tag}?period=YYYY-MM&view=overview
```

无需认证，但 `clan_tag` 必须属于对应月份的 `league_teams`，否则返回 `404`。`view=war-day` 只返回第 1～7 场战斗日及双方对位宽表，不生成、也不返回四张总览表；`view=overview` 只返回大本概览、小组对局、成员进攻和成员防守统计，不返回逐场阵容。两种响应都包含部落头部摘要、同月可切换队伍和 `payload_view`。`view` 不传时暂时返回完整响应，仅用于兼容已发布的旧版小程序；新版前端必须显式传参，未知值返回 `422`。

汇总和详情接口只读取 `cwl_live_group_cache`、`cwl_live_war_cache` 及当月 `league_teams`，不会在 HTTP 请求中访问 COC。实时同步与页面结构见 [19-cwl-live-dashboard.md](19-cwl-live-dashboard.md)。

### 2.7 CWL 集结检查

```
GET /api/clan/cwl-assembly
GET /api/clan/cwl-assembly/{clan_tag}
```

无需认证。汇总接口返回当月全部联赛部落的正式人数、已到位、未到位、额外成员、冻结状态和缓存时间；详情接口返回按“未到位、额外成员、正常成员”分组的数据，其中当前成员含职位和大本等级。`clan_tag` 必须属于当月 `league_teams`。

两个接口只读取 `cwl_roster_snapshots` 和 `cwl_assembly_cache`，不会在请求内读取腾讯文档或调用 COC。正式名单和成员检查规则见 [21-cwl-assembly-check.md](21-cwl-assembly-check.md)。

---

### 3. 微信登录

```
POST /api/wechat/login
```

无需认证。用微信 `wx.login()` 返回的 code 换取 JWT token。

**请求体**：
```json
{
  "code": "0a3x...微信返回的code"
}
```

**响应示例**（已有用户）：
```json
{
  "token": "eyJhbGciOiJI...",
  "user": {
    "openid": "oXXXX-xxx",
    "nickname": "微信用户",
    "role": "member",
    "account_name": "游戏昵称",
    "player_tag": "#ABC123"
  }
}
```

**响应示例**（新用户）：
```json
{
  "token": "eyJhbGciOiJI...",
  "user": {
    "openid": "oXXXX-xxx",
    "nickname": null,
    "role": "member",
    "account_name": null,
    "player_tag": null
  }
}
```

**逻辑流程**：
1. 用 code 调用微信 `jscode2session` 接口换取 `openid`
2. 查 `wechat_users` 表：有则返回 token + 用户信息；无则自动创建新记录
3. 新用户默认 `role=member`，`account_name` 和 `player_tag` 为空

**错误码**：
- `400` — 缺少 code 参数
- `400` — 微信登录失败（code 无效/过期）
- `500` — 服务端未配置 AppID/AppSecret

---

### 4. 获取当前用户信息

```
GET /api/wechat/me
```

**需要认证**：`Authorization: Bearer <token>`

**响应示例**：
```json
{
  "openid": "oXXXX-xxx",
  "nickname": "微信用户",
  "avatar_url": null,
  "role": "member",
  "account_name": "游戏昵称",
  "player_tag": "#ABC123",
  "created_at": "2026-08-01T10:00:00"
}
```

**错误码**：
- `401` — Token 无效或已过期
- `404` — 用户不存在

---

### 5. 绑定游戏账号

```
POST /api/wechat/bind
```

**需要认证**：`Authorization: Bearer <token>`

**请求体**（至少填一项）：
```json
{
  "account_name": "游戏昵称",
  "player_tag": "#ABC123"
}
```

**响应示例**：
```json
{
  "success": true,
  "user": {
    "openid": "oXXXX-xxx",
    "nickname": "微信用户",
    "role": "member",
    "account_name": "游戏昵称",
    "player_tag": "#ABC123"
  }
}
```

**错误码**：
- `400` — 至少需要 account_name 或 player_tag
- `401` — Token 无效或已过期
- `404` — 用户不存在（需先登录）

---

## 认证机制

### JWT Token

- **算法**: HS256
- **有效期**: 30 天
- **Payload**: `{ openid, role, exp, iat }`
- **传递方式**: `Authorization: Bearer <token>`

### 保护接口

在路由中使用 `Depends(require_user)` 即可保护接口：

```python
from .auth import require_user

@router.get("/api/me")
def me(user: dict = Depends(require_user)):
    return {"openid": user["openid"], "role": user["role"]}
```

---

## 数据库

### wechat_users 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `openid` | TEXT PK | 微信用户唯一标识 |
| `nickname` | TEXT | 微信昵称 |
| `avatar_url` | TEXT | 头像 URL |
| `role` | TEXT | 角色：admin / moderator / member |
| `account_name` | TEXT | 绑定的游戏昵称 |
| `player_tag` | TEXT | 绑定的玩家标签 |
| `created_at` | TEXT | 创建时间 (ISO 8601) |
| `updated_at` | TEXT | 更新时间 (ISO 8601) |

---

## CORS

开发/生产环境均允许所有来源的跨域请求：

```python
allow_origins=["*"]
allow_methods=["*"]
allow_headers=["*"]
```

---

## 部署

### Systemd 服务

```ini
# /etc/systemd/system/sky-admin.service
[Unit]
Description=Sky Admin API Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/YANG/sky-admin
Environment="PATH=/home/ubuntu/YANG/sky-admin/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="SKY_ADMIN_ENV=production"
ExecStart=/home/ubuntu/YANG/sky-admin/venv/bin/uvicorn api_server.app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=append:/var/log/sky-admin.log
StandardError=append:/var/log/sky-admin-error.log

[Install]
WantedBy=multi-user.target
```

> 完整部署流程与运维命令见 [`deploy/README.md`](../deploy/README.md) 与 `deploy/deploy.sh`。

### Nginx 反向代理

```nginx
server {
    listen 443 ssl;
    server_name api.skycoc.cc;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
