"""One-page, read-only X smoke test.

Run from the repository root:
    venv/bin/python -m modules.war_layout.test_x_live

This script loads the root .env, never prints credentials, and does not write
the database, download images, or call the WeChat API.
"""
from shared.config.env_loader import load_env

from .settings import WarLayoutSettings
from .x_http import XApiError, XHttpTransport


def main() -> int:
    load_env()
    settings = WarLayoutSettings.from_env()
    settings.validate_x()
    transport = XHttpTransport(settings.x_bearer_token)
    failures = 0
    for author in settings.authors:
        try:
            page = transport(author, None)
            print({
                "author": author,
                "posts": len(page.posts),
                "posts_with_images": sum(bool(post.image_urls) for post in page.posts),
                "has_next_page": bool(page.next_token),
            })
        except XApiError as exc:
            failures += 1
            print({"author": author, "status": "failed", "reason": type(exc).__name__})
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
