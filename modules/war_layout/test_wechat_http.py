from pathlib import Path
import json

from .wechat_http import WeChatHttpClient


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): return None
    def json(self): return self.payload


class Session:
    def __init__(self): self.calls = []
    def get(self, url, **kwargs): self.calls.append(("GET", url, kwargs)); return Response({"access_token": "token"})
    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if "uploadimg" in url: return Response({"url": "https://wx/img"})
        if "material/add" in url: return Response({"media_id": "cover-1"})
        if "mass/sendall" in url: return Response({"errcode": 0, "msg_id": 123, "msg_data_id": 456})
        if "mass/get" in url: return Response({"errcode": 0, "msg_id": 123, "msg_status": "SEND_SUCCESS"})
        return Response({"media_id": "draft-1"})


def test_wechat_client_uploads_material_and_creates_draft(tmp_path: Path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"image")
    session = Session()
    client = WeChatHttpClient("app", "secret", session=session)
    assert client.upload_content_image(str(image)) == "https://wx/img"
    assert client.upload_cover(str(image)) == "cover-1"
    assert client.create_draft({"title": "t", "thumb_media_id": "cover-1", "content": "c"}) == "draft-1"
    assert client.mass_send_all("draft-1", "dedupe-1") == {"msg_id": "123", "msg_data_id": "456"}
    assert client.get_mass_send_status("123") == "SEND_SUCCESS"
    send_call = next(call for call in session.calls if "mass/sendall" in call[1])
    send_body = json.loads(send_call[2]["data"])
    assert send_body["filter"] == {"is_to_all": True}
    assert send_body["mpnews"] == {"media_id": "draft-1"}
    assert send_body["clientmsgid"] == "dedupe-1"
    assert sum(1 for kind, _, _ in session.calls if kind == "GET") == 1
