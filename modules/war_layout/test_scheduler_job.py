import sqlite3
from types import SimpleNamespace

import requests

from .models import PostPayload
from .media import ImageDownloadError
from .repository import WarLayoutRepository
from .scheduler_job import run_job
from .service import WarLayoutService
from .settings import WarLayoutSettings
from .source_x import XPage, XSource
from .wechat_publisher import WeChatPublisher


def _service():
    source = XSource(lambda *_: XPage((PostPayload("p", "a", "https://link.clashofclans.com/x", ("https://img/x",)),)))
    publisher = WeChatPublisher(lambda _: "m", lambda _: "d")
    return WarLayoutService(source, WarLayoutRepository(sqlite3.connect(":memory:")), publisher)


def test_scheduler_wrapper_returns_serializable_success():
    result = run_job(_service(), WarLayoutSettings(("a",), "token"), dry_run=True)
    assert result["status"] == "success"
    assert result["layouts"] == 1


def test_scheduler_wrapper_hides_error_details():
    result = run_job(_service(), WarLayoutSettings((), ""), dry_run=True)
    assert result == {"status": "failed", "reason": "ValueError"}


def test_scheduler_wrapper_reports_safe_image_failure_stage():
    class _FailingService:
        def run_once(self, *args, **kwargs):
            raise ImageDownloadError("pbs.twimg.com", requests.ConnectionError("secret"), 4)

    result = run_job(_FailingService(), WarLayoutSettings(("a",), "token"), dry_run=True)

    assert result == {
        "status": "failed",
        "reason": "ImageDownloadError(pbs.twimg.com, ConnectionError, attempts=4)",
    }


class _CapturingService:
    def __init__(self):
        self.auto_mass_send = None

    def run_once(self, authors, *, dry_run, auto_mass_send):
        self.auto_mass_send = auto_mass_send
        return SimpleNamespace(
            posts=0,
            layouts=0,
            discovered=0,
            skipped=0,
            draft=None,
            mass_send=None,
        )

    def refresh_mass_send_statuses(self):
        return {}


def test_scheduler_switch_cannot_be_bypassed_by_true_override():
    service = _CapturingService()
    settings = WarLayoutSettings(("a",), "token", wechat_app_id="app", wechat_app_secret="secret")

    result = run_job(service, settings, dry_run=False, auto_mass_send=True)

    assert result["status"] == "success"
    assert service.auto_mass_send is False


def test_scheduler_switch_allows_explicit_mass_send_when_enabled():
    service = _CapturingService()
    settings = WarLayoutSettings(
        ("a",),
        "token",
        wechat_app_id="app",
        wechat_app_secret="secret",
        auto_mass_send=True,
    )

    result = run_job(service, settings, dry_run=False, auto_mass_send=True)

    assert result["status"] == "success"
    assert service.auto_mass_send is True
