from dataclasses import dataclass
from datetime import date

from .composer import compose_article
from .extractor import extract_layouts, layout_fingerprint
from .models import PostPayload
from .media import ImageMaterializer
from .repository import WarLayoutRepository
from .source_x import XSource
from .wechat_publisher import WeChatDraft, WeChatPublisher


@dataclass(frozen=True)
class RunResult:
    posts: int
    layouts: int
    discovered: int
    skipped: int
    draft: WeChatDraft | None = None


class WarLayoutService:
    def __init__(self, source: XSource, repository: WarLayoutRepository, publisher: WeChatPublisher, materializer: ImageMaterializer | None = None):
        self.source, self.repository, self.publisher, self.materializer = source, repository, publisher, materializer

    def run_once(self, authors: list[str], *, since_id: str | None = None, dry_run: bool = True, published_on: date | None = None, force: bool = False) -> RunResult:
        posts = self.source.fetch_posts(authors, since_id=since_id)
        layouts = extract_layouts(posts)
        if dry_run:
            return RunResult(len(posts), len(layouts), 0, 0)
        self.repository.initialize()
        discovered = skipped = 0
        new_layouts = []
        for layout in layouts:
            inserted = self.repository.add_discovered(
                post_id=layout.post_id,
                author=layout.author,
                fingerprint=layout_fingerprint(layout.layout_url),
                layout_url=layout.layout_url,
                image_url=layout.image_url,
            )
            existing = self.repository.get(layout_fingerprint(layout.layout_url))
            if existing is None:
                retryable = False
            else:
                status = existing["status"] if hasattr(existing, "keys") else existing[6]
                retryable = status in ("discovered", "failed") or (force and status == "draft_created")
            if inserted or retryable:
                discovered += 1
                new_layouts.append(layout)
            else:
                skipped += 1
        if not new_layouts:
            return RunResult(len(posts), len(layouts), discovered, skipped)
        publish_layouts = new_layouts
        if self.materializer:
            publish_layouts = [
                layout.__class__(
                    image_url=str(self.materializer.save(layout.image_url, layout_fingerprint(layout.layout_url))),
                    layout_url=layout.layout_url,
                    caption=layout.caption,
                    post_id=layout.post_id,
                    author=layout.author,
                )
                for layout in new_layouts
            ]
        article = compose_article(publish_layouts, published_on)
        try:
            draft = self.publisher.create_layout_draft(article["title"], publish_layouts)
        except Exception as exc:
            for layout in new_layouts:
                self.repository.update_status(
                    layout_fingerprint(layout.layout_url),
                    "failed",
                    error_message=type(exc).__name__,
                )
            raise
        if draft:
            for layout in new_layouts:
                self.repository.update_status(layout_fingerprint(layout.layout_url), "draft_created", draft_media_id=draft.media_id)
        return RunResult(len(posts), len(layouts), discovered, skipped, draft)
