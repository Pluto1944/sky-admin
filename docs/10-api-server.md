# API Server 文档

## 概述

`api_server/` 是基于 FastAPI 构建的 RESTful API 服务，为苍穹联赛管理提供后端接口，同时支持微信小程序登录认证。

- **线上地址**: `https://api.skycoc.cc`
- **框架**: FastAPI
- **认证**: 微信 JWT 与互刷系统 JWT（均为 HS256、30 天有效期，受众和校验依赖隔离）
- **数据库**: SQLite（与主项目共用 `data/` 下的 db 文件）

---

## 文件结构

```
api_server/
├── app.py             # FastAPI 应用工厂（CORS、路由挂载）
├── auth.py            # JWT 认证工具（生成/解析 token、require_user 依赖）
├── farm_system_auth.py   # 互刷系统独立 JWT 与账号状态复核
├── farm_system_routes.py # 互刷系统独立认证 API（默认关闭）
├── deps.py            # 依赖注入（Database、PlayerRepository 单例）
├── routes.py          # 迁移期遗留单联盟 API
├── alliance_routes.py # M2 带联盟上下文和字段权限的新 API
├── alliance_operations_routes.py # M6-M9 分享、人工认证、成员/套餐与平台运营 API
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
| `FARM_JWT_SECRET` | 互刷 JWT 独立签名密钥；未设时回退 `JWT_SECRET` | （64 位随机字符串） |
| `FARM_SYSTEM_ENABLED` | 是否开放互刷认证路由；默认 `false` | `false` |
| `FARM_SYSTEM_REGISTRATION_ENABLED` | 是否开放单部落登记；默认 `false`，必须独立于系统入口启用 | `false` |
| `FARM_SYSTEM_TIME_TOLERANCE_SECONDS` | 人工统一时间与官方战争时间最大误差；限制 60–7200 秒 | `2700` |
| `FARM_SYSTEM_ALLOWED_ACCOUNT_IDS` | 可选灰度账号 ID 白名单，逗号分隔；未设置表示不按账号限制 | `1,2` |

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

登录后的多联盟页面使用 `GET /api/alliances/{alliance_id}/farm-config`。该接口复用同一组本地
缓存组装逻辑，但配置来源严格限定为当前联盟订阅关系中 `category=farm` 的部落；没有互刷标签
部落时返回空 `clans`，不得回退到苍穹固定配置。接口不会触发 COC 或腾讯文档请求。

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
GET /api/alliances/{alliance_id}/wars/history?clan_tag=%232QQ
GET /api/alliances/{alliance_id}/wars/history/{clan_tag}/{war_key}
```

前两条旧接口无需认证。汇总接口返回每个已启用自有部落最近 15 场已结束普通战争的轻量摘要、分类和部落筛选元数据；详情接口返回单场完整阵容与攻防宽表。接口只读 `war_history_cache`，不直接调用外部 API。CWL、未结束战争和外部部落标签不会出现在历史列表。

登录后的联盟页面统一使用后两条联盟范围接口。它们必须携带 JWT，并从当前用户可访问的
`alliance_clans` 组装允许范围；苍穹与其他联盟执行完全相同的范围校验，不按联盟名称或
`alliance_key` 设置例外。

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

### 4.1 互刷系统独立认证（F1）

```text
POST /api/farm-system/auth/login
POST /api/farm-system/auth/logout
POST /api/farm-system/auth/change-password
GET  /api/farm-system/me
GET  /api/farm-system/clans
GET  /api/farm-system/admin/accounts
POST /api/farm-system/admin/accounts
PATCH /api/farm-system/admin/accounts/{account_id}
GET  /api/farm-system/admin/clans
POST /api/farm-system/admin/clans
PATCH /api/farm-system/admin/clans/{clan_tag}
POST /api/farm-system/admin/clans/{clan_tag}/transfer
GET  /api/farm-system/dashboard
POST /api/farm-system/admin/rounds
PATCH /api/farm-system/admin/rounds/{round_id}
GET  /api/farm-system/admin/rounds/{round_id}/results
POST /api/farm-system/rounds/{round_id}/clans/{clan_tag}/register
POST /api/farm-system/creator/matches/{match_id}/revoke
POST /api/farm-system/creator/rounds/{round_id}/cancel
POST /api/farm-system/creator/accounts/{account_id}/reset-password
```

