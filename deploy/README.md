# Sky Admin 部署文档

## 架构

```
用户/小程序
      │
      ▼
  Nginx :80 (公网入口)
      │ proxy_pass
      ▼
  FastAPI :8000 (127.0.0.1, 不对外)
      │
      ▼
  SQLite (data/league.db)
```

- Nginx 监听 80 端口，反代到 FastAPI
- FastAPI 只监听 127.0.0.1，不直接暴露公网
- systemd 守护进程，开机自启 + 挂了自动重启

## 前置条件

- 腾讯云轻量服务器 Ubuntu 22.04
- 安全组开放端口：22（SSH）、80（HTTP）、ICMP（Ping）
- 代码已上传到 `/opt/sky-admin/sky-admin/`

## 部署步骤

### 1. 上传代码到服务器

在**本地电脑**执行：

```bash
# 打包上传（在 sky-admin 项目根目录执行）
cd /Users/boyyang/Desktop/project/code/sky-admin
scp -r sky-admin/ root@你的服务器IP:/opt/
```

### 2. 登录服务器执行部署

```bash
ssh root@你的服务器IP
cd /opt/sky-admin/sky-admin
bash deploy/deploy.sh
```

脚本自动完成：
- 更新系统包
- 安装 Python3 + Nginx
- 创建虚拟环境并安装依赖
- 配置 Nginx 反代
- 配置 systemd 守护
- 启动服务

### 3. 验证

```bash
# 本地测试
curl http://服务器IP/api/ping

# 预期返回
# {"status":"ok","message":"Sky Admin API is running"}
```

### 4. 浏览器访问

```
http://你的服务器IP/api/members
```

---

## 域名 + HTTPS 切换（域名审核通过后）

### 第一步：DNS 解析

在腾讯云域名控制台添加 A 记录：

| 主机记录 | 记录类型 | 记录值 |
|---------|---------|--------|
| `api` | A | 你的服务器公网 IP |

### 第二步：安全组加 443

在服务器防火墙添加规则：

| 端口 | 协议 | 来源 |
|-----|------|-----|
| 443 | TCP | 0.0.0.0/0 |

### 第三步：安装 certbot

```bash
apt install -y certbot python3-certbot-nginx
```

### 第四步：修改 Nginx 配置

编辑 `/etc/nginx/sites-available/sky-admin`：
1. 注释掉 HTTP 模式的 `server` 块
2. 取消注释 HTTPS 模式的两个 `server` 块
3. 把 `YOUR_DOMAIN` 替换为你的实际域名

### 第五步：申请证书

```bash
certbot --nginx -d api.你的域名.com
```

### 第六步：验证

```bash
curl https://api.你的域名.com/api/ping
```

---

## 运维命令

### 服务管理

```bash
systemctl status sky-admin       # 查看服务状态
systemctl restart sky-admin      # 重启服务
systemctl stop sky-admin         # 停止服务
systemctl start sky-admin        # 启动服务
```

### 日志查看

```bash
journalctl -u sky-admin -f       # 实时查看 systemd 日志
tail -f /var/log/sky-admin.log   # 查看应用日志
tail -f /var/log/nginx/sky-admin-access.log  # Nginx 访问日志
tail -f /var/log/nginx/sky-admin-error.log   # Nginx 错误日志
```

### Nginx 管理

```bash
nginx -t                         # 测试配置是否正确
systemctl reload nginx           # 重载配置（不中断服务）
systemctl restart nginx          # 重启 Nginx
```

---

## 更新代码

```bash
ssh root@你的服务器IP
cd /opt/sky-admin/sky-admin
git pull                          # 拉取最新代码
systemctl restart sky-admin       # 重启服务
```

如果没用 git，重新 scp 上传后重启即可。

---

## 故障排查

### 服务启动失败

```bash
# 查看错误日志
journalctl -u sky-admin -n 50 --no-pager

# 手动启动测试
cd /opt/sky-admin/sky-admin
source venv/bin/activate
uvicorn api_server.app:app --host 127.0.0.1 --port 8000
```

### Nginx 502 Bad Gateway

说明 Nginx 连不上 FastAPI：
```bash
# 确认 FastAPI 在运行
systemctl status sky-admin
# 确认端口在监听
netstat -tlnp | grep 8000
```

### 无法访问

```bash
# 检查防火墙
ufw status
# 检查安全组（在腾讯云控制台看）
```
