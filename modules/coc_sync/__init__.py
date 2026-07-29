"""④ coc_sync 模块：通过 COC 官方 API 建档/更新 player。

- api_client.py：底层 HTTP 客户端（token/SSRF/超时），仅本模块内部调用。
- mapper.py：纯函数，COC 原始 dict -> player 档案 COC 组标准字段。
- config.py：要查询汇总的部落清单与同步策略。
- service.py：CocSyncService，唯一 API 编排出口（多部落汇总去重、写库、合并临时账号）。
"""
