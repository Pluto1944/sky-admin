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
    """Aggregate posts in source order and cap the total number of layouts."""
    if limit < 1:
        return []
    layouts: list[LayoutCandidate] = []
    seen: set[str] = set()
    for post in posts:
        for image_url, raw_url in zip(post.image_urls, LAYOUT_URL_RE.findall(post.text)):
            url = normalize_layout_url(raw_url)
            fingerprint = layout_fingerprint(url)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            layouts.append(LayoutCandidate(
                image_url=image_url,
                layout_url=url,
                post_id=post.post_id,
                author=post.author,
            ))
            if len(layouts) >= limit:
                return layouts
    return layouts
