"""Execute one real war-layout run (database, media, and WeChat draft)."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .scheduler_job import build_http_service
from .settings import WarLayoutSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="execute one war-layout draft run")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--author", help="one configured author to process")
    group.add_argument("--all", action="store_true", help="process all configured authors in one draft")
    parser.add_argument("--force", action="store_true", help="recreate a draft for already published records")
    args = parser.parse_args(argv)
    settings = WarLayoutSettings.from_env()
    settings.validate_x()
    settings.validate_wechat()
    authors = list(settings.authors) if args.all else [args.author.lstrip("@")]  # type: ignore[union-attr]
    if any(author not in settings.authors for author in authors):
        raise SystemExit("author is not configured")
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(settings.db_path))
    try:
        service = build_http_service(connection, settings)
        result = service.run_once(authors, dry_run=False, force=args.force)
        print(json.dumps({
            "authors": authors,
            "posts": result.posts,
            "layouts": result.layouts,
            "discovered": result.discovered,
            "skipped": result.skipped,
            "draft_media_id": result.draft.media_id if result.draft else None,
        }, ensure_ascii=False, indent=2))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
