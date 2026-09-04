import pytest

from .socialdata_source import SocialDataSource
from .socialdata_guard import SocialDataBudgetExceeded


class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class Session:
    def __init__(self): self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(url)
        return Response({"tweets": [{"id_str": "1", "full_text": "layout", "entities": {"urls": [{"expanded_url": "https://link.clashofclans.com/en?action=OpenLayout&id=1"}]}, "extended_entities": {"media": [{"type": "photo", "media_url_https": "https://img/1"}]}}]})


def test_socialdata_source_requires_id_and_returns_one_page():
    session = Session(); source = SocialDataSource("key", session=session, user_ids={"alice": "42"})
    page = source("alice", None); source("alice", None)
    assert len(page.posts) == 1 and page.posts[0].image_urls == ("https://img/1",)
    assert len(session.calls) == 2
    assert all("monitor" not in u for u in session.calls)

    with pytest.raises(Exception, match="user id"):
        source("bob", None)


def test_socialdata_source_rejects_pagination_and_budget():
    source = SocialDataSource("key", session=Session())
    with pytest.raises(Exception): source("alice", "cursor")
    source.guard.check_and_record(); source.guard.check_and_record(); source.guard.check_and_record()
    with pytest.raises(SocialDataBudgetExceeded): source.guard.check_and_record()
