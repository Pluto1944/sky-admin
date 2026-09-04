from collections.abc import Callable
from dataclasses import dataclass

from .models import LayoutCandidate


@dataclass(frozen=True)
class WeChatDraft:
    media_id: str
    title: str
    cover_media_id: str
    body: str


class WeChatPublisher:
    """公众号 draft-only publisher; transport is injected for API isolation."""

    def __init__(self, upload_image: Callable[[str], str], create_draft: Callable[[dict], str], upload_cover: Callable[[str], str] | None = None):
        self.upload_image = upload_image
        self.create_draft = create_draft
        self.upload_cover = upload_cover

    def create_layout_draft(self, title: str, layouts: list[LayoutCandidate]) -> WeChatDraft | None:
        if not layouts:
            return None
        media_ids = [self.upload_image(layout.image_url) for layout in layouts[:5]]
        body = "".join(
            f"<p><img src=\"{media_id}\" /></p><p>{layout.layout_url}</p>"
            f"<p>来源：{layout.author}</p><p><br /></p>"
            for media_id, layout in zip(media_ids, layouts[:5])
        )
        cover_media_id = self.upload_cover(layouts[0].image_url) if self.upload_cover else media_ids[0]
        payload = {"title": title, "thumb_media_id": cover_media_id, "content": body}
        draft_id = self.create_draft(payload)
        return WeChatDraft(draft_id, title, cover_media_id, body)
