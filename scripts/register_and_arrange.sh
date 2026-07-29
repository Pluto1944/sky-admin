#!/usr/bin/env bash
#
# 报名一体化入口：三步走。
#   [1] COC 官方 API   -> player 数据库（刷新战营部落成员与奖杯，保证战营名单最新）
#   [2] 腾讯在线文档    -> registrations（读取报名表，合并战营名单后落库）
#   [3] player 数据库  -> 腾讯在线文档（编排联赛名单并写回，供人工核对）
#
# 每月开赛前跑一次即可，例如：
#   scripts/register_and_arrange.sh 2026-07
#
# 也可放进 cron 定时执行（period 由参数或环境变量 LEAGUE_PERIOD 指定）：
#   0 9 1 * * LEAGUE_PERIOD=$(date +\%Y-\%m) /path/to/scripts/register_and_arrange.sh >> /path/to/register.log 2>&1
#
# 凭证与文档 ID 一律从项目根 .env 读取（不写进脚本、不提交仓库）：
#   cp .env.example .env  然后填入 COC_API_TOKEN / TENCENT_DOC_* / REG_DOC_FILE_ID / ROSTER_DOC_FILE_ID
# 可选变量（.env 或运行前 export 均可）：
#   REG_SHEET    报名子表名；留空则按 period 自动推算 "YYYYMMDD-YYYYMMDD（收集结果）"
#   ROSTER_SHEET 名单写入子表名；留空则用默认 "名单_<period>"

set -euo pipefail
cd "$(dirname "$0")/.."

# 从 .env 加载凭证（当前环境已 export 的同名变量优先，不被覆盖）
source "$(dirname "$0")/load_env.sh"

# period：优先命令行第 1 个参数，其次环境变量 LEAGUE_PERIOD
PERIOD="${1:-${LEAGUE_PERIOD:-}}"
if [[ -z "$PERIOD" ]]; then
  echo "用法: $0 <period>    例如: $0 2026-07（或设置环境变量 LEAGUE_PERIOD）" >&2
  exit 1
fi
# period 格式校验：YYYY-MM
if [[ ! "$PERIOD" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
  echo "错误: period 格式应为 YYYY-MM，例如 2026-07（收到: '$PERIOD'）" >&2
  exit 1
fi

: "${COC_API_TOKEN:?请在 .env 设置 COC_API_TOKEN}"
: "${TENCENT_DOC_ACCESS_TOKEN:?请在 .env 设置 TENCENT_DOC_ACCESS_TOKEN}"
: "${TENCENT_DOC_CLIENT_ID:?请在 .env 设置 TENCENT_DOC_CLIENT_ID}"
: "${TENCENT_DOC_OPEN_ID:?请在 .env 设置 TENCENT_DOC_OPEN_ID}"
: "${REG_DOC_FILE_ID:?请在 .env 设置 REG_DOC_FILE_ID（报名表在线文档 fileId）}"
: "${ROSTER_DOC_FILE_ID:?请在 .env 设置 ROSTER_DOC_FILE_ID（名单写入在线文档 fileId）}"

PY="${PYTHON:-python3}"

# 报名子表名：未显式指定 REG_SHEET 时，按 period 自动推算为
#   "YYYYMMDD-YYYYMMDD（收集结果）"（当月首日 ~ 末日）。
# 末日用 Python 的 calendar.monthrange 计算，精确处理 28/29/30/31（含闰年 2 月）。
if [[ -z "${REG_SHEET:-}" ]]; then
  REG_SHEET="$("$PY" - "$PERIOD" <<'PYEOF'
import calendar, sys
year, month = (int(x) for x in sys.argv[1].split("-"))
last = calendar.monthrange(year, month)[1]  # 当月天数：28/29/30/31
print(f"{year:04d}{month:02d}01-{year:04d}{month:02d}{last:02d}（收集结果）")
PYEOF
)"
  echo "[info] REG_SHEET 未指定，按 period 推算报名子表名：${REG_SHEET}"
fi

#echo "[1/3] COC 官方 API -> player 数据库（刷新战营部落成员）..."
#"$PY" cli.py coc-sync

echo "[2/3] 腾讯在线文档 (fileId=${REG_DOC_FILE_ID}, sheet=${REG_SHEET}) -> registrations 报名入库（period=${PERIOD}）..."
"$PY" cli.py import-reg "$REG_DOC_FILE_ID" --period "$PERIOD" --to tencent --sheet "$REG_SHEET"

echo "[3/3] player 数据库 -> 腾讯在线文档 (fileId=${ROSTER_DOC_FILE_ID}) 生成联赛名单（period=${PERIOD}）..."
arrange_cmd=("$PY" cli.py arrange --period "$PERIOD" --to tencent -o "$ROSTER_DOC_FILE_ID")
[[ -n "${ROSTER_SHEET:-}" ]] && arrange_cmd+=(--sheet "$ROSTER_SHEET")
"${arrange_cmd[@]}"

echo "完成：报名已入库并编排名单写入腾讯在线文档，可人工核对。"
