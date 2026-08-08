#!/bin/bash
# sync-uni.sh - 将服务器编译好的微信小程序产物同步到本地 Mac
# 用法：在 Mac 终端执行
#   bash sync-uni.sh
#
# 修改下面的 SERVER 为你的服务器地址

SERVER="ubuntu@115.159.64.19"
REMOTE_PATH="/home/ubuntu/YANG/sky-admin/uni-app/dist/build/mp-weixin/"
LOCAL_PATH="$HOME/Desktop/project/code/uni-app-dist"

echo "📦 从服务器同步微信小程序编译产物..."
echo "   服务器: $SERVER"
echo "   远程路径: $REMOTE_PATH"
echo "   本地路径: $LOCAL_PATH"
echo ""

# 确保本地目录存在
mkdir -p "$LOCAL_PATH"

# rsync 同步编译产物
rsync -avz --delete \
  --exclude='.DS_Store' \
  "$SERVER:$REMOTE_PATH" "$LOCAL_PATH"

echo ""
echo "✅ 同步完成！"
echo "📱 用微信开发者工具导入项目："
echo "   目录: $LOCAL_PATH"
echo "   AppID: wx6a46dda85a013a34"
