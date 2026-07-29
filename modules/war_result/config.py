"""war_result 战绩模块配置：战绩表列映射（关键词，与报名侧一致）。

修复隐患 #3：原先战绩表用**精确列名**「玩家Tag」取 tag，与报名侧"关键词映射 +
游戏昵称当 tag"的过渡方案对不上，导致取不到 tag 时整表静默跳过、或 tag 体系不
一致 join 不上账号。现改为与报名一致的**关键词映射**，且 tag 也从"游戏昵称"取，
从而两侧对齐。后续接入真实 Tag 时，把 RESULT_TAG_SOURCE 改为 "player_tag" 并
在关键词映射补一条 player_tag 规则即可。
"""

# 战绩表列名映射（关键词包含匹配）：内部字段名 -> {include:[...], exclude:[...]}
RESULT_COLUMN_KEYWORDS = {
    "account_name": {"include": ["游戏昵称", "账号名"], "exclude": ["主号"]},
    "player_tag":   {"include": ["玩家tag", "tag"], "exclude": []},  # 预留，现多为空
    "league_type":  {"include": ["联赛类型", "联赛"], "exclude": []},
}

# 账号标识过渡开关：与报名侧保持一致，用账号名（游戏昵称）临时充当 player_tag。
RESULT_TAG_SOURCE = "account_name"
