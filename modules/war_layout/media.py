from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
import time
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class ImageBlob:
    content: bytes
    content_type: str


class ImageDownloadError(RuntimeError):
    """Safe, retry-aware error for a remote layout image."""

    def __init__(self, host: str, cause: BaseException, attempts: int):
        self.public_reason = (
            f"ImageDownloadError({host}, {type(cause).__name__}, attempts={attempts})"
        )
        super().__init__(self.public_reason)


class RetryingImageDownloader:
    """Download images with bounded retries without retrying paid source APIs."""

    def __init__(
        self,
        session,
        *,
        timeout: float = 20,
        attempts: int = 4,
        backoff_seconds: tuple[float, ...] = (5, 15, 30),
        sleep=time.sleep,
    ):
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self.session = session
        self.timeout = timeout
        self.attempts = attempts
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep

    def __call__(self, url: str) -> ImageBlob:
        host = urlparse(url).hostname or "unknown-host"
        last_error: BaseException | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return ImageBlob(response.content, response.headers.get("Content-Type", ""))
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.attempts or not self._is_retryable(exc):
                    break
                if self.backoff_seconds:
                    delay_index = min(attempt - 1, len(self.backoff_seconds) - 1)
                    self.sleep(self.backoff_seconds[delay_index])
        if last_error is None:  # pragma: no cover - every loop exit records one
            raise RuntimeError("image download failed without an exception")
        raise ImageDownloadError(host, last_error, attempt) from last_error

    @staticmethod
    def _is_retryable(exc: requests.RequestException) -> bool:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return exc.response.status_code == 429 or exc.response.status_code >= 500
        return False


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
