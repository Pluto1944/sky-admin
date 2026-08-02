"""official 子模块：Supercell Clash of Clans 官方 API 封装。

提供 COC 官方 API 的 HTTP 调用能力和数据映射工具。

- api_client.py：底层 HTTP 客户端（token/SSRF/超时），仅本模块内部调用。
- mapper.py：纯函数，COC 原始 dict -> player 档案 COC 组标准字段。

数据来源：https://api.clashofclans.com
认证：需要 COC_API_TOKEN 环境变量
"""
