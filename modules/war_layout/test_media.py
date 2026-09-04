from pathlib import Path

import pytest

from .media import ImageBlob, ImageMaterializer


def test_materializer_saves_https_image(tmp_path: Path):
    materializer = ImageMaterializer(lambda _: ImageBlob(b"data", "image/jpeg"), tmp_path)
    path = materializer.save("https://img.example/a", "abc")
    assert path == tmp_path / "abc.jpg"
    assert path.read_bytes() == b"data"


@pytest.mark.parametrize("url,blob", [
    ("http://img.example/a", ImageBlob(b"x", "image/jpeg")),
    ("https://img.example/a", ImageBlob(b"x", "text/html")),
])
def test_materializer_rejects_unsafe_or_non_image(url, blob, tmp_path):
    with pytest.raises(ValueError):
        ImageMaterializer(lambda _: blob, tmp_path).save(url, "abc")


def test_materializer_preserves_webp_extension_and_rejects_invalid_limit(tmp_path):
    materializer = ImageMaterializer(lambda _: ImageBlob(b"x", "image/webp; charset=binary"), tmp_path)
    assert materializer.save("https://img.example/a", "abc").suffix == ".webp"
    with pytest.raises(ValueError):
        ImageMaterializer(lambda _: ImageBlob(b"x", "image/jpeg"), tmp_path, max_bytes=0)
