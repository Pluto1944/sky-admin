#!/usr/bin/env bash
# 一次性回填历史 CWL 战绩数据（用于 league-stats 功能的数据冷启动）
# 用法: bash scripts/backfill_league_results.sh
#
# 前置条件：DB 迁移已完成（league_results 表已有 offense_3stars 等新列）。
# 回填后 league_results 表将包含完整的进攻/防守三星统计数据。
#
# 逻辑：
#   1. 从 league_teams 表获取所有有 combat 队伍的月份
#   2. 与 league_results 表已有数据做差集，找出缺失的月份
#      - fetched_at IS NULL 的旧数据也视为缺失（旧版写入，缺少新字段）
#   3. 对每个缺失月份调用 fetch_cwl_data.py 拉取数据
#      - 优先走 ClashKing API（含进攻+防守三星统计）
#      - 降级到本地 JSON（只有进攻数据，防守为 0）
#   4. ON CONFLICT DO UPDATE 保证幂等，重复跑不会产生重复数据

set -euo pipefail
cd "$(dirname "$0")/.."
source "$(dirname "$0")/load_env.sh"

PY="${PYTHON:-python3}"

echo "========================================"
echo "  历史 CWL 数据回填（league-stats 冷启动）"
echo "========================================"

# ── 1. 自动发现待回填月份 ──
echo ""
echo "--- 发现待回填月份 ---"

MISSING=$("$PY" -c "
import sys, os
sys.path.insert(0, os.getcwd())
from shared.config.env_loader import load_env
load_env()
from shared.db.connection import Database
from config import DB_PATH, LEAGUE_COMBAT
db = Database(DB_PATH)
db.init_schema()

# league_teams 中有 combat 队伍的所有月份
team_periods = set()
rows = db.conn.execute(
    'SELECT DISTINCT period FROM league_teams WHERE category = ? ORDER BY period',
    (LEAGUE_COMBAT,)
).fetchall()
for r in rows:
    team_periods.add(r['period'])

# league_results 中已有完整数据的月份（fetched_at 不为空，表示新版写入过）
result_periods = set()
rows = db.conn.execute(
    'SELECT DISTINCT period FROM league_results WHERE fetched_at IS NOT NULL ORDER BY period'
).fetchall()
for r in rows:
    result_periods.add(r['period'])

missing = sorted(team_periods - result_periods)
db.close()

if missing:
    print(f'league_teams 有 combat 队伍: {len(team_periods)} 个月')
    print(f'league_results 已有完整数据: {len(result_periods)} 个月')
    print(f'待回填:                      {len(missing)} 个月')
    for m in missing:
        print(f'  - {m}')
else:
    print('所有月份已有数据，无需回填')

# 输出月份列表供 bash 使用
for m in missing:
    print(f'MISSING:{m}')
" 2>&1)

# 提取待回填月份
MONTHS=()
while IFS= read -r line; do
    if [[ "$line" == MISSING:* ]]; then
        MONTHS+=("${line#MISSING:}")
    else
        echo "$line"
    fi
done <<< "$MISSING"

if [ ${#MONTHS[@]} -eq 0 ]; then
    echo ""
    echo "✅ 无需回填，退出"
    exit 0
fi

echo ""
echo "========================================"
echo "  开始逐月回填 (共 ${#MONTHS[@]} 个月)"
echo "========================================"

SUCCESS=()
FAILED=()

for month in "${MONTHS[@]}"; do
  echo ""
  echo "--- 回填 $month ---"
  if "$PY" scripts/fetch_cwl_data.py --period "$month"; then
    SUCCESS+=("$month")
  else
    FAILED+=("$month")
    echo "⚠️ $month 回填失败（可能无历史数据或 API 不可达），继续下一个..."
  fi
done

echo ""
echo "========================================"
echo "  回填完成"
echo "========================================"
echo "成功: ${#SUCCESS[@]} 个月 — ${SUCCESS[*]:-无}"
echo "失败: ${#FAILED[@]} 个月 — ${FAILED[*]:-无}"

# ── 验证结果 ──
echo ""
echo "--- 各月份数据概况 ---"
"$PY" -c "
import sys, os
sys.path.insert(0, os.getcwd())
from shared.config.env_loader import load_env
load_env()
from shared.db.connection import Database
from config import DB_PATH
db = Database(DB_PATH)
db.init_schema()
rows = db.conn.execute(
    'SELECT period, COUNT(*) as players, '
    'SUM(offense_3stars) as off_3s, SUM(defense_3stars) as def_3s, SUM(defense_total) as def_tot, '
    'GROUP_CONCAT(DISTINCT CASE WHEN fetched_at = \"local_json\" THEN \"local_json\" '
    '  ELSE substr(fetched_at, 1, 10) END) as sources '
    'FROM league_results GROUP BY period ORDER BY period'
).fetchall()
print(f'{\"月份\":<10} {\"人数\":<6} {\"进攻三星\":<10} {\"防守三星\":<10} {\"防守总次数\":<10} {\"数据来源\":<30}')
for r in rows:
    src = r['sources'] or '-'
    print(f'{r[\"period\"]:<10} {r[\"players\"]:<6} {r[\"off_3s\"]:<10} {r[\"def_3s\"]:<10} {r[\"def_tot\"]:<10} {src:<30}')

# 检查防守数据为 0 的月份（可能是降级到本地 JSON 的）
print()
zero_def = db.conn.execute(
    'SELECT period, COUNT(*) as cnt FROM league_results '
    'WHERE period IN (SELECT DISTINCT period FROM league_results) '
    'GROUP BY period HAVING SUM(defense_total) = 0 ORDER BY period'
).fetchall()
if zero_def:
    print('⚠️ 以下月份防守数据为 0（可能走本地 JSON 降级，无防守统计）:')
    for r in zero_def:
        print(f'  - {r[\"period\"]} ({r[\"cnt\"]} 人)')
else:
    print('✅ 所有月份均有防守数据')

db.close()
"
