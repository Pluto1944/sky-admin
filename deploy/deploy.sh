#!/bin/bash
set -e

echo "========================================"
echo "  Sky Admin 一键部署脚本"
echo "========================================"
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ---- 配置区域：修改这里适配你的环境 ----
PROJECT_DIR="/home/ubuntu/YANG/sky-admin"
DOMAIN="api.skycoc.cc"
CERT_EMAIL="admin@skycoc.cc"
# ---------------------------------------

# 检查是否为 root
if [ "$(id -u)" != "0" ]; then
    echo "错误：请使用 root 用户执行此脚本"
    exit 1
fi

# 检查项目目录是否存在
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}错误：项目目录不存在 $PROJECT_DIR${NC}"
    echo "请先将代码上传到该目录，或修改脚本中的 PROJECT_DIR"
    exit 1
fi

# 1. 更新系统
echo -e "${GREEN}[1/8] 更新系统包...${NC}"
apt update && apt upgrade -y

# 2. 安装系统依赖
echo -e "${GREEN}[2/8] 安装 Python3 + Nginx + Certbot...${NC}"
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 3. 创建虚拟环境并安装 Python 依赖
echo -e "${GREEN}[3/8] 安装 Python 依赖...${NC}"
cd "$PROJECT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 4. 配置 Nginx（先用 HTTP 模板）
echo -e "${GREEN}[4/8] 配置 Nginx...${NC}"
cp deploy/nginx.conf /etc/nginx/sites-available/sky-admin
ln -sf /etc/nginx/sites-available/sky-admin /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# 5. 配置 systemd 服务
echo -e "${GREEN}[5/8] 配置 systemd 守护进程...${NC}"
cp deploy/sky-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sky-admin

# 6. 启动服务
echo -e "${GREEN}[6/8] 启动 FastAPI 服务...${NC}"
systemctl restart sky-admin
sleep 2
systemctl status sky-admin --no-pager

# 7. 申请 HTTPS 证书（需要域名 DNS 已生效 + 安全组已开放 443）
echo -e "${GREEN}[7/8] 申请 HTTPS 证书...${NC}"
if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$CERT_EMAIL" 2>/dev/null; then
    echo -e "${GREEN}HTTPS 证书申请成功！${NC}"
else
    echo -e "${YELLOW}HTTPS 证书申请失败（可能 DNS 未生效或 443 端口未开放）${NC}"
    echo -e "${YELLOW}服务仍以 HTTP 模式运行，稍后可手动执行：${NC}"
    echo "  sudo certbot --nginx -d $DOMAIN"
fi

# 8. 完成
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "服务器IP")
echo ""
echo -e "${GREEN}========================================"
echo "  部署完成！"
echo "========================================${NC}"
echo ""
echo "验证服务："
echo "  curl http://${SERVER_IP}/api/ping"
if [ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]; then
    echo "  curl https://${DOMAIN}/api/ping"
fi
echo ""
echo "常用运维命令（详见 deploy/README.md）："
echo "  sudo systemctl status sky-admin    查看服务状态"
echo "  sudo systemctl restart sky-admin   重启服务"
echo "  sudo journalctl -u sky-admin -f    查看实时日志"
echo ""
