#!/usr/bin/env bash
#
# 从 COC API 拉取 CWL 战绩 JSON（不导入 DB，仅拉数据）
#
# --period = 报名时间（CWL 发生月），如需要拉 7 月 CWL 数据 → --period 2026-07
#
# 用法：
#   scripts/fetch_cwl_data.sh --period 2026-07

set -euo pipefail
cd "$(dirname "$0")/.."
source "$(dirname "$0")/load_env.sh"

: "${COC_API_TOKEN:?请在 .env 设置 COC_API_TOKEN}"

echo "[fetch] 仅拉取 JSON（不导入 DB）..."
"${PYTHON:-python3}" scripts/fetch_cwl_data.py --fetch-only "$@"
