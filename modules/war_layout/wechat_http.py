from pathlib import Path
from typing import Any

import requests
import json


class WeChatApiError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, submission_unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.submission_unknown = submission_unknown


class WeChatHttpClient:
    """微信公众号素材、草稿和认证账号群发 API client."""

    def __init__(self, app_id: str, app_secret: str, session: Any = None, timeout: float = 20):
        self.app_id, self.app_secret = app_id, app_secret
        self.session, self.timeout = session or requests.Session(), timeout
        self._access_token: str | None = None

    def access_token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self.session.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": self.app_id, "secret": self.app_secret},
            timeout=self.timeout,
        )
        payload = self._json(response)
        self._raise_error(payload)
        self._access_token = payload["access_token"]
        return self._access_token

    def upload_content_image(self, image_path: str) -> str:
        response = self._post_file("https://api.weixin.qq.com/cgi-bin/media/uploadimg", image_path)
        payload = self._json(response)
        self._raise_error(payload)
        return payload["url"]

    def upload_cover(self, image_path: str) -> str:
        response = self._post_file("https://api.weixin.qq.com/cgi-bin/material/add_material", image_path, media_type="image")
        payload = self._json(response)
        self._raise_error(payload)
        return payload["media_id"]

    def create_draft(self, payload: dict) -> str:
        body = {"articles": [{"title": payload["title"], "thumb_media_id": payload["thumb_media_id"], "content": payload["content"]}]}
        response = self.session.post(
            "https://api.weixin.qq.com/cgi-bin/draft/add",
            params={"access_token": self.access_token()},
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=self.timeout,
        )
        result = self._json(response)
        self._raise_error(result)
        return result["media_id"]

    def mass_send_all(self, media_id: str, client_msg_id: str) -> dict[str, str]:
        body = {
            "filter": {"is_to_all": True},
            "mpnews": {"media_id": media_id},
            "msgtype": "mpnews",
            # Stop rather than silently replacing the article when WeChat's
            # originality check identifies content owned by another account.
            "send_ignore_reprint": 0,
            "clientmsgid": client_msg_id,
        }
        response = self.session.post(
            "https://api.weixin.qq.com/cgi-bin/message/mass/sendall",
            params={"access_token": self.access_token()},
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=self.timeout,
        )
        result = self._json(response)
        self._raise_error(result)
        return {
            "msg_id": str(result["msg_id"]),
            "msg_data_id": str(result.get("msg_data_id", "")),
        }

    def get_mass_send_status(self, msg_id: str) -> str:
        response = self.session.post(
            "https://api.weixin.qq.com/cgi-bin/message/mass/get",
            params={"access_token": self.access_token()},
            data=json.dumps({"msg_id": msg_id}).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=self.timeout,
        )
        result = self._json(response)
        self._raise_error(result)
        return str(result["msg_status"])

    def _post_file(self, url: str, image_path: str, **extra) -> Any:
        path = Path(image_path)
        if not path.is_file():
            raise WeChatApiError("image file not found")
        return self.session.post(
            url,
            params={"access_token": self.access_token(), **extra},
            files={"media": (path.name, path.read_bytes(), "application/octet-stream")},
            timeout=self.timeout,
        )

    @staticmethod
    def _json(response: Any) -> dict:
        try:
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (requests.RequestException, ValueError) as exc:
            raise WeChatApiError("WeChat API request failed", submission_unknown=True) from exc

    @staticmethod
    def _raise_error(payload: dict) -> None:
        if payload.get("errcode", 0):
            raise WeChatApiError(f"WeChat API error {payload['errcode']}", code=int(payload["errcode"]))
