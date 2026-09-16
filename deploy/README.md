# Sky Admin 部署与运维文档

> 域名: `api.skycoc.cc` | 服务器: 腾讯云轻量 Ubuntu 22.04

---

## 一、架构总览（一句话版）

```
小程序 → https://api.skycoc.cc → Nginx(:443) → FastAPI(:8000) → SQLite
```

> **备案过渡期**（备案未通过时）：走 IP 直连 `https://115.159.64.19`，见「三·五、备案过渡期（IP 直连方案）」。

- **Nginx**：公网入口，处理 HTTPS，转发请求到 FastAPI
- **FastAPI**：Python 后端，只监听 127.0.0.1:8000（不直接对外）
- **systemd**：守护 FastAPI 进程（sky-admin）与周期调度器（sky-scheduler），挂了自动重启，开机自启
- **certbot**：自动管理 SSL 证书，到期自动续期

---

## 二、前置条件

- 腾讯云轻量服务器 Ubuntu 22.04
- 安全组开放端口：**22**（SSH）、**80**（HTTP）、**443**（HTTPS）、ICMP（Ping）
- 域名 DNS 已添加 A 记录：`api.skycoc.cc → 服务器公网 IP`
- 代码在服务器上：`/home/ubuntu/YANG/sky-admin/`

---

## 三、首次部署

### 方式一：一键脚本

```bash
sudo bash /home/ubuntu/YANG/sky-admin/deploy/deploy.sh
```

脚本会自动完成：安装依赖 → 创建 venv → 配置 Nginx → 配置 systemd → 申请 SSL 证书。

### 方式二：手动分步

```bash
# 1. 安装系统包
sudo apt update && sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 2. 安装 Python 依赖
cd /home/ubuntu/YANG/sky-admin
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 3. 配置 Nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/sky-admin
sudo ln -sf /etc/nginx/sites-available/sky-admin /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 4. 配置 systemd
sudo cp deploy/sky-admin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sky-admin
sudo systemctl start sky-admin

# 5. 配置周期调度器（可选，同步数据用）
sudo cp deploy/sky-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sky-scheduler
sudo systemctl start sky-scheduler

# 6. 申请 HTTPS 证书
sudo certbot --nginx -d api.skycoc.cc
```

---

## 三·五、备案过渡期（IP 直连方案）

> 适用场景：小程序/域名备案尚未通过，暂时无法用 `api.skycoc.cc` 域名访问。

### 背景

备案通过前，小程序无法通过域名 `api.skycoc.cc` 访问后端，因此临时采用 **IP 直连 + HTTPS** 方案：

```
小程序/前端 → https://115.159.64.19 → Nginx(:443) → FastAPI(:8000) → SQLite
```

### 现状说明（截至 2026-09-12）

- **对外入口**：`https://115.159.64.19`（Nginx 监听 443，带 SSL 证书）
- **Nginx 配置**：使用仓库中的 `deploy/nginx-ip.conf`，反代到 `127.0.0.1:8000`
- **FastAPI**：正常由 systemd 托管，监听 `127.0.0.1:8000`（不直接对外）
- **HTTPS 证书**：使用 Let's Encrypt 的短期 IP 证书
  （`/etc/letsencrypt/live/115.159.64.19/`），有效期约 6 天，必须保持自动续期正常

### IP 直连 server 块（临时）

```nginx
server {
    listen 443 ssl http2 default_server;
    server_name 115.159.64.19;

    ssl_certificate     /etc/letsencrypt/live/115.159.64.19/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/115.159.64.19/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### 重要提醒

1. **FastAPI 只监听 `127.0.0.1:8000`，外网无法直接访问 8000 端口**。小程序/前端必须通过 `https://115.159.64.19` 走 Nginx 反代，不要配 `http://IP:8000`。
2. **不要手动用 `uvicorn --reload` 起进程**。历史上曾因手动起的 `0.0.0.0:8000 --reload` 进程占用端口，导致 systemd 的 `sky-admin` 服务崩溃循环（重启 11 万+ 次）。开发调试需先 `sudo systemctl stop sky-admin`，且结束后用 systemd 恢复托管。
3. **备案通过后切换回域名**：删掉 Nginx 配置里的 IP 直连 server 块，回到 `api.skycoc.cc` 域名架构（见本文档「三、首次部署」），小程序里 API 地址改为 `https://api.skycoc.cc`。
4. **IP 证书必须自动续期**：IP 证书需要 Certbot 5.4 或更高版本，并使用
   `shortlived` profile；续期后必须 reload Nginx。用 `sudo certbot renew --dry-run`
   定期验证续期链路。

