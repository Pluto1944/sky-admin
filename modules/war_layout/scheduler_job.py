from pathlib import Path
from typing import Any

import requests

from .media import ImageMaterializer, RetryingImageDownloader
from .service import WarLayoutService, public_error_reason
from .settings import WarLayoutSettings
from .source_x import XSource
from .wechat_http import WeChatHttpClient
from .wechat_publisher import WeChatPublisher
from .x_http import XHttpTransport
from .socialdata_source import SocialDataSource


def run_job(service: WarLayoutService, settings: WarLayoutSettings, *, dry_run: bool = True, auto_mass_send: bool | None = None) -> dict[str, Any]:
    """Scheduler-safe wrapper returning a serializable status dictionary."""
    try:
        settings.validate_x()
        if not dry_run:
            settings.validate_wechat()
        # The environment setting is the hard safety gate.  The optional
        # argument may suppress a send, but must never enable one while
        # WAR_LAYOUT_AUTO_MASS_SEND is disabled.
        should_mass_send = settings.auto_mass_send and auto_mass_send is not False
        result = service.run_once(list(settings.authors), dry_run=dry_run, auto_mass_send=should_mass_send and not dry_run)
        response = {
            "status": "success",
            "posts": result.posts,
            "layouts": result.layouts,
            "discovered": result.discovered,
            "skipped": result.skipped,
            "draft_media_id": result.draft.media_id if result.draft else None,
            "mass_send_msg_id": result.mass_send.msg_id if result.mass_send else None,
        }
        if should_mass_send and not dry_run:
            try:
                response["mass_send_statuses"] = service.refresh_mass_send_statuses()
            except Exception as exc:
                response["mass_send_status_error"] = type(exc).__name__
        return response
    except Exception as exc:  # scheduler must record failure and continue other jobs
        return {"status": "failed", "reason": public_error_reason(exc)}


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

    # Images may need a proxy even when SocialData and WeChat are reachable
    # directly. Keep that route isolated so other jobs and paid API calls are
    # unaffected by the image egress configuration.
    image_http = http
    if settings.image_proxy_url:
        settings.validate_image_proxy()
        image_http = requests.Session()
        image_http.trust_env = False
        image_http.proxies.update({
            "http": settings.image_proxy_url,
            "https": settings.image_proxy_url,
        })
    materializer = ImageMaterializer(RetryingImageDownloader(image_http), Path(settings.media_dir))
    publisher = WeChatPublisher(
        wechat.upload_content_image,
        wechat.create_draft,
        upload_cover=wechat.upload_cover,
        mass_send=wechat.mass_send_all,
        get_mass_send_status=wechat.get_mass_send_status,
    )
    from .repository import WarLayoutRepository

    return WarLayoutService(x_source, WarLayoutRepository(connection), publisher, materializer)
