"""命令行入口。

用法：
  python cli.py coc-sync      [--clan '#2QQ' --clan '#XX']   先同步 COC 建档
  python cli.py import-reg    报名表.xlsx --period 2026-08
  python cli.py import-reg    <fileId> --period 2026-08 --sheet 报名表 --to tencent
  python cli.py arrange       --period 2026-08 -o 名单.xlsx
  python cli.py import-result 战绩表.xlsx --period 2026-08
  python cli.py accounts      [--status active]
  python cli.py player-export -o players.xlsx [--status active] [--membership member] [--sort history_score]
  python cli.py reset-db      [-y]                            清空重建（历史数据清零）

period 语义统一为「联赛月份」（实际打 CWL 的月份，如 2026-08）。
- import-reg / arrange / import-result 的 --period 均为联赛月份。
- fetch_cwl_data.py 的 --period 为 CWL 实际发生月（编排 N 月联赛时传 N-1 月）。

架构：按业务领域分模块（player 中枢 / cwl_registration 报名 / war_result 战绩 /
coc_sync 预留），共享 shared 基础设施（io_adapter / db / config）。
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys

from modules.coc_sync.service import CocSyncService
from modules.cwl_registration.importer import RegistrationImporter
from modules.cwl_registration.repository import RegistrationRepository
from modules.cwl_registration.roster import LeagueArranger
from modules.cwl_registration.config import COMBAT_MIN_MATCH_VALUE, TEAMS
from modules.player.exporter import PlayerExporter
from modules.player.repository import PlayerRepository
from modules.player.service import PlayerService
from modules.war_result.importer import ResultImporter
from modules.war_result.repository import ResultRepository
from shared.config import common as config
from shared.db.connection import Database
from shared.io_adapter.base import ExcelIO


def make_excel_io(adapter: str | None = None) -> ExcelIO:
    """选择 IO 适配器。

    adapter 显式指定 'local' / 'tencent' 时以它为准（单条命令级覆盖，不影响
    其它命令）；未指定则回退到全局 config.IO_ADAPTER。
    """
    name = adapter or config.IO_ADAPTER
    if name == "tencent":
        from shared.io_adapter.tencent_doc import TencentDocAdapter

        return TencentDocAdapter()
    from shared.io_adapter.local_xlsx import LocalXlsxAdapter

    return LocalXlsxAdapter()


def make_db() -> Database:
    db = Database(config.DB_PATH)
    db.init_schema()
    return db


def _default_reg_sheet(league_period: str) -> str | None:
    """根据联赛月份推算报名表 sheet 名（报名月 = 联赛月 - 1）。

    报名表 sheet 命名约定：YYYYMM01-YYYYMMLAST（收集结果）
    例如联赛 2026-08 → 报名月 2026-07 → sheet "20260701-20260731（收集结果）"
    格式非法时返回 None（交由调用方处理）。
    """
    try:
        y, m = int(league_period[:4]), int(league_period[5:7])
    except (ValueError, IndexError):
        return None
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    last_day = calendar.monthrange(y, m)[1]
    return f"{y:04d}{m:02d}01-{y:04d}{m:02d}{last_day:02d}（收集结果）"


def cmd_import_reg(args) -> None:
    """导入报名表（本地 xlsx 或腾讯在线文档）。

    --to tencent 时 file 作为腾讯文档 fileId（缺省读 TENCENT_DOC_FILE_ID）；
    --to local 时 file 为本地 xlsx 路径。战营名单不从表格读取，而是从 accounts
    表按战营部落标签拉取（导入前应先 coc-sync 刷新该部落成员）。
    """
    to = args.to or config.IO_ADAPTER
    if to == "tencent":
        source = args.file or os.environ.get("TENCENT_DOC_FILE_ID")
        if not source:
            print(
                "错误: 从腾讯文档导入需指定 fileId，或设置环境变量 TENCENT_DOC_FILE_ID。",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        if not args.file:
            print("错误: 从本地导入需指定报名表 xlsx 路径。", file=sys.stderr)
            raise SystemExit(1)
        source = args.file

    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    reg_repo = RegistrationRepository(db.conn)
    importer = RegistrationImporter(player_service, reg_repo, make_excel_io(to))
    # 未显式指定 sheet 时，按联赛月份推算报名表 sheet 名（报名月 = 联赛月 - 1）
    sheet = args.sheet or _default_reg_sheet(args.period)
    n = importer.import_from(source, args.period, sheet)
    where = f"腾讯文档 {source}" if to == "tencent" else source
    print(f"已导入 {n} 条报名（{args.period}，来源：{where}）")


def _print_arrange_report(ordered: list[dict], team_results: list[dict],
                          period: str, where: str) -> None:
    """输出编排全量统计报告，使系统行为可观测。"""
    total = len(ordered)
    combat_count = sum(1 for x in ordered if x["league_type"] == config.LEAGUE_COMBAT)
    shell_count = total - combat_count
    assigned = sum(1 for x in ordered if x.get("team_name"))
    unassigned = total - assigned

    # 总览
    print()
    print("=" * 60)
    print(f"  名单编排报告  period={period}  输出={where}")
    print("=" * 60)
    print(f"  总人数  : {total}")
    print(f"    已入队: {assigned}  ({assigned * 100 // total}%)")
    print(f"    未分配: {unassigned}  ({unassigned * 100 // total}%)")
    print()

    # 联赛类型分布
    print(f"  联赛分类:")
    print(f"    实战 (combat): {combat_count} 人")
    print(f"    壳子 (shell) : {shell_count} 人")
    print(f"    实战最低匹配值门槛: {COMBAT_MIN_MATCH_VALUE}")
    print()

    # 队伍配置容量
    combat_teams = [t for t in TEAMS if t["category"] == config.LEAGUE_COMBAT]
    shell_teams  = [t for t in TEAMS if t["category"] == config.LEAGUE_SHELL]
    combat_cap = sum(t["member_count"] for t in combat_teams)
    shell_cap  = sum(t["member_count"] for t in shell_teams)
    print(f"  队伍容量:")
    print(f"    实战: {combat_cap} 位 ({len(combat_teams)} 队)")
    print(f"    壳子: {shell_cap} 位 ({len(shell_teams)} 队)")
    print(f"    合计: {combat_cap + shell_cap} 位")
    print()

    # 逐队详情
    print(f"  队伍分配:")
    for tr in team_results:
        cat_label = "实战" if tr["category"] == config.LEAGUE_COMBAT else "壳子"
        name   = tr["team_name"]
        filled = tr["filled_count"]
        cap    = tr["member_count"]
        reserved = tr.get("reserved_empty", 0)
        clan_tag  = tr.get("clan_tag", "")
        leader    = tr.get("leader", "")
        extra = f" {clan_tag}" if clan_tag else ""
        if leader:
            extra += f" 领队:{leader}"

        if filled == cap and reserved == 0:
            status = " 已满"
        elif reserved > 0:
            status = f" 实{filled}/{cap - reserved}+预留{reserved}"
        elif filled > cap:
            status = f" 溢出+{filled - cap}"
        else:
            status = f" 缺{cap - filled}"

        print(f"    [{cat_label}] {name:<10}{extra}  {filled}/{cap}{status}")
    print()

    # 未分配明细
    if unassigned > 0:
        unassigned_combat = sum(
            1 for x in ordered
            if not x.get("team_name") and x["league_type"] == config.LEAGUE_COMBAT
        )
        unassigned_shell = unassigned - unassigned_combat
        print(f"  未分配详情 ({unassigned} 人):")
        if unassigned_combat:
            print(f"    实战未入队: {unassigned_combat} 人（溢出，已注入壳子池参与排序）")
        if unassigned_shell:
            print(f"    壳子未入队: {unassigned_shell} 人（匹配值靠后，超出队伍容量）")
        print()
    print("=" * 60)
    print()


def cmd_arrange(args) -> None:
    """生成联赛名单并写入表格（本地 xlsx 或腾讯在线文档）。

    --to tencent 时 -o/--output 作为腾讯文档 fileId（缺省读 TENCENT_DOC_FILE_ID）；
    --to local 时 -o/--output 为本地 xlsx 路径。
    """
    to = args.to or config.IO_ADAPTER
    if to == "tencent":
        target = args.output or os.environ.get("TENCENT_DOC_FILE_ID")
        if not target:
            print(
                "错误: 写入腾讯文档需用 -o 指定 fileId，或设置环境变量 TENCENT_DOC_FILE_ID。",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        if not args.output:
            print("错误: 写入本地需用 -o 指定 xlsx 输出路径。", file=sys.stderr)
            raise SystemExit(1)
        target = args.output

    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    reg_repo = RegistrationRepository(db.conn)
    result_repo = ResultRepository(db.conn)
    arranger = LeagueArranger(player_service, reg_repo, make_excel_io(to), result_repo)
    ordered, team_results, _movements, sheet_name = arranger.arrange_and_export(
        args.period, target, sheet=args.sheet
    )
    where = f"腾讯文档 {target}" if to == "tencent" else target
    _print_arrange_report(ordered, team_results, args.period, where)


def cmd_import_result(args) -> None:
    """导入战绩表（本地 xlsx 或腾讯在线文档）。

    --to tencent 时 file 作为腾讯文档 fileId（缺省读 TENCENT_DOC_FILE_ID）；
    --to local 时 file 为本地 xlsx 路径。
    """
    to = args.to or config.IO_ADAPTER
    if to == "tencent":
        source = args.file or os.environ.get("TENCENT_DOC_FILE_ID")
        if not source:
            print(
                "错误: 从腾讯文档导入需指定 fileId，或设置环境变量 TENCENT_DOC_FILE_ID。",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        if not args.file:
            print("错误: 从本地导入需指定战绩表 xlsx 路径。", file=sys.stderr)
            raise SystemExit(1)
        source = args.file

    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    result_repo = ResultRepository(db.conn)
    importer = ResultImporter(player_service, result_repo, make_excel_io(to))
    n = importer.import_from(source, args.period, args.sheet)
    where = f"腾讯文档 {source}" if to == "tencent" else source
    print(f"已导入 {n} 条战绩并更新历史分（{args.period}，来源：{where}）")


def cmd_accounts(args) -> None:
    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    accounts = player_service.list_all(status=args.status)
    accounts.sort(key=lambda a: (a.get("status") or "", a.get("player_tag") or ""))
    print(f"共 {len(accounts)} 个账号：")
    for a in accounts:
        print(
            f"  {a['player_tag']:<12} {a.get('account_name') or '':<10} "
            f"{a.get('status') or '':<10} "
            f"最后报名={a.get('last_reg_period') or '-'} 历史分={a.get('history_score')}"
        )


def cmd_player_export(args) -> None:
    """把 player 数据库导出到表格（本地 xlsx 或腾讯在线文档），供人工检查。

    --to tencent 时 -o/--output 作为腾讯文档 fileId（缺省读 TENCENT_DOC_FILE_ID）；
    --to local 时 -o/--output 为本地 xlsx 路径（必填）。
    """
    to = args.to or config.IO_ADAPTER
    if to == "tencent":
        target = args.output or os.environ.get("TENCENT_DOC_FILE_ID")
        if not target:
            print(
                "错误: 导出到腾讯文档需用 -o 指定 fileId，或设置环境变量 TENCENT_DOC_FILE_ID。",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        if not args.output:
            print("错误: 导出到本地需用 -o 指定 xlsx 输出路径。", file=sys.stderr)
            raise SystemExit(1)
        target = args.output

    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    exporter = PlayerExporter(player_service, make_excel_io(to))
    n, sheet_name = exporter.export(
        target,
        status=args.status,
        membership_status=args.membership,
        sort_by=args.sort,
        descending=not args.asc,
        sheet=args.sheet,
    )
    where = f"腾讯文档 {target}" if to == "tencent" else target
    print(f"已导出 {n} 个账号 -> {where}[sheet: {sheet_name}]")


def cmd_coc_sync(args) -> None:
    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    svc = CocSyncService(player_service)
    clans = args.clan or None  # 命令行 --clan 覆盖 config.CLANS
    stats = svc.sync_clans(clans)
    print(
        f"COC 同步完成：部落 {stats['clans']}，成员 {stats['members']}，"
        f"新增 {stats['created']}，更新 {stats['updated']}，"
        f"跨部落重复 {stats['duplicates']}，退部 {stats['left']}"
    )
    if stats["failed_clans"]:
        print(f"[warn] 以下部落同步失败：{', '.join(stats['failed_clans'])}", file=sys.stderr)


def cmd_publish_results(args) -> None:
    """将编排结果（Part4 网格）发布到最终报名结果公示文档。

    从 registrations 表读取编排数据，重建 Part4 网格，写入 PUBLISH_DOC_FILE_ID。
    文档结构：前 20 行固定文字（硬编码） + Part4 队伍编排网格。
    """
    to = args.to or config.IO_ADAPTER
    if to != "tencent":
        print("错误: publish-results 仅支持腾讯文档（--to tencent）。", file=sys.stderr)
        raise SystemExit(1)

    target = args.file_id or os.environ.get("PUBLISH_DOC_FILE_ID")
    if not target:
        print(
            "错误: 需用 --file-id 指定目标文档，或设置环境变量 PUBLISH_DOC_FILE_ID。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    db = make_db()
    player_service = PlayerService(PlayerRepository(db.conn))
    reg_repo = RegistrationRepository(db.conn)
    result_repo = ResultRepository(db.conn)
    arranger = LeagueArranger(player_service, reg_repo, make_excel_io(to), result_repo)
    sheet_name = arranger.publish_part4_to_doc(
        args.period,
        target,
    )
    print(f"已发布报名结果: {sheet_name} → 腾讯文档 {target}")


def cmd_reset_db(args) -> None:
    if not args.yes:
        ans = input("将清空并重建 accounts/registrations/results（历史数据不可恢复），输入 yes 确认: ")
        if ans.strip().lower() != "yes":
            print("已取消。")
            return
    db = make_db()
    db.reset()
    print("已清空并重建数据库。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="联赛报名与名单编排管理系统")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("import-reg", help="导入报名表（本地/腾讯文档）")
    p1.add_argument(
        "file", nargs="?", default=None,
        help="本地模式：报名表 xlsx 路径；腾讯模式：文档 fileId（缺省读 TENCENT_DOC_FILE_ID）",
    )
    p1.add_argument("--period", required=True, help="联赛月份，如 2026-08")
    p1.add_argument("--sheet", default=None, help="工作表名（可选，缺省按联赛月-1自动推算报名表sheet名）")
    p1.add_argument(
        "--to", choices=("local", "tencent"), default=None,
        help="数据源：local=本地 xlsx，tencent=腾讯在线文档（缺省用 config.IO_ADAPTER）",
    )
    p1.set_defaults(func=cmd_import_reg)

    p2 = sub.add_parser("arrange", help="生成联赛名单（本地/腾讯文档）")
    p2.add_argument("--period", required=True, help="联赛月份，如 2026-08")
    p2.add_argument(
        "-o", "--output", default=None,
        help="本地模式：输出名单 xlsx 路径；腾讯模式：文档 fileId（缺省读 TENCENT_DOC_FILE_ID）",
    )
    p2.add_argument(
        "--to", choices=("local", "tencent"), default=None,
        help="写入目标：local=本地 xlsx，tencent=腾讯在线文档（缺省用 config.IO_ADAPTER）",
    )
    p2.add_argument(
        "--sheet",
        default=None,
        help="写入的 sheet 名（默认“名单_<period>”，文件已存在则新建该 sheet）",
    )
    p2.set_defaults(func=cmd_arrange)

    p3 = sub.add_parser("import-result", help="导入战绩表（本地/腾讯文档）")
    p3.add_argument(
        "file", nargs="?", default=None,
        help="本地模式：战绩表 xlsx 路径；腾讯模式：文档 fileId（缺省读 TENCENT_DOC_FILE_ID）",
    )
    p3.add_argument("--period", required=True, help="联赛月份（战绩所属月），如 2026-08")
    p3.add_argument("--sheet", default=None, help="工作表名（可选，腾讯文档建议指定）")
    p3.add_argument(
        "--to", choices=("local", "tencent"), default=None,
        help="数据源：local=本地 xlsx，tencent=腾讯在线文档（缺省用 config.IO_ADAPTER）",
    )
    p3.set_defaults(func=cmd_import_result)

    p4 = sub.add_parser("accounts", help="查看账号档案")
    p4.add_argument("--status", default=None, help="按状态过滤：active/missed/maybe_left/left")
    p4.set_defaults(func=cmd_accounts)

    p_exp = sub.add_parser("player-export", help="导出玩家档案到表格（本地/腾讯文档）")
    p_exp.add_argument(
        "-o", "--output", default=None,
        help="本地模式：xlsx 输出路径（必填）；腾讯模式：文档 fileId（缺省读 TENCENT_DOC_FILE_ID）",
    )
    p_exp.add_argument(
        "--to", choices=("local", "tencent"), default=None,
        help="导出目标：local=本地 xlsx，tencent=腾讯在线文档（缺省用 config.IO_ADAPTER）",
    )
    p_exp.add_argument(
        "--status", default=None, help="按报名状态过滤：active/missed/maybe_left/left"
    )
    p_exp.add_argument(
        "--membership", default=None, help="按部落身份过滤：member/left"
    )
    p_exp.add_argument(
        "--sort", default="history_score", help="排序字段（accounts 列名，默认 history_score）"
    )
    p_exp.add_argument("--asc", action="store_true", help="升序（默认降序）")
    p_exp.add_argument("--sheet", default=None, help="写入的 sheet 名（默认“玩家档案”）")
    p_exp.set_defaults(func=cmd_player_export)

    p5 = sub.add_parser("coc-sync", help="通过 COC API 同步部落成员到账号档案")
    p5.add_argument(
        "--clan",
        action="append",
        default=None,
        help="部落标签，如 '#2QQ'；可多次指定，覆盖 config.CLANS（不传则用配置）",
    )
    p5.set_defaults(func=cmd_coc_sync)

    p_pub = sub.add_parser("publish-results", help="发布编排结果（Part4）到最终报名结果公示文档")
    p_pub.add_argument("--period", required=True, help="联赛月份，如 2026-08")
    p_pub.add_argument(
        "--file-id", default=None,
        help="目标腾讯文档 fileId（缺省读 PUBLISH_DOC_FILE_ID）",
    )
    p_pub.add_argument(
        "--to", choices=("local", "tencent"), default="tencent",
        help="写入目标（仅支持 tencent）",
    )
    p_pub.set_defaults(func=cmd_publish_results)

    p6 = sub.add_parser("reset-db", help="清空并重建数据库（历史数据清零）")
    p6.add_argument("-y", "--yes", action="store_true", help="跳过二次确认")
    p6.set_defaults(func=cmd_reset_db)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