### 验证命令

```bash
# 直连本机 FastAPI
curl http://127.0.0.1:8000/api/ping

# 通过 Nginx IP 直连（当前过渡期入口）
curl https://115.159.64.19/api/ping
```

---

## 四、运维命令速查

### 1. sky-admin 服务管理（FastAPI 后端）

```bash
# 查看服务状态（是否在运行、运行了多久）
sudo systemctl status sky-admin

# 停止服务
sudo systemctl stop sky-admin

# 启动服务
sudo systemctl start sky-admin

# 重启服务（修改代码后执行这个）
sudo systemctl restart sky-admin

# 开机自启（已配置，不用管）
sudo systemctl enable sky-admin
```

### 2. sky-scheduler 服务管理（周期数据刷新调度器）

```bash
# 查看调度器状态
sudo systemctl status sky-scheduler

# 停止 / 启动 / 重启（修改代码后重启）
sudo systemctl stop sky-scheduler
sudo systemctl start sky-scheduler
sudo systemctl restart sky-scheduler

# 开机自启
sudo systemctl enable sky-scheduler
```

调度器统一管理 **4 类周期刷新任务**，状态落 `sync_jobs` 表（设计详见 `docs/15-scheduler.md`）：

| job_id | 说明 | 频率 |
|--------|------|------|
| `farm_stats` | 互刷部落统计 | 每 30 分钟 |
| `coc_sync` | COC 玩家档案 | 每 6 小时 |
| `war_results` | 普通部落战战绩 | 每天 |
| `cwl` | CWL 联赛战绩 | 每天触发，仅 12 号真正拉取 |

任务本身的状态管理（查看/手动触发/启停单个任务）用 CLI，无需动 systemd：

```bash
cd /home/ubuntu/YANG/sky-admin
venv/bin/python scripts/scheduler.py --list                       # 查看任务状态
venv/bin/python scripts/scheduler.py --once farm_stats            # 手动触发某任务
venv/bin/python scripts/scheduler.py --once all                   # 手动触发全部任务
venv/bin/python scripts/scheduler.py --once cwl --force           # 强制拉当月 CWL（跳过 12 号判断）
venv/bin/python scripts/scheduler.py --disable war_results        # 停用某任务
venv/bin/python scripts/scheduler.py --enable farm_stats          # 启用某任务
venv/bin/python scripts/scheduler.py --set-interval farm_stats 60 # 调整频率（分钟）
```

CLI 参数说明：

| 参数 | 说明 |
|------|------|
| （无参数） | loop 常驻模式（生产，由 systemd 守护，勿手动再起） |
| `--once <job_id\|all>` | 单次执行（不进入常驻循环），调试/补数据用 |
| `--force` | 搭配 `--once` 使用，跳过 CWL 的 `day==12` 判断 |
| `--list` | 打印 `sync_jobs` 表全部任务状态（含 `last_error` 报错原因） |
| `--enable` / `--disable` | 切换任务启用状态 |
| `--set-interval <分钟>` | 调整任务刷新间隔 |

### 3. 查看日志

**sky-admin（FastAPI 后端）：**

```bash
# 【最常用】实时查看 FastAPI 日志（Ctrl+C 退出）
sudo journalctl -u sky-admin -f

# 查看最近 50 行日志
sudo journalctl -u sky-admin -n 50 --no-pager

# 查看应用写入的日志
sudo tail -f /var/log/sky-admin.log
sudo tail -f /var/log/sky-admin-error.log
```

**sky-scheduler（周期调度器）：**

```bash
# 实时查看调度器日志
sudo journalctl -u sky-scheduler -f

# 查看最近 50 行日志
sudo journalctl -u sky-scheduler -n 50 --no-pager

# 查看应用写入的日志
sudo tail -f /var/log/sky-scheduler.log
sudo tail -f /var/log/sky-scheduler-error.log
```

