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
    parser.add_argument("--author", required=True, help="one configured author to process")
    parser.add_argument("--force", action="store_true", help="recreate a draft for already published records")
    args = parser.parse_args(argv)
    settings = WarLayoutSettings.from_env()
    settings.validate_x()
    settings.validate_wechat()
    author = args.author.lstrip("@")
    if author not in settings.authors:
        raise SystemExit(f"author is not configured: {author}")
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(settings.db_path))
    try:
        service = build_http_service(connection, settings)
        result = service.run_once([author], dry_run=False, force=args.force)
        print(json.dumps({
            "author": author,
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
