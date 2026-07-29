#!/usr/bin/env bash
# 切到项目根目录（本脚本位于 scripts/ 下），保证无论从哪里执行路径都正确
cd "$(dirname "$0")/.." || exit 1

# 凭证从项目根 .env 读取（不写进脚本、不提交仓库）：cp .env.example .env 后填入
source "$(dirname "$0")/load_env.sh"
: "${COC_API_TOKEN:?请在 .env 设置 COC_API_TOKEN}"

# 拉取 config 里所有 enabled 部落成员 -> 导出本地 xlsx（只读，不落库）
python3 scripts/dump_clans_to_xlsx.py "$@"
