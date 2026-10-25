#!/usr/bin/env bash

set -euo pipefail

TOOL_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPOSITORY_DIR=$(cd -- "$TOOL_DIR/../.." && pwd)

# npm 在本机代理下访问 registry 偶发 TLS 重置。工具安装与微信上传一样使用直连，
# 且不继承或打印代理地址、账号和密码。
source "$REPOSITORY_DIR/.frontend-env/activate"
cd "$TOOL_DIR"
exec env \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY='*' no_proxy='*' \
  npm ci --ignore-scripts \
    --registry=https://registry.npmjs.org \
    --fetch-timeout=30000 \
    --fetch-retries=2
