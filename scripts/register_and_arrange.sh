#!/usr/bin/env bash
#
# 报名一体化入口。
#
# 参数 PERIOD = 联赛时间（实际打 CWL 的月）。
#
# 步骤：
#   [1] 导入报名表（--period = 联赛时间；sheet 名按报名月 = 联赛-1 推算）
#   [2] fetch_cwl_data.py --period CWL月（= 联赛-1，拉取星数 → results 表）
#   [3] cli.py arrange（编排 + 升降级，星数从 results 表自动读取上月 CWL）
#
# 用法：
#   scripts/register_and_arrange.sh 2026-08
#   scripts/register_and_arrange.sh 2026-09

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

# CWL 月 = 联赛时间 - 1（用于 fetch_cwl_data 和报名表 sheet 名推算）
REG_PERIOD="$("$PY" - "$LEAGUE_PERIOD" <<'PYEOF'
import sys; y,m = map(int, sys.argv[1].split("-"))
m -= 1
if m == 0: y -= 1; m = 12
print(f"{y:04d}-{m:02d}")
PYEOF
)"

: "${COC_API_TOKEN:?请在 .env 设置 COC_API_TOKEN}"
: "${TENCENT_DOC_ACCESS_TOKEN:?请在 .env 设置 TENCENT_DOC_ACCESS_TOKEN}"
: "${TENCENT_DOC_CLIENT_ID:?请在 .env 设置 TENCENT_DOC_CLIENT_ID}"
: "${TENCENT_DOC_OPEN_ID:?请在 .env 设置 TENCENT_DOC_OPEN_ID}"
: "${REG_DOC_FILE_ID:?请在 .env 设置 REG_DOC_FILE_ID}"
: "${ROSTER_DOC_FILE_ID:?请在 .env 设置 ROSTER_DOC_FILE_ID}"

if [[ -z "${REG_SHEET:-}" ]]; then
  REG_SHEET="$("$PY" - "$REG_PERIOD" <<'PYEOF'
import calendar, sys; y,m = map(int, sys.argv[1].split("-"))
print(f"{y:04d}{m:02d}01-{y:04d}{m:02d}{calendar.monthrange(y,m)[1]:02d}（收集结果）")
PYEOF
)"
fi

echo "=== 联赛时间: ${LEAGUE_PERIOD}  →  CWL 月: ${REG_PERIOD} ==="

# [1] 导入报名表（--period = 联赛时间；sheet 名按报名月 = 联赛-1 推算）
echo ""
echo "[1] 导入报名表（联赛时间=${LEAGUE_PERIOD}）..."
"$PY" cli.py import-reg "$REG_DOC_FILE_ID" --period "$LEAGUE_PERIOD" --to tencent --sheet "$REG_SHEET"


# [2] 拉取星数 → results 表（CWL 月 = 联赛-1）
# 如果是 2026-07，数据已通过迁移脚本写入 league_results，跳过 API 拉取
echo ""
if [[ "$REG_PERIOD" == "2026-07" ]]; then
  echo "[2] CWL 月=${REG_PERIOD}，数据已迁移，跳过 API 拉取"
else
  echo "[2] 拉取 CWL 星数 → results 表..."
  if "$PY" scripts/fetch_cwl_data.py --period "$REG_PERIOD"; then
    echo "[2] ✅ 星数就绪"
  else
    echo "[2] ⚠️ 无星数数据，编排时自动跳过升降级（所有人员保持原队）"
  fi
fi
echo ""

# [3] 编排名单
echo "[3] 编排名单（联赛时间=${LEAGUE_PERIOD}）..."
arrange_cmd=("$PY" cli.py arrange --period "$LEAGUE_PERIOD" --to tencent -o "$ROSTER_DOC_FILE_ID")
[[ -n "${ROSTER_SHEET:-}" ]] && arrange_cmd+=(--sheet "$ROSTER_SHEET")
"${arrange_cmd[@]}"

echo ""
echo "完成。"
