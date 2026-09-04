import json
from pathlib import Path

from .models import PostPayload


def load_posts(path: Path) -> list[PostPayload]:
    """Load the small offline fixture format used by the dry-run command."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("fixture must be a JSON array")
    return [
        PostPayload(
            post_id=str(item["post_id"]),
            author=str(item["author"]),
            text=str(item.get("text", "")),
            image_urls=tuple(str(url) for url in item.get("image_urls", [])),
        )
        for item in payload
    ]
