"""② cwl_registration CWL 报名模块。

两大功能：
1. 每月把报名结果导入并更新到 player 模块（importer.py）。
2. 根据 player 模块信息生成报名/联赛名单（roster.py，即原 arrange_league 行为）。

自身维护 registrations 表（月度报名快照）。
"""