互刷账号不复用微信 `openid`。令牌受众固定为 `farm-system`，载荷包含账号 ID（`sub`）、
`role` 和 `token_version`；每次访问均回查账号状态和当前令牌版本。微信 JWT 不能访问这些接口，
互刷 JWT 也不能通过微信 JWT 校验。互刷账号统一使用邮箱登录；登录失败按规范化邮箱执行进程内基础限流，邮箱不存在和密码错误
统一返回 `401`。密码变更返回新令牌并立即废止旧令牌。

全部接口受 `FARM_SYSTEM_ENABLED` 控制，未启用时返回 `404`。F1 不提供公开注册；账号通过
`scripts/manage_farm_account.py create` 受控创建，也可用同一脚本执行 `reset-password`、`enable` 和
`disable`。密码必须交互输入，不能作为命令行参数或写入日志。

`GET /clans` 始终按当前互刷账号 ID 过滤。`/admin/*` 需要 `admin` 或 `creator`；管理员不能
修改创建者，也不能提升账号角色，创建者可以在 `member / admin` 间调整角色。唯一创建者的初始化、
停用或转移不在页面 API 中完成。新增部落只接受 `clan_profile_cache` 中已由受控任务同步成功或保留
为 stale 的官方资料，HTTP 请求路径不会为了添加部落直接调用 COC API。转移部落仅改变当前归属，
原积分不清零。

`dashboard` 在无当前场次时返回当前账号已绑定的启用部落；创建场次后只返回当前账号在本轮快照
中的部落。管理员结果接口返回全联盟快照。创建场次时把带时区的北京时间转换为 UTC，并复制全部
启用参与部落。统一时间固定为“开始搜战时间”，
`business_time_kind` 只允许 `preparation_start`，登记时与官方 `preparationStartTime` 比较。

单部落登记接口额外受 `FARM_SYSTEM_REGISTRATION_ENABLED` 控制。它是用户显式写操作：读取官方
当前战争后校验普通战状态、统一时间和本轮快照，对内部对手原子写入双方结果与两笔积分流水；外部
对手写 `match_failed` 且积分不变。`not_in_war / war_mismatch / fetch_failed` 均可重试且不改积分。
重复登记直接返回已保存结果，不再次请求 COC 或重新随机。

一键登记第一版不新增批次 API：小程序只在当前账号范围内串行调用同一个单部落登记接口，逐项刷新，
单个失败不会终止后续部落。后端幂等和权限规则与单个登记完全一致。

`/creator/*` 只接受数据库实时角色为 `creator` 的互刷令牌。撤销匹配和整场取消必须填写原因，
通过反向积分流水恢复余额，不覆盖或删除原始流水；整场取消在单一事务中完成。密码重置递增
`token_version`，目标账号全部旧令牌立即失效。

灰度期间设置 `FARM_SYSTEM_ALLOWED_ACCOUNT_IDS` 后，登录和每次令牌复核都会检查当前账号 ID；移除账号
后已有令牌也立即失去访问权。该白名单不能替代两个功能开关。

---

### 5. 联盟上下文与权限接口（M2）

以下接口必须携带 JWT。JWT 中遗留的全局 `role` 只作旧接口兼容，新接口每次按
`openid` 从 `alliance_members`、`alliances`、`alliance_plans` 和 `alliance_clans`
重新读取当前权限：

