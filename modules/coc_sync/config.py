"""coc_sync 模块配置：要查询并汇总成员的部落清单与同步策略。

只放 coc_sync 自己的参数；跨模块公共常量仍在 shared/config/common.py。
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 要同步汇总的部落列表。
# coc-sync 会遍历 enabled=True 的部落，拉取全部成员，按真实 Tag 汇总去重后写入
# player 档案。name 仅用于日志/展示；临时不想同步某部落时把 enabled 置 False 即可
# （无需删配置）。tag 以 '#' 开头，大小写不敏感（客户端会规范化）。
# ---------------------------------------------------------------------------
CLANS = [
    {"tag": "#2QQ", "name": "云深不知处 战营", "enabled": True},
    {"tag": "#LQR", "name": "秋雨不问梧桐意", "enabled": True},
    {"tag": "#U2L", "name": "仙境", "enabled": True},
    {"tag": "#2COUL898", "name": "Avalon", "enabled": True},
    {"tag": "#YCOC", "name": "Minecraft(互刷一营)", "enabled": True},
    {"tag": "#9V9", "name": "清风追明月(互刷二营)", "enabled": True},
    {"tag": "#U2UL", "name": "白马啸西风(互刷三营)", "enabled": True},
    {"tag": "#R88U8", "name": "苍穹(互刷四营)", "enabled": True},
    {"tag": "#2LRQ88JQR", "name": "新手村(互刷五营)", "enabled": True},
    {"tag": "#U89", "name": "执手听风吟(互刷六营)", "enabled": True},
    {"tag": "#2JU", "name": "清夜坠玄天(互刷七营)", "enabled": True},
    {"tag": "#L0YLR02L", "name": "冰风谷wy(互刷八营)", "enabled": True},
    # {"tag": "#YYYYY", "name": "苍穹三部", "enabled": False},  # 临时不同步
]

# 同一真实 Tag 出现在多个部落时的处理：
#   "warn"   -> 告警并只保留首次出现（首个部落）
#   "silent" -> 静默只保留首次出现
DUP_ACROSS_CLANS = "warn"

# 单部落抓取失败是否中断整体：
#   False -> 跳过该部落、继续其余（推荐，与战绩导入"跳过+告警"风格一致）
#   True  -> 直接抛出，终止本次同步
FAIL_FAST = False


def alliance_clan_tags() -> list[str]:
    """联盟旗下所有部落 tag（含临时 enabled=False 的）。

    退部对账时用它判断"玩家的新部落是否仍属联盟"：enabled=False 只表示本次不
    主动同步该部落，并不代表它脱离联盟，因此转入这类部落的成员不应被判为退部。
    返回原始 tag（未规范化），大小写/'#' 由调用方统一规范化后比较。
    """
    return [c["tag"] for c in CLANS]