**Nginx（公网入口）：**

```bash
# 查看 Nginx 访问日志（谁在调 API）
sudo tail -f /var/log/nginx/sky-admin-access.log

# 查看 Nginx 错误日志（出问题时看这个）
sudo tail -f /var/log/nginx/sky-admin-error.log
```

### 4. Nginx 管理

```bash
# 测试配置是否正确（改完 nginx 配置后先跑这个）
sudo nginx -t

# 重载配置（不中断服务，修改配置后执行）
sudo systemctl reload nginx

# 重启 Nginx（会短暂中断）
sudo systemctl restart nginx

# 停止 Nginx
sudo systemctl stop nginx

# 启动 Nginx
sudo systemctl start nginx
```

### 5. 端口与进程检查

```bash
# 查看哪些端口在监听
sudo ss -tlnp

# 只看关键端口
sudo ss -tlnp | grep -E '80|443|8000'

# 查看 FastAPI 进程
ps aux | grep uvicorn

# 查看调度器进程
ps aux | grep scheduler.py

# 查看 Nginx 进程
ps aux | grep nginx
```

### 6. 手动测试

**sky-admin（FastAPI 后端）：**

```bash
# 测试 FastAPI 是否正常（直接在服务器上）
curl http://127.0.0.1:8000/api/ping

# 测试通过 Nginx 代理
curl http://127.0.0.1/api/ping

# 测试公网 HTTPS
curl https://api.skycoc.cc/api/ping

# 测试公网 HTTP（会自动跳转 HTTPS）
curl -I http://api.skycoc.cc/api/ping
```

**sky-scheduler（周期调度器）：**

```bash
cd /home/ubuntu/YANG/sky-admin
# 查看任务状态（能正常列出即调度器可正常读写库）
venv/bin/python scripts/scheduler.py --list

# 手动触发某任务（验证单任务执行链路）
venv/bin/python scripts/scheduler.py --once farm_stats
```

---

## 五、日常维护

### 更新代码

```bash
cd /home/ubuntu/YANG/sky-admin
git pull                              # 拉取最新代码
sudo systemctl restart sky-admin      # 重启 FastAPI 生效
sudo systemctl restart sky-scheduler  # 重启调度器生效（若调度器相关代码有改动）
```

### SSL 证书

```bash
# 查看证书到期时间
sudo certbot certificates

# 手动续期（一般不需要，certbot 会自动续）
sudo certbot renew

# 测试自动续期是否正常（dry-run 不会真正续期）
sudo certbot renew --dry-run
```

---

## 六、故障排查

### 场景 1：接口访问不了，返回什么也没有

**检查链路**：从里到外逐步排查

```bash
# 第 1 步：FastAPI 活着吗？
curl http://127.0.0.1:8000/api/ping
# 如果失败 → sudo systemctl restart sky-admin
# 再失败 → 看日志：sudo journalctl -u sky-admin -n 50

# 第 2 步：Nginx 活着吗？
sudo systemctl status nginx
# 如果没跑 → sudo systemctl start nginx

# 第 3 步：从公网能访问吗？
curl https://api.skycoc.cc/api/ping
# 如果第 1 步通但第 3 步不通 → 检查安全组 443 端口
```

### 场景 2：修改了代码但不生效

```bash
sudo systemctl restart sky-admin
# 重启后确认状态
sudo systemctl status sky-admin
```

### 场景 3：报错 502 Bad Gateway

说明 Nginx 连不上 FastAPI：

```bash
# 确认 FastAPI 在跑
sudo systemctl status sky-admin
# 确认 8000 端口在监听
sudo ss -tlnp | grep 8000
# 如果没监听，重启服务
sudo systemctl restart sky-admin
```

### 场景 4：服务频繁挂掉

```bash
# 查看错误日志找原因
sudo journalctl -u sky-admin -n 100 --no-pager | tail -50
# 常见原因：数据库被锁、内存不足、.env 配置错误
```

### 场景 5：SSL 证书过期

```bash
# 手动续期
sudo certbot renew
# 重载 Nginx 使新证书生效
sudo systemctl reload nginx
```

### 场景 6：修改了 .env 文件

