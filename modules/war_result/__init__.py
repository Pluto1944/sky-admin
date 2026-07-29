"""③ war_result 战绩模块。

查询 war / cwl 战绩并更新到 player 模块的历史分。近期以 Excel 导入为主
（importer.py），COC 官方 API 仅预留接口（api_client.py，暂不实现）。
自身维护 results 表（月度多指标战绩）。
"""
