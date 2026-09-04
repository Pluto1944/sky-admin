from .x_http import XHttpTransport


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): return None
    def json(self): return self.payload


class Session:
    def __init__(self): self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "/by/username/" in url:
            return Response({"data": {"id": "42"}})
        return Response({
            "data": [{"id": "100", "text": "layout", "attachments": {"media_keys": ["m1", "v1"]}}],
            "includes": {"media": [
                {"media_key": "m1", "type": "photo", "url": "https://img/1.jpg"},
                {"media_key": "v1", "type": "video", "preview_image_url": "https://img/video.jpg"},
            ]},
            "meta": {"next_token": "next"},
        })


def test_transport_resolves_user_parses_photos_and_paginates():
    session = Session()
    transport = XHttpTransport("secret", session=session)
    page = transport("author", "page-2")
    assert page.posts[0].image_urls == ("https://img/1.jpg",)
    assert page.next_token == "next"
    assert session.calls[1][1]["params"]["pagination_token"] == "page-2"
    transport("author", None)
    assert len([url for url, _ in session.calls if "/by/username/" in url]) == 1
