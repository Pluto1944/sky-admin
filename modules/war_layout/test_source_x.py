from .models import PostPayload
from .source_x import XPage, XSource, dry_run_summary


def test_fetches_pages_in_author_order_and_supports_dry_run():
    calls = []

    def transport(author, token):
        calls.append((author, token))
        if author == "a" and token is None:
            return XPage((PostPayload("1", "a", "", ()),), "next")
        if author == "a":
            return XPage((PostPayload("2", "a", "", ()),))
        return XPage((PostPayload("3", "b", "", ()),))

    posts = XSource(transport).fetch_posts(["a", "b"])
    assert [post.post_id for post in posts] == ["1", "2", "3"]
    assert calls == [("a", None), ("a", "next"), ("b", None)]
    assert dry_run_summary(posts) == {"posts": 3, "authors": 2, "images": 0}
