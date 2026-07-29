"""cwl_registration 报名模块配置：报名表列映射、战营名单、排序权重、输出列。"""

# ---------------------------------------------------------------------------
# 排序权重（综合分计算用，见 rank_score.py）
# ---------------------------------------------------------------------------
SORT_WEIGHTS = {
    "match_value": 0.6,
    "history_score": 0.4,
}


# ---------------------------------------------------------------------------
# 报名表列名映射（关键词包含匹配）：内部字段名 -> {include:[...], exclude:[...]}
#
# 真实表头带换行/空格，且列语义随月份漂移（列位不同），因此不用精确等值匹配，
# 改为"表头去空白后包含任一 include 关键词、且不含任何 exclude 关键词即命中"，
# 命中多个时取第一个。
# ---------------------------------------------------------------------------
REGISTRATION_COLUMN_KEYWORDS = {
    "player_name":  {"include": ["主号游戏昵称", "主号"], "exclude": []},
    "account_name": {"include": ["游戏昵称"], "exclude": ["主号"]},
    "match_value":  {"include": ["匹配值"], "exclude": []},
    "join_combat":  {"include": ["想实战"], "exclude": []},
    "submit_time":  {"include": ["提交时间"], "exclude": []},
}

# 账号标识来源开关（问题 4 根治的预留切换点，当前未接线）。
# 现状：解析阶段不再产出 player_tag，真实账号 Tag 一律由 importer._save 经
# resolve_tag_by_name 按昵称反查回填。待报名表补上真实"玩家Tag"列后，把此项改为
# "player_tag"、在 REGISTRATION_COLUMN_KEYWORDS 补一条 player_tag 规则，并让解析/落库
# 优先采用表内真实 Tag（详见文档 TODO：报名表真实 Tag 列根治重名取分）。
REGISTRATION_TAG_SOURCE = "account_name"

# 报名表内同一 tag（账号名）重复时的去重策略：
#   "latest_submit" -> 保留提交时间最晚的一条，并打印告警。
REGISTRATION_DEDUP = "latest_submit"

# "想实战？" 文本 -> bool
JOIN_COMBAT_TRUE_TEXTS = {"是", "yes", "y", "true", "1", "参加"}


# ---------------------------------------------------------------------------
# 战营名单：其中的账号即战营账号（combat），优先级最高、全部实战。
#
# 数据来源已从"报名表的战营名单 sheet"改为**直接拉取战营部落（#2QQ）的 COC 成员**：
# 导入报名前先对该部落做一次 coc-sync 刷新（奖杯等实时数据），再从 accounts 表
# 按 clan_tag 取成员。这样战营名单始终与部落实际成员一致，奖杯也是最新的。
#
# EXCLUDED_CAMP_NAMES：在 #2QQ 部落内、但不参与联赛排序的账号（按游戏昵称排除），
# 例如管理小号、临时挂靠账号等。过滤在两处生效：
#   - 导入阶段（importer._read_camp）：被排除的成员不进入战营名单集合，不会被
#     标为 combat 类型；但若他们在报名表中报了名，仍会以普通账号身份正常入库。
#   - 排序阶段（roster._load_accounts）：加载报名数据时统一过滤，被排除的账号
#     不参与排序、不出现在最终联赛名单中。此层保证旧残留记录也一并过滤。
# ---------------------------------------------------------------------------
CAMP_CLAN_TAG = "#2QQ"                       # 战营部落标签（成员即战营账号）
EXCLUDED_CAMP_NAMES: set[str] = {"Pluto2QQ", "落花归尘", "misael", "AltriaPendragon", "葉丶"} # 排除名单（不参与排序），如 {"张三", "李四"}

# 旧的 Excel 战营名单 sheet 配置（已弃用，保留仅为兼容历史报名表结构解析）。
CAMP_SHEET_NAME = "战营名单"
CAMP_COLUMN_KEYWORDS = {
    "account_name": {"include": ["游戏昵称"], "exclude": ["主号"]},
    "player_tag":   {"include": ["玩家tag", "tag"], "exclude": []},  # 预留，现为空
    "camp_group":   {"include": ["战营"], "exclude": ["是否"]},
    "match_value":  {"include": ["匹配值"], "exclude": []},          # 预留，现为空
}


# ---------------------------------------------------------------------------
# 名单输出列（顺序即输出表头顺序）
# ---------------------------------------------------------------------------
ARRANGEMENT_OUTPUT_HEADERS = [
    "rank_order",
    "league_type",
    "player_tag",
    "account_name",
    "player_name",
    "account_type",
    "prev_rank",
    "trophies",
    "match_value",
    "history_score",
]
