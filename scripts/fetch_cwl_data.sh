#!/usr/bin/env bash
#
# 从 COC API 拉取 CWL 战绩数据并写入数据库
#
# 用法：
#   bash scripts/fetch_cwl_data.sh 2026-08        # 拉取 8 月联赛数据
#   bash scripts/fetch_cwl_data.sh 2026-07        # 拉取 7 月联赛数据

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "用法: bash scripts/fetch_cwl_data.sh <YYYY-MM>"
    echo "示例: bash scripts/fetch_cwl_data.sh 2026-08"
    exit 1
fi

PERIOD="$1"
cd "$(dirname "$0")/.."
source "$(dirname "$0")/load_env.sh"

echo "[fetch] 拉取 CWL 数据，联赛月: ${PERIOD} ..."
"${PYTHON:-python3}" scripts/fetch_cwl_data.py --period "${PERIOD}"
