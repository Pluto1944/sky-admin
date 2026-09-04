from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutCandidate:
    """One layout image and its official share link."""

    image_url: str
    layout_url: str
    caption: str = ""
    post_id: str = ""
    author: str = ""


@dataclass(frozen=True)
class PostPayload:
    """Minimal source post payload used by pure extraction functions."""

    post_id: str
    author: str
    text: str
    image_urls: tuple[str, ...] = ()
