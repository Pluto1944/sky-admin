from .models import LayoutCandidate
from .wechat_publisher import WeChatPublisher


def test_publisher_uploads_in_order_and_creates_draft_only():
    uploaded = []
    payloads = []

    def upload(url):
        uploaded.append(url)
        return f"media-{len(uploaded)}"

    def create(payload):
        payloads.append(payload)
        return "draft-1"

    layouts = [LayoutCandidate("https://img/1", "https://link/1"), LayoutCandidate("https://img/2", "https://link/2")]
    draft = WeChatPublisher(upload, create).create_layout_draft("冲杯阵2026-09-03", layouts)
    assert uploaded == ["https://img/1", "https://img/2"]
    assert draft.media_id == "draft-1"
    assert payloads[0]["thumb_media_id"] == "media-1"
    assert payloads[0]["content"].count("<p><br /></p>") == 2
    assert "来源：" in payloads[0]["content"]


def test_empty_layouts_do_not_call_api():
    publisher = WeChatPublisher(lambda _: (_ for _ in ()).throw(AssertionError()), lambda _: (_ for _ in ()).throw(AssertionError()))
    assert publisher.create_layout_draft("x", []) is None
