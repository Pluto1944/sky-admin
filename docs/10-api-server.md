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

无需认证。返回服务状态和时间戳。

**响应示例**：
```json
{
  "status": "ok",
  "service": "sky-admin-api",
  "timestamp": "2026-08-08T08:00:00+00:00"
}
```

---

### 2. 成员列表

```
GET /api/members
```

无需认证。从 `accounts` 表读取所有成员信息。

**响应示例**：
```json
{
  "count": 50,
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
- `500` — 数据库查询失败

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