```bash
# 修改 .env 后必须重启服务才能生效
sudo systemctl restart sky-admin
sudo systemctl restart sky-scheduler
```

### 场景 7：数据没按时刷新（sky-scheduler）

```bash
# 第 1 步：调度器活着吗？
sudo systemctl status sky-scheduler
# 如果没跑 → sudo systemctl start sky-scheduler

# 第 2 步：任务状态如何（重点看 last_status / last_error / next_run_at）
cd /home/ubuntu/YANG/sky-admin
venv/bin/python scripts/scheduler.py --list
# 若 last_status=failed → 看 last_error 列的报错原因
# 若 next_run_at 尚未到期 → 属正常等待，无需处理

# 第 3 步：手动触发验证
venv/bin/python scripts/scheduler.py --once farm_stats
```

### 场景 8：调度器频繁重启（sky-scheduler）

```bash
# 查看调度器日志找原因
sudo journalctl -u sky-scheduler -n 100 --no-pager | tail -50
sudo tail -f /var/log/sky-scheduler-error.log
# 常见原因：.env 缺失、数据库被锁、依赖未安装
```

---

## 七、配置文件位置

| 文件 | 位置 | 作用 |
|------|------|------|
| 项目代码 | `/home/ubuntu/YANG/sky-admin/` | Python 后端代码 |
| .env | `/home/ubuntu/YANG/sky-admin/.env` | 密钥、Token 等敏感配置 |
| 数据库 | `/home/ubuntu/YANG/sky-admin/data/league.db` | SQLite 数据库 |
| Nginx 配置 | `/etc/nginx/sites-available/sky-admin` | Nginx 站点配置（含备案过渡期 IP 直连 server 块） |
| systemd 服务 | `/etc/systemd/system/sky-admin.service` | 守护进程配置 |
| systemd 调度器 | `/etc/systemd/system/sky-scheduler.service` | 周期调度器守护配置 |
| 调度器脚本 | `/home/ubuntu/YANG/sky-admin/scripts/scheduler.py` | 周期调度器核心脚本（CLI + 常驻循环） |
| FastAPI 日志 | `/var/log/sky-admin.log` | 应用标准输出日志 |
| FastAPI 错误 | `/var/log/sky-admin-error.log` | 应用错误日志 |
| 调度器日志 | `/var/log/sky-scheduler.log` | 调度器标准输出日志 |
| 调度器错误 | `/var/log/sky-scheduler-error.log` | 调度器错误日志 |
| Nginx 访问日志 | `/var/log/nginx/sky-admin-access.log` | 请求记录 |
| Nginx 错误日志 | `/var/log/nginx/sky-admin-error.log` | Nginx 错误 |
| SSL 证书 | `/etc/letsencrypt/live/api.skycoc.cc/` | HTTPS 证书 |

---

## 八、从零重建（换服务器时用）

本节适用于全新 Ubuntu 主机。旧服务器发生过安全事件时，不能复制 `/etc`、SSH 配置、旧 TLS
私钥、虚拟环境或系统二进制；只迁移经过校验的源码、配置键名和 SQLite 数据，并轮换所有 Secret。

### 8.1 重装前的最终备份

先记录 Git 状态和当前依赖版本：

```bash
git -C /home/ubuntu/YANG/sky-admin status --short --branch
git -C /home/ubuntu/YANG/sky-admin rev-parse HEAD
/home/ubuntu/YANG/sky-admin/venv/bin/pip freeze > /home/ubuntu/sky-admin-pip-freeze.txt
```

`requirements.txt` 当前使用最低版本范围，并非完全锁定；`pip freeze` 只用于重建后的版本对照和
排障，不应在发生过入侵的旧主机上直接生成可执行信任链。

在维护窗口停止两个写入服务，并使用 SQLite Online Backup API 创建一致快照：

