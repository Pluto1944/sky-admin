"""④ coc_sync 模块：COC 数据获取与同步。

子模块：
- official/：Supercell 官方 API 封装（api_client + mapper）
- clashking/：ClashKing 第三方 API 封装（CWL 历史战绩兜底拉取）

服务层：
- service.py：CocSyncService，唯一 API 编排出口（多部落汇总去重、写库、合并临时账号）。
"""
