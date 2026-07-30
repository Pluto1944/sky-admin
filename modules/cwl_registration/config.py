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
    "team_name",        # 队伍分配结果
    "movement",         # 升降级标识（v2.4）↑升级/↓降级/空
    "player_tag",
    "account_name",
    "player_name",
    "account_type",
    "prev_rank",
    "trophies",
    "match_value",
    "history_score",
]


# ---------------------------------------------------------------------------
# 队伍填充配置（队伍分配阶段使用）
# ---------------------------------------------------------------------------

# 参加实战的最低匹配值：低于此值的账号强制转为壳子
COMBAT_MIN_MATCH_VALUE = 600

# TEAMS 列表：按顺序定义所有联赛队伍，"category"列决定收 combat 还是 shell。
# reserved_slots: >0 留空位 / 0 不预留 / <0 多招备选(容量=member_count+abs(reserved))
# 列表顺序即分配优先级：实战团队从前到后依次填充，壳子团队同理。
TEAMS = [
    # ===== 实战队伍 =====
    {"name": "泰坦二",    "clan_tag": "#2QQ",       "leader": "", "member_count": 15, "league_level": "", "manager": "xxx", "category": "combat", "reserved_slots": 0},
    {"name": "冠一 一队",  "clan_tag": "#2GGGGGGG",  "leader": "", "member_count": 15, "league_level": "", "manager": "yyy", "category": "combat", "reserved_slots": 0},
    {"name": "冠一 二队",  "clan_tag": "#2JP8PLQLJ", "leader": "", "member_count": 15, "league_level": "", "manager": "zzz", "category": "combat", "reserved_slots": 0},
    {"name": "冠三",      "clan_tag": "#2QQQQ2G",   "leader": "", "member_count": 15, "league_level": "", "manager": "www", "category": "combat", "reserved_slots": 0},
    {"name": "大一",      "clan_tag": "#2R8RCPY0J",  "leader": "", "member_count": 15, "league_level": "", "manager": "www", "category": "combat", "reserved_slots": 0},
    {"name": "大一",      "clan_tag": "#2C9QCL892",  "leader": "", "member_count": 30, "league_level": "", "manager": "www", "category": "combat", "reserved_slots": 0},
    {"name": "大一",      "clan_tag": "#2CU9JPYU8",  "leader": "", "member_count": 30, "league_level": "", "manager": "www", "category": "combat", "reserved_slots": 0},

    # ===== 壳子队伍 =====
    {"name": "大一",      "clan_tag": "#AAAAA",      "leader": "", "member_count": 30, "league_level": "", "manager": "aaa", "category": "shell",  "reserved_slots": 0},
    {"name": "大三",      "clan_tag": "#BBBBB",      "leader": "", "member_count": 30, "league_level": "", "manager": "bbb", "category": "shell",  "reserved_slots": 0},
    {"name": "水一",      "clan_tag": "#CCCCC",      "leader": "", "member_count": 30, "league_level": "", "manager": "ccc", "category": "shell",  "reserved_slots": 0},
    {"name": "水二",      "clan_tag": "#DDDDD",      "leader": "", "member_count": 30, "league_level": "", "manager": "ddd", "category": "shell",  "reserved_slots": 0},
]

# 队伍分配输出表头（队伍详情的列）
TEAM_OUTPUT_HEADERS = [
    "rank_order",
    "account_name",
    "player_name",
    "match_value",
    "league_type",
    "trophies",
    "history_score",
]


# ---------------------------------------------------------------------------
# 升降级配置
#
# 在 fill_teams() 完成基础队伍分配后，根据上月实战星数在相邻实战队伍间
# 执行人员交换（见 promotion.apply_promotion_relegation）。
#
# 设计理由：
# - 升级门槛 21/21（满星）：避免"接近满星"的人升到更强队后表现断崖
# - 降级门槛 ≤18/21：给 19-20 星留安全区，防一两次失误即降级
# - 星数离散（0-21 整数），天然有 ≥3 星的 gap，无需额外 rate_gap 保护
# ---------------------------------------------------------------------------
PROMOTION_RELEGATION_CONFIG = {
    "count": 2,                  # 每对相邻队伍最多交换人数
    "promotion_min_stars": 21,   # 升级门槛：≥ 此值才可升级（满星）
    "relegation_max_stars": 18,  # 降级门槛：≤ 此值触发降级
}
