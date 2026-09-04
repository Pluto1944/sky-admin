from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .models import PostPayload


@dataclass(frozen=True)
class XPage:
    posts: tuple[PostPayload, ...]
    next_token: str | None = None


class XSource:
    """Small X API adapter; HTTP is injected so dry-runs stay deterministic."""

    def __init__(self, transport: Callable[[str, str | None], XPage]):
        self.transport = transport

    def fetch_posts(self, authors: Iterable[str], *, since_id: str | None = None, max_pages: int = 10) -> list[PostPayload]:
        if max_pages < 1:
            return []
        result: list[PostPayload] = []
        for author in authors:
            token: str | None = None
            for _ in range(max_pages):
                page = self.transport(author, token)
                result.extend(post for post in page.posts if since_id is None or post.post_id > since_id)
                if not page.next_token:
                    break
                token = page.next_token
        return result


def dry_run_summary(posts: Iterable[PostPayload]) -> dict[str, int]:
    posts = list(posts)
    return {"posts": len(posts), "authors": len({post.author for post in posts}), "images": sum(len(post.image_urls) for post in posts)}