```bash
sudo systemctl stop sky-scheduler sky-admin
install -d -m 0700 /home/ubuntu/sky-admin-rebuild-export

/home/ubuntu/YANG/sky-admin/venv/bin/python - <<'PY'
import sqlite3

source = sqlite3.connect("file:/home/ubuntu/YANG/sky-admin/data/league.db?mode=ro", uri=True)
target = sqlite3.connect("/home/ubuntu/sky-admin-rebuild-export/league.db")
with target:
    source.backup(target)
target.close()
source.close()
PY

git -C /home/ubuntu/YANG/sky-admin bundle create \
  /home/ubuntu/sky-admin-rebuild-export/sky-admin.bundle --all
(cd /home/ubuntu/sky-admin-rebuild-export && \
  sha256sum league.db sky-admin.bundle > SHA256SUMS)
chmod 0600 /home/ubuntu/sky-admin-rebuild-export/*
```

用同一 Python 环境执行完整性检查：

```bash
/home/ubuntu/YANG/sky-admin/venv/bin/python - <<'PY'
import sqlite3
db = sqlite3.connect("file:/home/ubuntu/sky-admin-rebuild-export/league.db?mode=ro", uri=True)
print(db.execute("PRAGMA integrity_check").fetchone()[0])
db.close()
PY
```

从 Mac 主动拉取，不允许旧服务器反向登录 Mac：

```bash
REBUILD_OLD_SERVER="ubuntu@旧服务器IP"
REBUILD_MAC_DIR="/Users/你的用户名/Backups/sky-admin-rebuild"
mkdir -p "$REBUILD_MAC_DIR"
scp -p "${REBUILD_OLD_SERVER}:/home/ubuntu/sky-admin-rebuild-export/*" "$REBUILD_MAC_DIR/"
cd "$REBUILD_MAC_DIR"
shasum -a 256 -c SHA256SUMS
```

若不立即重装，重新启动服务并确认状态：

```bash
sudo systemctl start sky-admin sky-scheduler
sudo systemctl --no-pager --full status sky-admin sky-scheduler
```

2026-09-12 审计时 sky-admin HEAD 为
`444238c8b9d6819fdcd45562d8c7b8bdabcb7068`。重装前必须重新记录最终 HEAD；当前本地分支曾领先
远端，不能只依赖 GitHub，必须保留 Git bundle。

### 8.2 新服务器安全基线

1. 创建 `ubuntu` 管理用户，只安装新的 SSH 公钥；关闭 SSH 密码登录和 root 登录。
2. 安装系统安全更新，只在云安全组和主机防火墙开放 22、80、443。
3. 8000 端口只能监听 `127.0.0.1`，不得加入安全组或直接暴露公网。
4. 先把代码和数据库恢复到固定路径，再运行部署脚本。
5. DNS 切换放在本机验收之后，避免半成品接收生产流量。

### 8.3 恢复可信代码

优先从已经校验的 bundle 恢复，因为远端仓库可能缺少本地提交：

```bash
REBUILD_NEW_SERVER="ubuntu@新服务器IP"
REBUILD_MAC_DIR="/Users/你的用户名/Backups/sky-admin-rebuild"
ssh "$REBUILD_NEW_SERVER" 'install -d -m 0700 /home/ubuntu/sky-admin-rebuild-import'
scp -p "$REBUILD_MAC_DIR/sky-admin.bundle" "$REBUILD_MAC_DIR/league.db" \
  "$REBUILD_MAC_DIR/SHA256SUMS" \
  "$REBUILD_NEW_SERVER:/home/ubuntu/sky-admin-rebuild-import/"
ssh "$REBUILD_NEW_SERVER"
```

以下命令在新服务器执行：

```bash
cd /home/ubuntu/sky-admin-rebuild-import
sha256sum -c SHA256SUMS
sudo install -d -o ubuntu -g ubuntu /home/ubuntu/YANG
git bundle verify /home/ubuntu/sky-admin-rebuild-import/sky-admin.bundle
git clone /home/ubuntu/sky-admin-rebuild-import/sky-admin.bundle \
  /home/ubuntu/YANG/sky-admin
git -C /home/ubuntu/YANG/sky-admin status --short --branch
git -C /home/ubuntu/YANG/sky-admin rev-parse HEAD
```

确认 HEAD 与重装前 manifest 完全一致。不要从旧主机复制 `venv/`、缓存、日志或 `__pycache__`。

### 8.4 重建配置并轮换 Secret

`.env.example` 只提供基础模板，不覆盖生产启用的全部功能。根据实际使用情况逐项创建新值，至少核对：

