from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutCandidate:
    """One layout image and its official share link."""

    image_url: str
    layout_url: str
    caption: str = ""
    post_id: str = ""
    author: str = ""
    image_urls: tuple[str, ...] = ()
    layout_urls: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.image_urls:
            object.__setattr__(self, "image_urls", (self.image_url,))
        if not self.layout_urls:
            object.__setattr__(self, "layout_urls", (self.layout_url,))


@dataclass(frozen=True)
class PostPayload:
    """Minimal source post payload used by pure extraction functions."""

    post_id: str
    author: str
    text: str
    image_urls: tuple[str, ...] = ()
