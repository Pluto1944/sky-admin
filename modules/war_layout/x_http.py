from typing import Any

import requests

from .models import PostPayload
from .source_x import XPage


class XApiError(RuntimeError):
    pass


class XHttpTransport:
    """X API v2 user timeline transport implementing the XSource callback."""

    def __init__(self, bearer_token: str, session: Any = None, timeout: float = 20):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {bearer_token}"}
        self._user_ids: dict[str, str] = {}

    def __call__(self, author: str, pagination_token: str | None) -> XPage:
        user_id = self._resolve_user_id(author)
        params = {
            "max_results": 100,
            "exclude": "retweets,replies",
            "expansions": "attachments.media_keys",
            "media.fields": "media_key,type,url,preview_image_url",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token
        payload = self._get(f"https://api.x.com/2/users/{user_id}/tweets", params=params)
        media = {item["media_key"]: item for item in payload.get("includes", {}).get("media", [])}
        posts = []
        for item in payload.get("data", []):
            keys = item.get("attachments", {}).get("media_keys", [])
            image_urls = tuple(
                media[key].get("url") or media[key].get("preview_image_url")
                for key in keys
                if key in media and media[key].get("type") == "photo" and (media[key].get("url") or media[key].get("preview_image_url"))
            )
            posts.append(PostPayload(str(item["id"]), author, item.get("text", ""), image_urls))
        return XPage(tuple(posts), payload.get("meta", {}).get("next_token"))

    def _resolve_user_id(self, author: str) -> str:
        author = author.lstrip("@")
        if author not in self._user_ids:
            payload = self._get(f"https://api.x.com/2/users/by/username/{author}")
            try:
                self._user_ids[author] = str(payload["data"]["id"])
            except (KeyError, TypeError) as exc:
                raise XApiError(f"X user not found: @{author}") from exc
        return self._user_ids[author]

    def _get(self, url: str, **kwargs) -> dict:
        try:
            response = self.session.get(url, headers=self.headers, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise XApiError(f"X API request failed: {type(exc).__name__}") from exc
