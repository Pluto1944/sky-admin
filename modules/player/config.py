"""player 模块配置。"""

# 连续未报名达到该月数则标记为 maybe_left（疑似离开）
MAYBE_LEFT_MONTHS = 2


# ---------------------------------------------------------------------------
# 玩家档案导出（player-export）
#
# 导出列（顺序即表头顺序）：内部字段名 -> 中文表头。集中一处便于增删列。
# 表头用中文便于在本地/在线文档里直接查看；键为 accounts 列或读取时派生的字段
# （last_reg_period 由 registrations 实时派生）。按月维度列（账号类型/匹配值/实战/
# 战营顺序）已下沉 registrations，不在账号级导出中。
PLAYER_EXPORT_COLUMNS = {
    "player_tag":         "玩家Tag",
    "account_name":       "游戏昵称",
    "player_name":        "归属人",
    "town_hall_level":    "大本",
    "exp_level":          "等级",
    "trophies":           "奖杯",
    "league_name":        "段位",
    "clan_tag":           "部落Tag",
    "clan_role":          "部落职位",
    "membership_status":  "部落身份",
    "status":             "报名状态",
    "history_score":      "历史分",
    "last_reg_period":    "最后报名",
    "last_synced_at":     "最后同步",
    "updated_at":         "更新时间",
}

# 导出默认排序：字段名 + 是否降序（None 值统一排到末尾）
PLAYER_EXPORT_DEFAULT_SORT = "history_score"
PLAYER_EXPORT_DEFAULT_DESC = True

# 默认写入的 sheet 名
PLAYER_EXPORT_SHEET = "玩家档案"
