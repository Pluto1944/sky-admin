import pytest
import requests

from .media import ImageDownloadError, RetryingImageDownloader


class _Response:
    content = b"image"
    headers = {"Content-Type": "image/jpeg"}

    def raise_for_status(self):
        return None


class _FlakySession:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("temporary")
        return _Response()


def test_image_download_retries_transient_connection_errors():
    session = _FlakySession(failures=2)
    sleeps = []
    downloader = RetryingImageDownloader(
        session,
        attempts=4,
        backoff_seconds=(1, 2, 3),
        sleep=sleeps.append,
    )

    blob = downloader("https://pbs.twimg.com/media/example.jpg")

    assert blob.content == b"image"
    assert session.calls == 3
    assert sleeps == [1, 2]


def test_image_download_failure_has_safe_stage_and_host():
    session = _FlakySession(failures=4)
    downloader = RetryingImageDownloader(session, attempts=2, backoff_seconds=(), sleep=lambda _: None)

    with pytest.raises(ImageDownloadError) as caught:
        downloader("https://pbs.twimg.com/media/secret-path.jpg?token=hidden")

    assert str(caught.value) == "ImageDownloadError(pbs.twimg.com, ConnectionError, attempts=2)"
    assert "secret-path" not in str(caught.value)
    assert session.calls == 2
