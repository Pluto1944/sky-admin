"""① player 玩家中枢模块。

管理部落内各账号的长期档案（accounts 表），是全系统的数据中枢：
其他模块（报名 / 战绩 / coc_sync）都通过 PlayerService 读写账号数据，
不直接操作 accounts 表。player 本身不反向依赖任何业务模块，杜绝循环依赖。
"""
