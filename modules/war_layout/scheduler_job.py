from pathlib import Path
from typing import Any

import requests

from .media import ImageBlob, ImageMaterializer
from .service import WarLayoutService
from .settings import WarLayoutSettings
from .source_x import XSource
from .wechat_http import WeChatHttpClient
from .wechat_publisher import WeChatPublisher
from .x_http import XHttpTransport
from .socialdata_source import SocialDataSource


def run_job(service: WarLayoutService, settings: WarLayoutSettings, *, dry_run: bool = True) -> dict[str, Any]:
    """Scheduler-safe wrapper returning a serializable status dictionary."""
    try:
        settings.validate_x()
        if not dry_run:
            settings.validate_wechat()
        result = service.run_once(list(settings.authors), dry_run=dry_run)
        return {
            "status": "success",
            "posts": result.posts,
            "layouts": result.layouts,
            "discovered": result.discovered,
            "skipped": result.skipped,
            "draft_media_id": result.draft.media_id if result.draft else None,
        }
    except Exception as exc:  # scheduler must record failure and continue other jobs
        return {"status": "failed", "reason": type(exc).__name__}


def build_http_service(connection, settings: WarLayoutSettings, *, session: Any = None) -> WarLayoutService:
    """Construct the real HTTP-backed service without opening a DB connection."""
    http = session or requests.Session()
    if settings.source == "socialdata":
        from .socialdata_guard import SocialDataBudgetGuard
        x_transport = SocialDataSource(settings.socialdata_api_key, session=http, user_ids=settings.socialdata_user_ids, guard=SocialDataBudgetGuard(max_requests=settings.socialdata_max_requests))
    else:
        x_transport = XHttpTransport(settings.x_bearer_token, session=http)
    x_source = XSource(x_transport)
    # WeChat IP whitelisting must see the server's direct egress address;
    # don't let the Codex/Hermes proxy environment affect these requests.
    wechat_http = requests.Session()
    wechat_http.trust_env = False
    wechat = WeChatHttpClient(settings.wechat_app_id, settings.wechat_app_secret, session=wechat_http)

    def download(url: str) -> ImageBlob:
        response = http.get(url, timeout=20)
        response.raise_for_status()
        return ImageBlob(response.content, response.headers.get("Content-Type", ""))

    materializer = ImageMaterializer(download, Path(settings.media_dir))
    publisher = WeChatPublisher(wechat.upload_content_image, wechat.create_draft, upload_cover=wechat.upload_cover)
    from .repository import WarLayoutRepository

    return WarLayoutService(x_source, WarLayoutRepository(connection), publisher, materializer)
