#!/usr/bin/env bash
#
# 把 Part4（联赛名单排布网格）发布到"苍穹联赛报名结果"公示文档。
#
# 前置条件：register_and_arrange.sh 已成功执行（registrations 表有编排数据）。
#
# 行为：
#   - 前 20 行固定文字（规则说明、报名链接等）直接硬编码在代码中
#   - 从 registrations 表读取编排数据，重建 Part4 网格
#   - 拼接后按月份新建 sheet 写入目标文档
#
# 用法：
#   scripts/publish_to_results.sh 2026-08
#   scripts/publish_to_results.sh 2026-09

set -euo pipefail
cd "$(dirname "$0")/.."
source "$(dirname "$0")/load_env.sh"

LEAGUE_PERIOD="${1:-}"
if [[ -z "$LEAGUE_PERIOD" ]]; then
  echo "用法: $0 <联赛时间>    例如: $0 2026-09" >&2
  exit 1
fi
if [[ ! "$LEAGUE_PERIOD" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
  echo "错误: 联赛时间格式应为 YYYY-MM（收到: '$LEAGUE_PERIOD'）" >&2
  exit 1
fi

PY="${PYTHON:-python3}"

: "${TENCENT_DOC_ACCESS_TOKEN:?请在 .env 设置 TENCENT_DOC_ACCESS_TOKEN}"
: "${TENCENT_DOC_CLIENT_ID:?请在 .env 设置 TENCENT_DOC_CLIENT_ID}"
: "${TENCENT_DOC_OPEN_ID:?请在 .env 设置 TENCENT_DOC_OPEN_ID}"
: "${PUBLISH_DOC_FILE_ID:?请在 .env 设置 PUBLISH_DOC_FILE_ID}"

echo "=== 发布联赛报名结果：${LEAGUE_PERIOD} → ${PUBLISH_DOC_FILE_ID} ==="

"$PY" cli.py publish-results --period "$LEAGUE_PERIOD" --file-id "$PUBLISH_DOC_FILE_ID"

echo ""
echo "完成。"
