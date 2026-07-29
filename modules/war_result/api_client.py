"""COC 官方 API 战绩查询客户端（预留，暂不实现）。

近期战绩以 Excel 导入为主，本客户端仅预留接口。实现时需遵守安全约束：

安全设计（务必落地）：
- 密钥：COC_API_TOKEN 只从**环境变量**读取，绝不入库、绝不提交仓库。
- SSRF 防护：**硬编码只允许**官方域名 api.clashofclans.com，拒绝一切内网地址
  （127./10./172.16-31./192.168. 及安全规则里列出的 9./10./11./21./30.*）。
- tag 参数做 URL 编码（'#' -> '%23'）。

实现后由 war_result.importer 或独立命令调用，把查得的 war/cwl 战绩写入 results 表。
"""
from __future__ import annotations

ALLOWED_HOST = "api.clashofclans.com"
BASE_URL = "https://api.clashofclans.com/v1"


class CocWarApiClient:
    """占位实现，尚未接入。调用即抛出明确错误。"""

    def __init__(self, token: str | None = None):
        # 预留：token 应来自环境变量 COC_API_TOKEN，不接受硬编码明文
        self._token = token

    def get_clan_war_league(self, clan_tag: str) -> dict:
        raise NotImplementedError(
            "COC 官方 API 战绩查询尚未实现，请先使用 Excel 导入（import-result）。"
        )

    def get_current_war(self, clan_tag: str) -> dict:
        raise NotImplementedError(
            "COC 官方 API 战绩查询尚未实现，请先使用 Excel 导入（import-result）。"
        )
