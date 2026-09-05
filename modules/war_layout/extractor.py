import re
from hashlib import sha256
from collections.abc import Iterable

from .models import LayoutCandidate, PostPayload

LAYOUT_URL_RE = re.compile(r"https?://link\.clashofclans\.com/[^\s<>]+", re.IGNORECASE)
MAX_LAYOUTS_PER_POST = 5


def normalize_layout_url(url: str) -> str:
    """Remove surrounding punctuation while preserving the deep link."""
    return url.strip().rstrip(".,;!?)]}>")


def layout_fingerprint(layout_url: str) -> str:
    return sha256(normalize_layout_url(layout_url).encode("utf-8")).hexdigest()


def extract_layouts(posts: Iterable[PostPayload], limit: int = MAX_LAYOUTS_PER_POST) -> list[LayoutCandidate]:
    """Return one display candidate per post, grouping all images and links."""
    if limit < 1:
        return []
    layouts: list[LayoutCandidate] = []
    seen: set[str] = set()
    for post in posts:
        links = LAYOUT_URL_RE.findall(post.text)
        if not links or not post.image_urls:
            continue
        urls = tuple(normalize_layout_url(raw) for raw in links)
        fingerprint = layout_fingerprint("|".join(urls) + "|" + "|".join(post.image_urls))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        layouts.append(LayoutCandidate(post.image_urls[0], urls[0], post_id=post.post_id, author=post.author, image_urls=post.image_urls, layout_urls=urls))
        if len(layouts) >= limit:
            return layouts
    return layouts
