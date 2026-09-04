"""Offline command entry point for validating the war-layout pipeline.

Usage: python -m modules.war_layout.cli --fixture path/to/posts.json
"""
import argparse
import json
from pathlib import Path

from .composer import compose_article
from .extractor import extract_layouts
from .fixture import load_posts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="war layout dry-run")
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args(argv)
    posts = load_posts(args.fixture)
    layouts = extract_layouts(posts)
    article = compose_article(layouts)
    print(json.dumps({"posts": len(posts), "layouts": len(layouts), "article": article}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
