from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
from urllib.parse import urlparse


@dataclass(frozen=True)
class ImageBlob:
    content: bytes
    content_type: str


class ImageMaterializer:
    def __init__(self, downloader: Callable[[str], ImageBlob], root: Path, max_bytes: int = 10 * 1024 * 1024):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.downloader, self.root, self.max_bytes = downloader, root, max_bytes

    def save(self, image_url: str, fingerprint: str) -> Path:
        parsed = urlparse(image_url)
        if parsed.scheme != "https":
            raise ValueError("image URL must use HTTPS")
        blob = self.downloader(image_url)
        if not blob.content_type.lower().startswith("image/"):
            raise ValueError("downloaded content is not an image")
        if len(blob.content) > self.max_bytes:
            raise ValueError("image exceeds size limit")
        self.root.mkdir(parents=True, exist_ok=True)
        mime = blob.content_type.lower().split(";", 1)[0].strip()
        suffix = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".jpg")
        path = self.root / f"{fingerprint}{suffix}"
        fd, temporary = tempfile.mkstemp(prefix=f".{fingerprint}.", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob.content)
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return path
