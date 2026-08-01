"""COC 官方 API 账号信息查询客户端。

安全设计（已落地）：
- 密钥：COC_API_TOKEN 只从**环境变量**读取，绝不入库、绝不提交仓库。
- SSRF 防护：采用**白名单(allowlist)**机制——只放行官方域名 api.clashofclans.com
  且强制 https，请求前再用 urlparse 校验 scheme/host。任何其它目标（含各类内网地址
  127./10./172.16-31./192.168. 及安全规则列出的 9./10./11./21./30.* 等）因不在白名单内
  一律被拒，无需逐个黑名单匹配（白名单比黑名单更严、更安全）。
- tag 参数做 URL 编码（'#' -> '%23'）。
- 请求设超时，避免挂起。
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ALLOWED_HOST = "api.clashofclans.com"
BASE_URL = "https://api.clashofclans.com/v1"
DEFAULT_TIMEOUT = 15  # 秒


class CocApiError(RuntimeError):
    """COC API 调用失败（网络、鉴权、HTTP 错误码等）。"""


class CocApiClient:
    """Clash of Clans 官方 API 客户端。"""

    def __init__(self, token: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        # 密钥仅来自环境变量，绝不硬编码；构造时不强制读取，避免无 token 环境导入即失败
        self._token = token or os.environ.get("COC_API_TOKEN")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def get_clan_members(self, clan_tag: str) -> list[dict]:
        """给定部落标签，返回该部落所有成员的信息列表。

        每个成员至少包含：tag / name / role / expLevel / trophies /
        league / clanRank / donations 等（由官方 API 决定）。
        """
        data = self._get(f"/clans/{self._encode_tag(clan_tag)}/members")
        return data.get("items", [])

    def get_clan(self, clan_tag: str) -> dict:
        """查询部落概要信息（含 memberList）。"""
        return self._get(f"/clans/{self._encode_tag(clan_tag)}")

    def get_player(self, player_tag: str) -> dict:
        """按玩家 Tag 查询单个账号信息。"""
        return self._get(f"/players/{self._encode_tag(player_tag)}")

    # ------------------------------------------------------------------
    # CWL 相关接口
    # ------------------------------------------------------------------
    def get_clan_warlog(self, clan_tag: str, limit: int | None = None) -> list[dict]:
        """查询部落战争日志。GET /clans/{clanTag}/warlog

        返回战争列表，每条含 result / teamSize / opponent / endTime 等。
        注意：warlog 不含 warTag 字段，不能用于回溯 CWL 明细。
        """
        path = f"/clans/{self._encode_tag(clan_tag)}/warlog"
        if limit is not None:
            path += f"?limit={limit}"
        data = self._get(path)
        return data.get("items", [])

    def get_cwl_war(self, war_tag: str) -> dict:
        """查询单场 CWL 战争详情。GET /clanwarleagues/wars/{warTag}

        返回 clan / opponent 双方的成员名单及每人每场进攻明细（stars / attacks）。
        """
        return self._get(f"/clanwarleagues/wars/{self._encode_tag(war_tag)}")

    def get_league_group(self, clan_tag: str) -> dict | None:
        """查询部落当前联赛组信息。GET /clans/{clanTag}/currentwar/leaguegroup

        仅在 CWL 周返回有效数据；非 CWL 周或部落未参赛时返回 None。
        返回含 season / state / rounds[].warTags[] 等。
        """
        try:
            return self._get(f"/clans/{self._encode_tag(clan_tag)}/currentwar/leaguegroup")
        except CocApiError as e:
            if "404" in str(e):
                return None
            # 403 等错误原样上抛，让调用方看到具体原因（如 IP 白名单问题）
            raise

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_tag(tag: str) -> str:
        """规范化并 URL 编码 tag：确保以 '#' 开头、转大写、'#' -> '%23'。"""
        if not tag or not tag.strip():
            raise ValueError("tag 不能为空")
        t = tag.strip().upper()
        if not t.startswith("#"):
            t = "#" + t
        # 只对单个 path 段做编码，不放行 '/' 等分隔符，防止路径穿越
        return quote(t, safe="")

    def _get(self, path: str) -> dict:
        if not self._token:
            raise CocApiError(
                "缺少 COC_API_TOKEN 环境变量，请先设置后再调用（切勿硬编码密钥）。"
            )

        url = f"{BASE_URL}{path}"
        # SSRF 兜底校验：即便 BASE_URL 固定，也再确认 scheme/host 合法
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise CocApiError(f"非法请求目标，仅允许 https://{ALLOWED_HOST}")

        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise CocApiError(f"COC API 返回错误 {e.code}: {detail}") from e
        except URLError as e:
            raise CocApiError(f"请求 COC API 失败：{e.reason}") from e

        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise CocApiError("COC API 响应不是合法 JSON") from e
