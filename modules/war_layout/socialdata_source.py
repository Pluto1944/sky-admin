"""Low-cost SocialData Data API source (Monitoring API is intentionally absent)."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

import requests

from .models import PostPayload
from .socialdata_guard import SocialDataBudgetGuard
from .source_x import XPage


class SocialDataError(RuntimeError):
    pass


class SocialDataSource:
    """Fetch one timeline page per author with a hard free-budget guard.

    This class exposes the same callable shape as ``XHttpTransport``. It never
    follows cursors, retries requests, or calls SocialData Monitoring APIs.
    """

    BASE_URL = "https://api.socialdata.tools/twitter"

    def __init__(self, api_key: str, session: Any = None, guard: SocialDataBudgetGuard | None = None, timeout: float = 20, user_ids: dict[str, str] | None = None):
        if not api_key:
            raise ValueError("SOCIALDATA_API_KEY is required")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self.guard = guard or SocialDataBudgetGuard()
        self._user_ids: dict[str, str] = dict(user_ids or {})

    def __call__(self, author: str, pagination_token: str | None) -> XPage:
        if pagination_token:
            raise SocialDataError("SocialData source does not support pagination")
        username = author.lstrip("@")
        user_id = self._user_ids.get(username)
        if not user_id:
            # Looking up a profile costs another Data API request.  Requiring
            # a preconfigured numeric ID keeps the free-budget guarantee
            # enforceable even when this adapter is used directly.
            raise SocialDataError("SocialData user id is not configured")
        # Search narrows the response to likely layout posts.  The user
        # timeline endpoint has no page-size control and would charge for
        # every ordinary tweet returned.
        query = f"from:{username} -filter:replies link.clashofclans.com"
        payload = self._get(f"/search?{urlencode({'query': query, 'type': 'Latest'})}")
        posts = []
        for item in payload.get("tweets", []):
            text = item.get("full_text") or item.get("text") or ""
            # X often keeps links only in entities (the visible text contains
            # a t.co URL).  Append expanded URLs so the pure extractor can
            # apply the same official-link rule to both response shapes.
            entity_urls = item.get("entities", {}).get("urls", [])
            expanded = [u.get("expanded_url") or u.get("unwound_url") or u.get("url") for u in entity_urls if isinstance(u, dict)]
            if expanded:
                text = f"{text} {' '.join(url for url in expanded if url)}"
            media = item.get("extended_entities", {}).get("media", [])
            if not media:
                media = item.get("entities", {}).get("media", [])
            image_urls = tuple(m.get("media_url_https") or m.get("media_url") or m.get("url") for m in media if m.get("type") == "photo" and (m.get("media_url_https") or m.get("media_url") or m.get("url")))
            post_id = str(item.get("id_str") or item.get("id") or "")
            if post_id:
                posts.append(PostPayload(post_id, username, text, image_urls, item.get("tweet_created_at") or item.get("created_at")))
        return XPage(tuple(posts), None)

    def _get(self, path: str) -> dict:
        self.guard.check_and_record()
        try:
            response = self.session.get(f"{self.BASE_URL}{path}", headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SocialDataError(f"SocialData request failed: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise SocialDataError("SocialData returned invalid JSON")
        if payload.get("status") == "error":
            raise SocialDataError("SocialData returned an error")
        return payload
