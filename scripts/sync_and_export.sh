#!/usr/bin/env bash
#
# 一体化维护入口：两步走。
#   [1] COC 官方 API  -> player 数据库（建档 / 更新 / 临时账号合并 / 退部对账）
#   [2] player 数据库 -> 腾讯在线文档（供人工检查数据是否正确）
#
# 适合放进 cron 定时执行，实现"长期更新维护"。例如每天 08:00：
#   0 8 * * * /path/to/scripts/sync_and_export.sh >> /path/to/sync.log 2>&1
#
# 凭证与文档 ID 一律从项目根 .env 读取（不写进脚本、不提交仓库）：
#   cp .env.example .env  然后填入：
#     COC_API_TOKEN               COC 官方 API（拉成员）
#     TENCENT_DOC_ACCESS_TOKEN    腾讯文档 OpenAPI（写表格，约 30 天过期需手动更新）
#     TENCENT_DOC_CLIENT_ID
#     TENCENT_DOC_OPEN_ID
#     ROSTER_DOC_FILE_ID          目标在线文档 fileId（导出玩家档案）
#

set -euo pipefail
cd "$(dirname "$0")/.."

# 从 .env 加载凭证（当前环境已 export 的同名变量优先，不被覆盖）
source "$(dirname "$0")/load_env.sh"

: "${COC_API_TOKEN:?请在 .env 设置 COC_API_TOKEN}"
: "${TENCENT_DOC_ACCESS_TOKEN:?请在 .env 设置 TENCENT_DOC_ACCESS_TOKEN}"
: "${TENCENT_DOC_CLIENT_ID:?请在 .env 设置 TENCENT_DOC_CLIENT_ID}"
: "${TENCENT_DOC_OPEN_ID:?请在 .env 设置 TENCENT_DOC_OPEN_ID}"

# 导出目标文档 fileId：优先 ROSTER_DOC_FILE_ID，回退到 TENCENT_DOC_FILE_ID
FILE_ID="${ROSTER_DOC_FILE_ID:-${TENCENT_DOC_FILE_ID:-}}"
: "${FILE_ID:?请在 .env 设置 ROSTER_DOC_FILE_ID（导出目标在线文档 fileId）}"

PY="${PYTHON:-python3}"

echo "[1/2] COC 官方 API -> player 数据库 ..."
"$PY" cli.py coc-sync

echo "[2/2] player 数据库 -> 腾讯在线文档 (fileId=${FILE_ID}) ..."
"$PY" cli.py player-export --to tencent -o "$FILE_ID"

echo "完成：数据已同步入库并导出到腾讯在线文档，可人工核对。"