- `COC_API_TOKEN`；
- 强随机 `JWT_SECRET`；
- `WECHAT_APP_ID` / `WECHAT_APP_SECRET`，以及兼容键 `WECHAT_APPID` / `WECHAT_SECRET`；
- 腾讯文档的 Client、Access Token、Open ID、文档 ID 和 Sheet；
- X/Twitter Bearer Token、作者或用户 ID；
- SocialData API Key 和限额；
- 战争阵型来源与发布文档配置。

只从官方控制台签发新 Token。不要从旧 `.env` 复制值；旧文件只能用于确认启用了哪些键。完成后：

```bash
chmod 0600 /home/ubuntu/YANG/sky-admin/.env
chown ubuntu:ubuntu /home/ubuntu/YANG/sky-admin/.env
```

不得在终端、Git diff、日志或文档中打印真实值。生产环境必须显式设置强 `JWT_SECRET`。

### 8.5 恢复数据库

把已校验的 Online Backup 快照复制到新主机：

```bash
install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/YANG/sky-admin/data
install -o ubuntu -g ubuntu -m 0600 \
  /home/ubuntu/sky-admin-rebuild-import/league.db \
  /home/ubuntu/YANG/sky-admin/data/league.db
```

用系统 Python 在安装服务前做只读完整性检查：

```bash
python3 - <<'PY'
import sqlite3
db = sqlite3.connect("file:/home/ubuntu/YANG/sky-admin/data/league.db?mode=ro", uri=True)
print(db.execute("PRAGMA integrity_check").fetchone()[0])
db.close()
PY
```

结果必须只有 `ok`。不要运行 `python cli.py reset-db`，它会清空历史数据。

### 8.6 部署服务

部署脚本固定使用 `/home/ubuntu/YANG/sky-admin`，会安装 Python/Nginx/Certbot、创建全新 venv、
安装依赖、复制 systemd 模板并申请新证书：

```bash
bash -n /home/ubuntu/YANG/sky-admin/deploy/deploy.sh
sudo bash /home/ubuntu/YANG/sky-admin/deploy/deploy.sh
```

脚本包含 `apt upgrade -y`，应在已确认的维护窗口执行。证书必须在新主机重新申请，不要复制旧
`/etc/letsencrypt` 私钥。若 DNS 尚未切换，Certbot 失败不会阻止 HTTP 服务启动，稍后再执行：

```bash
sudo certbot --nginx -d api.skycoc.cc
```

### 8.7 Nginx 与备案过渡期

仓库 `deploy/nginx.conf` 是域名部署模板。旧生产配置额外包含本章“三·五”中的 IP 直连 443
`server` 块，一键脚本不会自动添加。只有确实仍需备案过渡期 IP 入口时才手工加入，并注意域名证书
用于 IP URL 会产生主机名不匹配；正式环境应使用 `https://api.skycoc.cc`。

无论是否启用临时 IP 块，都必须先执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 8.8 DNS 切换前验收

```bash
sudo systemctl is-enabled sky-admin sky-scheduler nginx
sudo systemctl is-active sky-admin sky-scheduler nginx
curl --fail --show-error http://127.0.0.1:8000/api/ping
curl --fail --show-error -H 'Host: api.skycoc.cc' http://127.0.0.1/api/ping
sudo ss -lntp | grep -E ':(80|443|8000)\b'
sudo journalctl -u sky-admin -u sky-scheduler -n 100 --no-pager
```

验收条件：

- 三个服务均为 enabled/active；
- FastAPI 只监听 `127.0.0.1:8000`；
- 本机 API 和 Nginx 反代均返回成功；
- 日志没有 `.env` 缺失、数据库锁、迁移失败或持续重启；
- `league.db` 完整性为 `ok`，关键历史记录数量与旧机最终 manifest 一致；
- 调度器能列出任务状态，但不要在验收中随意触发会写外部系统的任务。

本机验收通过后再把 `api.skycoc.cc` A 记录切到新 IP，申请/确认新证书，并执行：

```bash
curl --fail --show-error https://api.skycoc.cc/api/ping
sudo certbot renew --dry-run
```

观察一个完整调度周期且无异常后，才能销毁旧服务器。
