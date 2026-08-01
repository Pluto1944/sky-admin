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
    "player_name":        {"include": ["主号游戏昵称", "主号"], "exclude": []},
    "account_name":       {"include": ["游戏昵称"], "exclude": ["主号"]},
    "match_value":        {"include": ["匹配值"], "exclude": []},
    "join_combat":        {"include": ["想实战"], "exclude": []},
    "submit_time":        {"include": ["提交时间"], "exclude": []},
    "willing_to_manage":  {"include": ["愿意做联赛管理员"], "exclude": []},
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
EXCLUDED_CAMP_NAMES: set[str] = {"Pluto2QQ", "落花归尘", "misael", "AltriaPendragon", "葉丶", "飞的煎饼", "幻想鄉", "Timo⚡️Z⚔️ephyr™"} # 排除名单（不参与排序），如 {"张三", "李四"}

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
    "cur_team",         # 当月队伍（"index alias coc_name" 拼接）
    "prev_team",        # 上月队伍（"index alias" 拼接）
    "movement",         # 升降级标识（v2.4）↑升级/↓降级/空
    "player_tag",
    "account_name",
    "player_name",
    "team_name",        # COC 真实部落名称（新增）
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
    {"name": "泰坦二",    "clan_tag": "#2QQ",       "leader": "leader2QQ", "member_count": 15, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},
    {"name": "冠一 一队",  "clan_tag": "#2GGGGGGG",  "leader": "leader5", "member_count": 15, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},
    {"name": "冠二",      "clan_tag": "#2C822CJJC", "leader": "Pluto leader6", "member_count": 15, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},
    {"name": "冠三",      "clan_tag": "#2QQQQ2G",   "leader": "leader4", "member_count": 15, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},
    {"name": "大一",      "clan_tag": "#UUP2",  "leader": "leader", "member_count": 15, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},
    {"name": "大一",      "clan_tag": "#CYYL",  "leader": "leader2", "member_count": 30, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},
    {"name": "大一",      "clan_tag": "#2CU9JPYU8",  "leader": "南门 ", "member_count": 30, "league_level": "", "manager": "", "category": "combat", "reserved_slots": 0},

    # ===== 壳子队伍 =====
    {"name": "大一",      "clan_tag": "#2R9Y209LY",      "leader": "leader10", "member_count": 30, "league_level": "", "manager": "", "category": "shell",  "reserved_slots": 0},
    {"name": "大三",      "clan_tag": "#2JQR89P9G",      "leader": "leader6", "member_count": 30, "league_level": "", "manager": "", "category": "shell",  "reserved_slots": 0},
    {"name": "水一",      "clan_tag": "#2JUJRYVQP",      "leader": "登悟", "member_count": 30, "league_level": "", "manager": "", "category": "shell",  "reserved_slots": 0},
    {"name": "水二",      "clan_tag": "#2GR0LPGVQ",      "leader": "leader8", "member_count": 30, "league_level": "", "manager": "", "category": "shell",  "reserved_slots": 0},
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


# ---------------------------------------------------------------------------
# 备选管理员名单（顺序即优先级，从前往后）
# 队伍分配完成后，对每个队伍按此顺序逐个查询成员是否包含该管理员
# （按 account_name 精确匹配），命中则设为该队伍管理员并从候选池移除，
# 后续队伍不再匹配该管理员；全部未命中则为空。
# ---------------------------------------------------------------------------
MANAGER_CANDIDATES: list[str] = [
    # ===== 当前 TEAMS 队伍的历史管理员 =====
    "鸟不拉不拉",       # 泰坦二 #2QQ
    "ELIKI",            # 冠一 一队 #2GGGGGGG
    "Sunken ship",      # 冠二 #2C822CJJC（手动添加）
    "TT",               # 冠三 #2QQQQ2G
    "星空之翼",         # 大一 #UUP2
    "QAQ",              # 大一 #CYYL（手动添加）
    "星空:宗主",        # 大一 #2CU9JPYU8
    "Ghost✨Almighty",  # 手动添加
    "小小龙",           # 手动添加
    "帝都",             # 大一(壳) #2R9Y209LY
    "武瞾",             # 大三(壳) #2JQR89P9G
    "武曌",             # 大三(壳) 历史变体
    "Always",           # 水一(壳) #2JUJRYVQP
    "always",           # 水一(壳) 历史变体
    "ghost",            # 水一/水二(壳) 历史
    "yolo",             # 水一(壳) 历史
    "Always#3",         # 水二(壳) #2GR0LPGVQ
    "沉舟大大1号",      # 水二(壳) 历史
    "爱吃贝果小太阳",   # 水二(壳) 历史

    # ===== 历史出现过的其他管理员（其他 clan_tag） =====
    "Snzed",
    "于我",
    "如梦",
    "故浅",
    "芝士芒果龙利鱼",
    "苏瞬卿",
    "虚伪、",
]

# ---------------------------------------------------------------------------
# 黑名单与白名单（基准升降级方案 v3.0）
#
# 黑名单：其中的账号不出现在任何队伍中。在阶段0（前置过滤）从所有数据源排除。
# 白名单：每一项 (account_name, clan_tag) 强制安排到指定队伍开头。在阶段8
#         （队伍填充后）处理，即使该账号没报名也强制插入。
# ---------------------------------------------------------------------------
BLACK_LIST: set[str] = set()

WHITE_LIST: list[tuple[str, str]] = [("10°C✨Godwin 2", "#2QQ"),]

# 战营新增人员起始插入编号（第3队开头，前两支高等级队不放新人）
NEW_COMBAT_INSERT_START = 30

# 普通营新增人员起始插入编号（已废弃：现改为追加到实战区末尾，不再按编号插入）
# 保留此常量仅为兼容旧引用，当前逻辑中不再生效。
NEW_NORMAL_INSERT_START = 45
