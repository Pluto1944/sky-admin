#!/bin/bash
set -e

echo "========================================"
echo "  Sky Admin 一键部署脚本"
echo "========================================"
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="/opt/sky-admin/sky-admin"

# 检查是否为 root
if [ "$(id -u)" != "0" ]; then
    echo "错误：请使用 root 用户执行此脚本"
    exit 1
fi

# 1. 更新系统
echo -e "${GREEN}[1/7] 更新系统包...${NC}"
apt update && apt upgrade -y

# 2. 安装系统依赖
echo -e "${GREEN}[2/7] 安装 Python3 + Nginx...${NC}"
apt install -y python3 python3-pip python3-venv nginx

# 3. 创建虚拟环境并安装 Python 依赖
echo -e "${GREEN}[3/7] 安装 Python 依赖...${NC}"
cd "$PROJECT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 4. 配置 Nginx
echo -e "${GREEN}[4/7] 配置 Nginx...${NC}"
cp deploy/nginx.conf /etc/nginx/sites-available/sky-admin
ln -sf /etc/nginx/sites-available/sky-admin /etc/nginx/sites-enabled/
# 删除默认站点
rm -f /etc/nginx/sites-enabled/default
# 测试配置
nginx -t && systemctl reload nginx

# 5. 配置 systemd 服务
echo -e "${GREEN}[5/7] 配置 systemd 守护进程...${NC}"
cp deploy/sky-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sky-admin

# 6. 启动服务
echo -e "${GREEN}[6/7] 启动服务...${NC}"
systemctl restart sky-admin
sleep 2
systemctl status sky-admin --no-pager

# 7. 完成
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "服务器IP")
echo ""
echo -e "${GREEN}========================================"
echo "  部署完成！"
echo "========================================${NC}"
echo ""
echo "验证服务："
echo "  curl http://${SERVER_IP}/api/ping"
echo ""
echo "常用命令："
echo "  systemctl status sky-admin    查看服务状态"
echo "  systemctl restart sky-admin   重启服务"
echo "  journalctl -u sky-admin -f    查看实时日志"
echo "  tail -f /var/log/sky-admin.log 查看应用日志"
echo ""
echo -e "${YELLOW}域名审核通过后，切换 HTTPS 步骤：${NC}"
echo "  1. 编辑 nginx 配置: vim /etc/nginx/sites-available/sky-admin"
echo "  2. 启用 HTTPS 部分，注释 HTTP 部分"
echo "  3. certbot --nginx -d api.你的域名.com"
echo "  4. systemctl reload nginx"
echo ""
