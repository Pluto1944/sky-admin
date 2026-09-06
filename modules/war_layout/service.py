from dataclasses import dataclass
from datetime import date
from datetime import datetime, timedelta, timezone

from .composer import compose_article
from .extractor import extract_layouts, layout_fingerprint
from .models import PostPayload, LayoutCandidate
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

    def run_once(self, authors: list[str], *, since_id: str | None = None, dry_run: bool = True, published_on: date | None = None, force: bool = False, publish_limit: int | None = None) -> RunResult:
        if publish_limit is not None and publish_limit < 1:
            raise ValueError("publish_limit must be positive")
        run_started_at = datetime.now(timezone.utc)
        if not dry_run:
            self.repository.initialize()
        posts = self.source.fetch_posts(authors, since_id=since_id)
        if not dry_run:
            # Use each author's persisted watermark.  A first run only looks
            # back 24 hours; subsequent runs are strictly incremental.
            watermarks = {
                author: self.repository.get_last_pull_time(author)
                or (run_started_at - timedelta(hours=24))
                for author in authors
            }
            posts = [post for post in posts if self._in_window(post, watermarks.get(post.author), run_started_at)]
            # Newest first makes the per-author five-post cap deterministic.
            posts.sort(key=lambda post: self._post_time(post) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        # Discover candidates first, then apply the per-author daily quota.
        all_layouts = extract_layouts(posts, limit=max(1, len(posts) * 10))
        # Apply the daily quota independently for each author. Overflow is
        # intentionally discarded and never persisted as a backlog.
        author_counts: dict[str, int] = {}
        layouts = []
        for layout in all_layouts:
            count = author_counts.get(layout.author, 0)
            if count >= 5:
                continue
            layouts.append(layout)
            author_counts[layout.author] = count + 1
        if dry_run:
            return RunResult(len(posts), len(layouts), 0, 0)
        discovered = skipped = 0
        new_layouts = []
        for layout in layouts:
            inserted = self.repository.add_discovered(
                post_id=layout.post_id,
                author=layout.author,
                fingerprint=layout_fingerprint(layout.layout_url),
                layout_url=layout.layout_url,
                image_url=layout.image_url,
                layout_urls=layout.layout_urls,
                image_urls=layout.image_urls,
            )
            existing = self.repository.get(layout_fingerprint(layout.layout_url))
            if existing is None:
                retryable = False
            else:
                status = existing["status"] if hasattr(existing, "keys") else existing[6]
                # In daily no-buffer mode, only failed records are retried;
                # old discovered rows from the former queue are left as
                # historical backlog and must not be republished implicitly.
                retryable = status == "failed" or (force and status in ("discovered", "draft_created"))
            if inserted or retryable:
                discovered += 1
                new_layouts.append(layout)
            else:
                skipped += 1
        if not new_layouts:
            for author in authors:
                self.repository.set_last_pull_time(author, run_started_at)
            return RunResult(len(posts), 0, discovered, skipped)
        publish_layouts = new_layouts if publish_limit is None else new_layouts[:publish_limit]
        if self.materializer:
            publish_layouts = [
                layout.__class__(
                    image_url=str(self.materializer.save(layout.image_urls[0], layout_fingerprint(layout.layout_url))),
                    layout_url=layout.layout_url,
                    caption=layout.caption,
                    post_id=layout.post_id,
                    author=layout.author,
                    image_urls=tuple(str(self.materializer.save(image, layout_fingerprint(layout.layout_url) + f"-{index}")) for index, image in enumerate(layout.image_urls)),
                    layout_urls=layout.layout_urls,
                )
                for layout in publish_layouts
            ]
        article = compose_article(publish_layouts, published_on)
        try:
            draft = self.publisher.create_layout_draft(article["title"], publish_layouts)
        except Exception as exc:
            for layout in publish_layouts:
                self.repository.update_status(
                    layout_fingerprint(layout.layout_url),
                    "failed",
                    error_message=type(exc).__name__,
                )
            raise
        if draft:
            for layout in publish_layouts:
                self.repository.update_status(layout_fingerprint(layout.layout_url), "draft_created", draft_media_id=draft.media_id)
        for author in authors:
            self.repository.set_last_pull_time(author, run_started_at)
        return RunResult(len(posts), len(publish_layouts), discovered, skipped, draft)

    @staticmethod
    def _post_time(post: PostPayload) -> datetime | None:
        if not post.created_at:
            return None
        try:
            parsed = datetime.fromisoformat(post.created_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _in_window(cls, post: PostPayload, start: datetime, end: datetime) -> bool:
        timestamp = cls._post_time(post)
        # Fixtures and older sources may not provide timestamps; retain them
        # and let post-id/fingerprint deduplication provide idempotency.
        return timestamp is None or start <= timestamp <= end
