"""Read-only live dry-run for validating the configured post data source."""
from __future__ import annotations

import argparse
import json
from typing import Any

import requests

from .composer import compose_article
from .extractor import extract_layouts
from .settings import WarLayoutSettings
from .socialdata_source import SocialDataSource
from .socialdata_guard import SocialDataBudgetGuard
from .source_x import XSource
from .x_http import XHttpTransport


def run_live_dry_run(settings: WarLayoutSettings, *, session: Any = None, authors: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Fetch one page per configured author without any writes or publishing."""
    settings.validate_x()
    http = session or requests.Session()
    if settings.source == "socialdata":
        transport = SocialDataSource(
            settings.socialdata_api_key,
            session=http,
            user_ids=settings.socialdata_user_ids,
            guard=SocialDataBudgetGuard(max_requests=settings.socialdata_max_requests),
        )
    else:
        transport = XHttpTransport(settings.x_bearer_token, session=http)
    selected_authors = authors or settings.authors
    posts = XSource(transport).fetch_posts(list(selected_authors), max_pages=1)
    all_layouts = extract_layouts(posts, limit=max(1, len(posts) * 10))
    layouts = all_layouts[:5]
    article = compose_article(layouts)
    return {
        "source": settings.source,
        "authors": len(selected_authors),
        "posts": len(posts),
        "posts_with_images": sum(bool(post.image_urls) for post in posts),
        "layouts_found": len(all_layouts),
        "layouts_selected": len(layouts),
        "article": article,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read-only live war-layout dry-run")
    parser.add_argument("--pretty", action="store_true", help="pretty-print the JSON result")
    parser.add_argument("--author", help="test only one configured author")
    args = parser.parse_args(argv)
    settings = WarLayoutSettings.from_env()
    authors = (args.author.lstrip("@"),) if args.author else None
    result = run_live_dry_run(settings, authors=authors)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
