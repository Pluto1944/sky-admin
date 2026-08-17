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

### 现状说明（截至 2026-08-17）

- **对外入口**：`https://115.159.64.19`（Nginx 监听 443，带 SSL 证书）
- **Nginx 配置**：`/etc/nginx/sites-enabled/sky-admin` 中额外增加了一个 `server_name 115.159.64.19` 的 server 块，反代到 `127.0.0.1:8000`
- **FastAPI**：正常由 systemd 托管，监听 `127.0.0.1:8000`（不直接对外）
- **HTTPS 证书**：临时复用 `api.skycoc.cc` 的证书（`/etc/letsencrypt/live/api.skycoc.cc/`）

### IP 直连 server 块（临时）

```nginx
server {
    listen 443 ssl http2 default_server;
    server_name 115.159.64.19;

    ssl_certificate     /etc/letsencrypt/live/api.skycoc.cc/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.skycoc.cc/privkey.pem;
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

### 验证命令

```bash
# 直连本机 FastAPI
curl http://127.0.0.1:8000/api/ping

# 通过 Nginx IP 直连（当前过渡期入口）
curl -k https://115.159.64.19/api/ping
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

假设换了新服务器，需要重新部署：

1. **安全组开放端口**：22、80、443
2. **DNS 解析**：`api.skycoc.cc` A 记录指向新服务器 IP
3. **上传代码**：
   ```bash
   scp -r sky-admin/ ubuntu@新IP:/home/ubuntu/YANG/
   # 记得单独传 .env 和 data/league.db
   ```
4. **运行部署脚本**：
   ```bash
   sudo bash /home/ubuntu/YANG/sky-admin/deploy/deploy.sh
   ```
5. **验证**：
   ```bash
   curl https://api.skycoc.cc/api/ping
   ```