```text
GET /api/me/alliances
POST /api/me/alliances/{alliance_id}/visit
GET /api/alliances/{alliance_id}
GET /api/alliances/{alliance_id}/clans
GET /api/alliances/{alliance_id}/clans/{clan_tag}
GET /api/alliances/{alliance_id}/members
GET /api/alliances/{alliance_id}/wars/current
GET /api/alliances/{alliance_id}/wars/current/{clan_tag}
GET /api/alliances/{alliance_id}/wars/history
GET /api/alliances/{alliance_id}/wars/history/{clan_tag}/{war_key}
GET /api/alliances/{alliance_id}/war-stats
GET /api/alliances/{alliance_id}/league-stats
GET /api/alliances/{alliance_id}/cwl/seasons
GET /api/alliances/{alliance_id}/cwl/seasons/{period}
POST /api/alliances/{alliance_id}/cwl/seasons/{period}
POST /api/alliances/{alliance_id}/cwl/seasons/{period}/copy-previous
POST /api/alliances/{alliance_id}/cwl/seasons/{period}/teams
PUT /api/alliances/{alliance_id}/cwl/seasons/{period}/teams/{team_id}
DELETE /api/alliances/{alliance_id}/cwl/seasons/{period}/teams/{team_id}
POST /api/alliances/{alliance_id}/cwl/seasons/{period}/teams/{team_id}/correct-tag
POST /api/alliances/{alliance_id}/cwl/seasons/{period}/confirm
GET /api/alliances/{alliance_id}/cwl/live
GET /api/alliances/{alliance_id}/cwl/live/{clan_tag}
POST /api/me/alliances
PATCH /api/me/alliances/{alliance_id}/visibility
PATCH /api/alliances/{alliance_id}
GET /api/alliances/{alliance_id}/subscription
PUT /api/alliances/{alliance_id}/subscription
POST /api/alliances/{alliance_id}/subscription/refresh
DELETE /api/alliances/{alliance_id}
```

`GET /api/me/alliances` 分别返回 `alliances`（首领、管理员、成员）和 `browsed_alliances`（无活跃成员
关系的浏览历史），两组各按最近访问倒序。浏览历史最多保留 50 条。旧 `hidden_alliances` 字段在迁移期
保留为空数组，前端不再使用隐藏/恢复模型。
`POST /api/me/alliances/{alliance_id}/visit` 可切换到有效成员关系或已有浏览历史，并记为最近访问和
默认联盟；不会创建成员关系或提升角色。`DELETE /api/me/alliance-history/{alliance_id}` 只删除非成员的
浏览历史；成员需使用退出接口，首领需输入联盟名称软删除联盟。

普通只读接口接受三类上下文：有效成员关系、已登录用户的浏览历史，或请求头 `X-Alliance-Share`
携带的有效分享令牌。三者的普通字段一致；访客上下文永远不授予管理字段。修改 URL 中的
`alliance_id` 或 `clan_tag` 仍不能越过令牌来源联盟和该联盟订阅部落范围，无权访问统一返回 `404`。

免费联盟写接口首先受 `ALLIANCE_FREE_ENABLED=true`（兼容旧名 `M5_FREE_ALLIANCE_ENABLED`）
环境总开关控制。内部测试账号可由 `M5_FREE_ALLIANCE_OPENIDS` 允许；外部用户还必须满足平台后台
`free_registration_enabled=true` 且未达到总配额。创建者是联盟
首领，但新订阅部落固定为 `unverified`，因此业务数据权限仍封顶为成员。免费联盟最多一个有效部落；
所有用户通过同一普通创建接口和左上角联盟下拉菜单时，最多创建一个有效免费联盟，超级管理员也不例外。
超级管理员只有通过 `/api/platform/alliances` 平台入口才可创建多个运营或测试联盟。
管理员或首领可修改 `normal / combat / farm / flat` 标签，也可先软移除再添加另一个 Tag。
移除会撤销当前联盟的部落认证关系，但不清理共享公共缓存或历史。

订阅接口在关系提交后只向 M4 队列提交部落资料、成员列表和当前战争初始化任务；已有新鲜公共缓存
直接复用。刷新接口默认只提交 `current_war`，返回 `202`、任务/缓存状态和共享冷却结果，不在 HTTP
请求中调用 COC。`pending / running / retry_wait / ready / partial / failed` 均表示真实异步状态。

`GET /api/alliances/{alliance_id}/members` 默认每页 100 人，最多 100 人，可用
`clan_tag` 或逗号分隔的 `clan_tags` 过滤，并兼容现有成员表格的 `membership_status`、
`search`、`sort_key` 和 `sort_order` 参数。基础成员、当前捐兵和赛季进攻数据属于
`member` 级别。只有当前用户在
联盟中是 `admin/leader` 且当前部落 `verification_status=verified` 时，响应才由后端显式
组装 `management` 对象，包含归属人、活动观察、历史分、最近普通战、最近三月联赛、
都城和竞赛趋势；这些历史摘要只统计当前联盟订阅部落，不能混入玩家在其他联盟部落的
记录。为兼容现有小程序表格，具备管理权限时这些已授权字段也会投影到成员对象顶层；
未认证部落即使是管理员也只返回成员字段。

