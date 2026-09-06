import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import PostPayload
from .repository import WarLayoutRepository
from .service import WarLayoutService
from .source_x import XPage, XSource
from .wechat_publisher import WeChatPublisher
from .media import ImageBlob, ImageMaterializer


def test_dry_run_does_not_write_or_publish():
    db = sqlite3.connect(":memory:")
    source = XSource(lambda *_: XPage((PostPayload("p", "a", "https://link.clashofclans.com/x", ("https://img/x",)),)))
    publisher = WeChatPublisher(lambda _: (_ for _ in ()).throw(AssertionError()), lambda _: (_ for _ in ()).throw(AssertionError()))
    result = WarLayoutService(source, WarLayoutRepository(db), publisher).run_once(["a"], dry_run=True)
    assert (result.posts, result.layouts) == (1, 1)


def test_execute_is_idempotent():
    db = sqlite3.connect(":memory:")
    source = XSource(lambda *_: XPage((PostPayload("p", "a", "https://link.clashofclans.com/x", ("https://img/x",)),)))
    created = []
    publisher = WeChatPublisher(lambda _: "media-1", lambda payload: created.append(payload) or "draft-1")
    service = WarLayoutService(source, WarLayoutRepository(db), publisher)
    first = service.run_once(["a"], dry_run=False)
    second = service.run_once(["a"], dry_run=False)
    assert first.discovered == 1
    assert second.skipped == 1
    assert second.draft is None
    assert len(created) == 1


def test_daily_limit_is_five_per_author():
    db = sqlite3.connect(":memory:")
    links = " ".join(f"https://link.clashofclans.com/{i}" for i in range(6))
    images = tuple(f"https://img/{i}" for i in range(6))
    service = WarLayoutService(
        XSource(lambda *_: XPage((PostPayload("p", "a", links, images),))),
        WarLayoutRepository(db),
        WeChatPublisher(lambda _: "m", lambda _: "draft"),
    )
    result = service.run_once(["a"], dry_run=False)
    assert result.layouts == 1
    assert db.execute("SELECT COUNT(*) FROM war_layout_items").fetchone()[0] == 1


def test_failed_draft_is_retryable():
    db = sqlite3.connect(":memory:")
    source = XSource(lambda *_: XPage((PostPayload("p", "a", "https://link.clashofclans.com/x", ("https://img/x",)),)))
    attempts = []
    def create(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise RuntimeError("temporary")
        return "draft-1"
    service = WarLayoutService(source, WarLayoutRepository(db), WeChatPublisher(lambda _: "m", create))
    try:
        service.run_once(["a"], dry_run=False)
    except RuntimeError:
        pass
    result = service.run_once(["a"], dry_run=False)
    assert result.discovered == 1 and result.draft.media_id == "draft-1"


def test_layout_keeps_exact_source_post_metadata():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    posts = (
        PostPayload("p1", "a", "https://link.clashofclans.com/1", ("https://img/same",)),
        PostPayload("p2", "b", "https://link.clashofclans.com/2", ("https://img/same",)),
    )
    service = WarLayoutService(XSource(lambda *_: XPage(posts)), WarLayoutRepository(db), WeChatPublisher(lambda _: "m", lambda _: "d"))
    service.run_once(["a"], dry_run=False)
    rows = db.execute("SELECT post_id, author FROM war_layout_items ORDER BY id").fetchall()
    assert [tuple(row) for row in rows] == [("p1", "a"), ("p2", "b")]


def test_execute_materializes_images_outside_git_tree(tmp_path):
    db = sqlite3.connect(":memory:")
    source = XSource(lambda *_: XPage((PostPayload("p", "a", "https://link.clashofclans.com/x", ("https://img/x",)),)))
    uploaded = []
    publisher = WeChatPublisher(lambda path: uploaded.append(path) or "media-1", lambda _: "draft-1")
    materializer = ImageMaterializer(lambda _: ImageBlob(b"x", "image/jpeg"), tmp_path)
    WarLayoutService(source, WarLayoutRepository(db), publisher, materializer).run_once(["a"], dry_run=False)
    assert Path(uploaded[0]).parent == tmp_path


def test_execute_uses_per_author_incremental_watermark():
    db = sqlite3.connect(":memory:")
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=2)).isoformat()
    recent = (now - timedelta(minutes=5)).isoformat()
    posts = (
        PostPayload("old", "a", "https://link.clashofclans.com/old", ("https://img/old",), old),
        PostPayload("recent", "a", "https://link.clashofclans.com/recent", ("https://img/recent",), recent),
    )
    service = WarLayoutService(
        XSource(lambda *_: XPage(posts)),
        WarLayoutRepository(db),
        WeChatPublisher(lambda _: "m", lambda _: "d"),
    )
    result = service.run_once(["a"], dry_run=False)
    assert result.posts == 1
    assert result.layouts == 1
    assert db.execute("SELECT post_id FROM war_layout_items").fetchone()[0] == "recent"
