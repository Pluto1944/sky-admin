"""拉取 config 里所有 enabled 部落的成员，写入本地 xlsx 供人工核对。

这是**只读预览**脚本：走 CocSyncService.fetch_clan_members，只拉取+标准化，
不写数据库（不影响 player 档案），用于验证"多部落抓取 + 本地导出"是否正确。

前置：
  1. 到 https://developer.clashofclans.com 申请 API Token（需绑定出口 IP）。
  2. 把 Token 放进环境变量（切勿写进代码/仓库）：
       export COC_API_TOKEN='你的token'

用法：
  python scripts/dump_clans_to_xlsx.py                    # 默认输出 data/coc_members.xlsx
  python scripts/dump_clans_to_xlsx.py -o /tmp/members.xlsx

说明：
  - 遍历 modules/coc_sync/config.py 的 CLANS（仅 enabled=True）；改数量只需改配置。
  - 每个部落写成一个独立 sheet（sheet 名取部落 name），表头中文、开自动筛选+冻结首行。
  - 手动联调脚本，需要真实 Token 与外网，不纳入 pytest。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# 允许直接 `python scripts/dump_clans_to_xlsx.py` 运行时找到项目根包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.coc_sync import config as coc_config  # noqa: E402
from modules.coc_sync.api_client import CocApiError  # noqa: E402
from modules.coc_sync.service import CocSyncService  # noqa: E402
from shared.io_adapter.local_xlsx import LocalXlsxAdapter  # noqa: E402

# 成员预览列（顺序即表头顺序）：内部字段 -> 中文表头。
# 注意：/clans/{tag}/members 接口不返回 townHallLevel，故不含"大本"列。
COLUMNS = {
    "clan_name": "所属部落",
    "clan_tag": "部落Tag",
    "player_tag": "玩家Tag",
    "account_name": "游戏昵称",
    "clan_role": "部落职位",
    "exp_level": "等级",
    "trophies": "奖杯",
    "league_name": "段位",
}

# Excel sheet 名限制：<=31 字符且不含 []:*?/\
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:\*\?/\\]")


def _safe_sheet_name(name: str, fallback: str) -> str:
    cleaned = _INVALID_SHEET_CHARS.sub(" ", (name or "").strip())
    cleaned = cleaned or fallback
    return cleaned[:31]


def _to_rows(members: list[dict], clan_name: str) -> list[dict]:
    """把标准化成员映射为中文表头行；补上所属部落名（成员条目本身不含）。"""
    rows = []
    for m in members:
        src = dict(m)
        src["clan_name"] = clan_name
        rows.append({header: src.get(field) for field, header in COLUMNS.items()})
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="拉取所有 enabled 部落成员并导出本地 xlsx（只读）")
    parser.add_argument(
        "-o", "--output", default=os.path.join("data", "coc_members.xlsx"),
        help="输出 xlsx 路径（默认 data/coc_members.xlsx）",
    )
    args = parser.parse_args(argv[1:])

    if not os.environ.get("COC_API_TOKEN"):
        print("错误: 未设置环境变量 COC_API_TOKEN，请先 export 后再运行。", file=sys.stderr)
        return 1

    clans = [c for c in coc_config.CLANS if c.get("enabled", True)]
    if not clans:
        print("错误: config.CLANS 中没有 enabled=True 的部落。", file=sys.stderr)
        return 1

    # 输出目录不存在则创建；已存在同名文件先删除，避免旧 sheet 残留
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(args.output):
        os.remove(args.output)

    svc = CocSyncService()  # 只读预览，无需 player_service
    io = LocalXlsxAdapter()

    headers = list(COLUMNS.values())
    failed: list[str] = []
    all_rows: list[dict] = []
    # 先拉取全部部落并累积，便于"总表"排在最前
    clan_rows: list[tuple[str, list[dict]]] = []
    print(f"共 {len(clans)} 个部落待拉取：\n")
    for idx, clan in enumerate(clans, 1):
        tag, name = clan["tag"], clan.get("name") or clan["tag"]
        try:
            members = svc.fetch_clan_members(tag, name)
        except (CocApiError, ValueError) as e:
            print(f"[warn] 部落 {name}({tag}) 拉取失败，跳过：{e}", file=sys.stderr)
            failed.append(tag)
            continue

        rows = _to_rows(members, name)
        sheet_name = _safe_sheet_name(name, fallback=f"clan{idx}")
        clan_rows.append((sheet_name, rows))
        all_rows.extend(rows)
        print(f"  [{idx}] {name}({tag})：{len(rows)} 人 -> sheet「{sheet_name}」")

    # 总表（所有部落汇总）放第一个 sheet，再写各部落分表
    io.write_sheet(
        args.output, all_rows, headers=headers, sheet="总表",
        auto_filter=True, freeze_header=True,
    )
    for sheet_name, rows in clan_rows:
        io.write_sheet(
            args.output, rows, headers=headers, sheet=sheet_name,
            auto_filter=True, freeze_header=True,
        )

    print(
        f"\n完成：{len(clans) - len(failed)}/{len(clans)} 个部落，"
        f"共 {len(all_rows)} 人 -> {args.output}（总表 + {len(clan_rows)} 个分表）"
    )
    if failed:
        print(f"失败部落：{', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
