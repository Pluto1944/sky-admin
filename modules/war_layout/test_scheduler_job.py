import sqlite3

from .models import PostPayload
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
