"""clashking 子模块：ClashKing 第三方 API 封装。

提供 ClashKing 公开 API 的 HTTP 调用能力，主要用于 CWL 历史战绩的兜底拉取。

接口：
- /war/{clan_tag}/previous — 历史战争日志（从中筛选 CWL 战斗）

数据来源：https://api.clashk.ing
认证：公开端点无需 Token
速率：30 req/s
"""