部落列表、单部落详情、当前战争和普通战历史接口均返回联盟订阅顺序、类别及页面所需的筛选元数据。
单部落详情只能读取当前联盟已订阅部落，并继续复用全局部落资料缓存。

`GET /api/alliances/{alliance_id}/war-stats` 从当前联盟订阅关系中选择排序最前的
`category=combat` 战营部落，也可用 `clan_tag` 显式选择当前联盟的其他战营部落。响应同时返回
`combat_clans` 供后续多战营切换；没有战营部落时返回空统计，不回退到固定 `#2QQ` 或苍穹配置。
该接口与普通战历史接口都只读 `war_history_cache`、`member_war_facts` 和成员快照。

当前战争和当前月 CWL 属于协作数据，联盟成员可见。普通战成员历史、历史月份 CWL 和滚动联赛
统计属于评价数据，要求联盟管理员或首领权限，且至少存在对应已认证部落。互刷接口对普通成员和
未认证管理隐藏填坑号、不活跃与踢人候选。联盟查询接口只读 SQLite 缓存；写接口只写联盟关系、审计和持久化
队列，也不在请求路径调用 COC。

月度 CWL 队伍来自 `alliance_cwl_seasons`、`alliance_cwl_teams`，不要求出现在日常
`alliance_clans`，也不要求部落认证。联盟管理员和首领可配置当前月、下月；普通成员只读已确认
配置。发现官方联赛组后普通编辑被冻结，错误 Tag 只能通过带原因的审计纠正接口处理。
套餐中的 `max_cwl_teams` 控制每月上限，免费为 1、付费为 20。

苍穹现有 `league_teams` 继续作为报名编排快照和旧接口兼容来源，通过迁移脚本及以后每次编排
幂等同步到新表；临时壳子无需加入日常 12 部落。通用 CWL 汇总和详情不按联盟名称特判，也不从
日常订阅范围推断联赛队伍。

苍穹只保留 M1 存量迁移兼容：迁移时已有微信用户被映射为管理员。迁移完成后的新微信登录不会
自动加入苍穹；普通分享只写浏览历史，加入必须通过申请审核或管理员/首领邀请。

**错误码**：

- `401` — 未登录或 Token 无效；
- `403` — 请求历史/管理数据，但角色或逐部落认证不足；
- `404` — 联盟、成员关系或订阅部落不在当前用户范围；
- `409` — 免费联盟配额、生命周期或不允许的部落替换发生冲突；
- `422` — 分页或查询参数不合法。

### 5.1 分享、人工认证、成员和平台运营接口（M6～M9）

```text
POST   /api/alliance-shares/preview
POST   /api/alliance-shares/open
POST   /api/alliance-shares/join
GET    /api/alliances/{alliance_id}/verification
GET    /api/alliances/{alliance_id}/managed-clans
POST   /api/alliances/{alliance_id}/managed-clans
PUT    /api/alliances/{alliance_id}/managed-clans/order
PATCH  /api/alliances/{alliance_id}/managed-clans/{clan_tag}
DELETE /api/alliances/{alliance_id}/managed-clans/{clan_tag}
POST   /api/alliances/{alliance_id}/managed-clans/{clan_tag}/refresh
GET    /api/alliances/{alliance_id}/shares
POST   /api/alliances/{alliance_id}/shares
DELETE /api/alliances/{alliance_id}/shares/{link_id}
GET    /api/alliances/{alliance_id}/user-members
POST   /api/alliances/{alliance_id}/user-members
PATCH  /api/alliances/{alliance_id}/user-members/{member_id}
DELETE /api/alliances/{alliance_id}/user-members/{member_id}
POST   /api/alliances/{alliance_id}/join-requests
GET    /api/alliances/{alliance_id}/join-requests
PATCH  /api/alliances/{alliance_id}/join-requests/{request_id}
POST   /api/alliances/{alliance_id}/leave
DELETE /api/me/alliance-history/{alliance_id}

GET /api/platform/capability
GET /api/platform/alliances
GET /api/platform/alliances/{alliance_id}
PUT /api/platform/settings/free-registration
PUT /api/platform/alliances/{alliance_id}/verification
PUT /api/platform/alliances/{alliance_id}/plan
PUT /api/platform/alliances/{alliance_id}/status
DELETE /api/platform/alliances/{alliance_id}?confirmation_name=...
```

