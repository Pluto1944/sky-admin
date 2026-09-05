from collections.abc import Callable
from dataclasses import dataclass
from html import escape

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
        media_ids = [[self.upload_image(image) for image in layout.image_urls] for layout in layouts]
        body = "".join(
            "".join(f"<p><img src=\"{media_id}\" /></p>" for media_id in image_ids)
            + "".join(f"<p style=\"text-align:left;\">阵型链接：<a href=\"{escape(url, quote=True)}\">{escape(url)}</a></p>" for url in layout.layout_urls)
            + f"<p>来源：{layout.author}</p><p><br /></p>"
            for image_ids, layout in zip(media_ids, layouts)
        )
        cover_media_id = self.upload_cover(layouts[0].image_urls[0]) if self.upload_cover else media_ids[0][0]
        payload = {"title": title, "thumb_media_id": cover_media_id, "content": body}
        draft_id = self.create_draft(payload)
        return WeChatDraft(draft_id, title, cover_media_id, body)
