from dataclasses import dataclass
from datetime import date
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from .composer import compose_article
from .extractor import extract_layouts, layout_fingerprint
from .models import PostPayload, LayoutCandidate
from .media import ImageMaterializer
from .repository import WarLayoutRepository
from .source_x import XSource
from .wechat_publisher import WeChatDraft, WeChatMassSend, WeChatPublisher


@dataclass(frozen=True)
class RunResult:
    posts: int
    layouts: int
    discovered: int
    skipped: int
    draft: WeChatDraft | None = None
    mass_send: WeChatMassSend | None = None


def public_error_reason(exc: BaseException) -> str:
    """Return a diagnostic that is useful in logs without exposing secrets."""
    reason = getattr(exc, "public_reason", None)
    if reason:
        return str(reason)
    code = getattr(exc, "code", None)
    if code is not None:
        return f"{type(exc).__name__}:{code}"
    return type(exc).__name__


class WarLayoutService:
    def __init__(self, source: XSource, repository: WarLayoutRepository, publisher: WeChatPublisher, materializer: ImageMaterializer | None = None):
        self.source, self.repository, self.publisher, self.materializer = source, repository, publisher, materializer

    def run_once(self, authors: list[str], *, since_id: str | None = None, dry_run: bool = True, published_on: date | None = None, force: bool = False, publish_limit: int | None = None, auto_mass_send: bool = False) -> RunResult:
        if publish_limit is not None and publish_limit < 1:
            raise ValueError("publish_limit must be positive")
        run_started_at = datetime.now(timezone.utc)
        if not dry_run:
            self.repository.initialize()
        posts = self.source.fetch_posts(authors, since_id=since_id)
        if not dry_run:
            # Use each author's persisted watermark.  A first run only looks
            # back 24 hours; subsequent runs are strictly incremental.
            watermark = self.repository.get_global_last_pull_time() or (run_started_at - timedelta(hours=24))
            posts = [post for post in posts if self._in_window(post, watermark, run_started_at)]
            # Newest first makes the per-author five-post cap deterministic.
            posts.sort(key=lambda post: self._post_time(post) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        # Discover candidates first, then apply the per-author daily quota.
        all_layouts = extract_layouts(posts, limit=max(1, len(posts) * 10))
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
            self.repository.record_global_sync(window_start=watermark, window_end=run_started_at, status="success", posts=len(posts), layouts=0)
            return RunResult(len(posts), 0, discovered, skipped)
        publish_layouts = new_layouts if publish_limit is None else new_layouts[:publish_limit]
        try:
            if self.materializer:
                publish_layouts = [self._materialize(layout) for layout in publish_layouts]
            article = compose_article(publish_layouts, published_on)
            draft = self.publisher.create_layout_draft(article["title"], publish_layouts)
        except Exception as exc:
            for layout in publish_layouts:
                self.repository.update_status(
                    layout_fingerprint(layout.layout_url),
                    "failed",
                    error_message=public_error_reason(exc),
                )
            self.repository.record_global_sync(
                window_start=watermark,
                window_end=run_started_at,
                status="failed",
                posts=len(posts),
                layouts=len(publish_layouts),
                error_message=public_error_reason(exc),
            )
            raise
        if draft:
            for layout in publish_layouts:
                self.repository.update_status(layout_fingerprint(layout.layout_url), "draft_created", draft_media_id=draft.media_id)
        mass_send = None
        if draft and auto_mass_send:
            fingerprints = sorted(layout_fingerprint(layout.layout_url) for layout in publish_layouts)
            client_msg_id = sha256("|".join(fingerprints).encode("utf-8")).hexdigest()[:32]
            try:
                mass_send = self.publisher.mass_send_draft(draft, client_msg_id)
            except Exception as exc:
                # The request may have reached WeChat even if the response was
                # lost. Never turn these records back into draft retries.
                send_status = "mass_send_unknown" if getattr(exc, "submission_unknown", True) else "mass_send_failed"
                for layout in publish_layouts:
                    self.repository.update_status(
                        layout_fingerprint(layout.layout_url),
                        send_status,
                        draft_media_id=draft.media_id,
                        mass_send_client_msg_id=client_msg_id,
                        error_message=type(exc).__name__,
                    )
                self.repository.record_global_sync(
                    window_start=watermark,
                    window_end=run_started_at,
                    status="failed",
                    posts=len(posts),
                    layouts=len(publish_layouts),
                    error_message=type(exc).__name__,
                )
                raise
            for layout in publish_layouts:
                self.repository.update_status(
                    layout_fingerprint(layout.layout_url),
                    "mass_send_submitted",
                    draft_media_id=draft.media_id,
                    mass_send_client_msg_id=client_msg_id,
                    mass_send_msg_id=mass_send.msg_id,
                    mass_send_msg_data_id=mass_send.msg_data_id,
                    mass_send_status=mass_send.status,
                )
        self.repository.record_global_sync(
            window_start=watermark,
            window_end=run_started_at,
            status="success",
            posts=len(posts),
            layouts=len(publish_layouts),
        )
        return RunResult(len(posts), len(publish_layouts), discovered, skipped, draft, mass_send)

    def _materialize(self, layout: LayoutCandidate) -> LayoutCandidate:
        """Download every source image once and reuse the first as the cover."""
        assert self.materializer is not None
        fingerprint = layout_fingerprint(layout.layout_url)
        image_paths = tuple(
            str(self.materializer.save(image, f"{fingerprint}-{index}"))
            for index, image in enumerate(layout.image_urls)
        )
        return layout.__class__(
            image_url=image_paths[0],
            layout_url=layout.layout_url,
            caption=layout.caption,
            post_id=layout.post_id,
            author=layout.author,
            image_urls=image_paths,
            layout_urls=layout.layout_urls,
        )

    def refresh_mass_send_statuses(self) -> dict[str, str]:
        self.repository.initialize()
        statuses = {}
        for msg_id in self.repository.pending_mass_send_ids():
            status = self.publisher.query_mass_send_status(msg_id)
            self.repository.update_mass_send_result(msg_id, status)
            statuses[msg_id] = status
        return statuses

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