分享预览无需 JWT，只返回联盟名称、套餐名称、部落数量、分享类型和过期时间，不创建成员、不提交
同步任务。`open` 为已登录用户记录浏览历史，不自动加入；普通 `browse` 分享不能调用 `join`。
管理员或首领创建的 `invite` 在接收者确认后固定创建 `member`，不会继承分享者角色。`removed` 用户
需重新申请，`blocked` 用户不能通过邀请或申请恢复。令牌在 POST JSON 或普通只读请求头中传入，
数据库只保存摘要。

`verification` 用户接口只返回人工处理说明和当前状态。“申请部落认证”按钮不会调用验证码或自动
认证接口。只有平台管理员可通过平台接口设置 `verified / disputed / revoked / unverified`；平台
管理员来源为 `platform_admins`、`ALLIANCE_PLATFORM_ADMIN_OPENIDS`，迁移期可由 M5 内部白名单引导，
任何平台权限都不会替代联盟成员关系和逐部落业务权限。

认证冲突按入口区分：普通用户、联盟首领和管理员不能覆盖其他联盟已有的有效认证，后续接入自助认证时
必须返回冲突并提示联系超级管理员；平台人工认证接口允许超级管理员把同一部落认证给多个联盟，且不会
自动撤销其他联盟的认证。平台列表把这种状态显示为“多联盟认证”，超级管理员可在各联盟详情中逐个撤销。
数据库认证单位仍为 `(alliance_id, clan_tag)`，不对 `clan_tag` 单独建立已认证唯一约束。

联盟成员列表仅 `admin / leader` 可读且不返回他人的 OpenID。用户可在设置页复制自己的 OpenID，
首领据此直接添加普通成员或管理员，管理员只能添加普通成员。首领可以调整管理员或移交首领；
管理员只能移除普通成员。加入申请由管理员或首领批准或拒绝。普通成员和管理员可主动退出；首领
必须先移交或输入联盟名称软删除联盟。免费或有效付费联盟的管理员/首领
可通过统一接口新增、软移除、修改业务标签和调整顺序；免费套餐最多 1 个有效部落，付费套餐当前
最多 10 个。新增或重新启用的部落默认未认证并通过 M4 队列初始化。`internal` 套餐由系统配置，
不允许在小程序中修改，防止误改苍穹存量配置。平台套餐接口是人工运营入口，不是在线支付接口。

通用部落管理响应为免费套餐的有效部落附带三项本地同步状态，并通过 `manual_refresh_available` 明确
是否允许手动刷新。通用刷新接口当前只对免费联盟的管理员或首领开放，只向全局去重队列提交任务并遵守
共享冷却，不在 HTTP 请求中调用 COC；普通成员返回 `403`，自动高频套餐返回 `409`。旧
`/subscription` 三个接口继续兼容已发布小程序，新版前端不再使用其管理页面。

平台部落管理使用 `/api/platform/alliances/{alliance_id}/managed-clans` 专用接口。它只接受超级管理员，
不要求操作者先成为目标联盟成员，并可添加、软移除、修改标签和调整顺序。平台添加不受目标联盟套餐
部落数量限制，数据库通过 `alliances.clan_limit_override` 记录逐联盟扩容；普通联盟管理接口仍严格执行
免费 1 个、付费 10 个的套餐上限。所有平台部落变更同时写入联盟审计和平台审计。

超级管理的联盟删除采用“先停用、再删除”两阶段规则。状态接口只允许在 `active / suspended`
之间切换；删除接口只接受已经停用且 `confirmation_name` 与联盟完整名称一致的目标。删除是软归档：
撤销有效分享、取消待处理加入申请、停止联盟同步需求、退出当前成员并从普通平台列表移除，但不删除
公共战争、联赛等历史事实及审计记录。已归档联盟不能通过状态接口恢复。

### 6. 绑定游戏账号

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

互刷令牌使用独立的 `aud=farm-system` 和 `require_farm_account` 依赖；即使签名密钥暂时回退为
`JWT_SECRET`，两类令牌也不能互换。生产环境应显式配置强 `JWT_SECRET` 和 `FARM_JWT_SECRET`。

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

互刷认证相关的 `farm_auth_accounts`、`farm_clans` 和 `farm_audit_logs` 见
[`02-database.md`](02-database.md#互刷系统独立认证底座f1)。

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
