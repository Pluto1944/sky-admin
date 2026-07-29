"""COC 部落成员查询 —— 简单探测脚本。

用途：验证 COC 官方 API 是否打通，给定部落标签打印全部成员信息。

前置：
  1. 到 https://developer.clashofclans.com 申请 API Token（需绑定出口 IP）。
  2. 把 Token 放进环境变量（切勿写进代码/仓库）：
       export COC_API_TOKEN='你的token'

用法：
  python scripts/probe_coc_clan.py '#2PP'          # 传部落标签
  python scripts/probe_coc_clan.py 2PP             # '#' 可省略，脚本会补

说明：这是手动联调脚本，需要真实 Token 与外网，不纳入 pytest 自动化。
"""
from __future__ import annotations

import os
import sys

# 允许直接 `python scripts/probe_coc_clan.py` 运行时找到项目根包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.coc_sync.api_client import CocApiError  # noqa: E402
from modules.coc_sync.service import CocSyncService  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python scripts/probe_coc_clan.py <部落标签，如 #2PP>", file=sys.stderr)
        return 2

    clan_tag = argv[1]

    if not os.environ.get("COC_API_TOKEN"):
        print("错误: 未设置环境变量 COC_API_TOKEN，请先 export 后再运行。", file=sys.stderr)
        return 1

    # 满足"所有 API 调用全部经 coc_sync 封装"：只读预览也走 CocSyncService，不直接碰 api_client
    svc = CocSyncService()
    try:
        members = svc.fetch_clan_members(clan_tag)
    except (CocApiError, ValueError) as e:
        print(f"查询失败: {e}", file=sys.stderr)
        return 1

    print(f"部落 {clan_tag} 共 {len(members)} 名成员：\n")
    header = f"{'#':>3}  {'Tag':<12} {'名字':<18} {'职位':<10} {'等级':>4} {'奖杯':>6}"
    print(header)
    print("-" * len(header))
    for i, m in enumerate(members, 1):
        print(
            f"{i:>3}  "
            f"{m.get('player_tag', '-'):<12} "
            f"{m.get('account_name', '-'):<18} "
            f"{m.get('clan_role', '-'):<10} "
            f"{m.get('exp_level', '-'):>4} "
            f"{m.get('trophies', '-'):>6}  {m.get('league_name', '-')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
