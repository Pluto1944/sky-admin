import sqlite3
from pathlib import Path

from .media import ImageBlob, ImageMaterializer
from .models import PostPayload
from .repository import WarLayoutRepository
from .service import WarLayoutService
from .source_x import XPage, XSource
from .wechat_publisher import WeChatPublisher


def test_full_mock_pipeline_multiple_authors_global_five_and_idempotent(tmp_path: Path):
    posts = (
        PostPayload("p1", "author-a", " ".join(f"https://link.clashofclans.com/a{i}" for i in range(1, 4)), tuple(f"https://cdn/a{i}.jpg" for i in range(1, 4))),
        PostPayload("p2", "author-b", " ".join(f"https://link.clashofclans.com/b{i}" for i in range(1, 4)), tuple(f"https://cdn/b{i}.jpg" for i in range(1, 4))),
    )
    source = XSource(lambda *_: XPage(posts))
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    repo = WarLayoutRepository(db)
    uploaded = []
    drafts = []
    publisher = WeChatPublisher(
        lambda path: uploaded.append(path) or f"img-{len(uploaded)}",
        lambda payload: drafts.append(payload) or f"draft-{len(drafts)}",
    )
    materializer = ImageMaterializer(lambda url: ImageBlob(url.encode(), "image/jpeg"), tmp_path)
    service = WarLayoutService(source, repo, publisher, materializer)

    first = service.run_once(["author-a", "author-b"], dry_run=False)
    second = service.run_once(["author-a", "author-b"], dry_run=False)

    assert first.layouts == 5
    assert first.discovered == 5
    assert second.skipped == 5
    assert second.draft is None
    assert len(uploaded) == 5
    assert len(drafts) == 1
    assert drafts[0]["thumb_media_id"] == "img-1"
    assert drafts[0]["content"].count("<p><br /></p>") == 5
    assert db.execute("SELECT COUNT(*) FROM war_layout_items").fetchone()[0] == 5
    assert db.execute("SELECT COUNT(*) FROM war_layout_items WHERE status = 'draft_created'").fetchone()[0] == 5
