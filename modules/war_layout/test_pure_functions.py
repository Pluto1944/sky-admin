from datetime import date

from .composer import compose_article
from .extractor import extract_layouts
from .models import LayoutCandidate, PostPayload


def test_extract_pairs_images_and_links_and_limits_to_five():
    text = " ".join(f"https://link.clashofclans.com/en?action=OpenLayout&id={i}" for i in range(1, 7))
    post = PostPayload("p1", "author", text, tuple(f"https://img/{i}.jpg" for i in range(1, 7)))
    layouts = extract_layouts([post])
    assert len(layouts) == 1
    assert layouts[0].image_url.endswith("1.jpg")
    assert len(layouts[0].layout_urls) == 6


def test_limit_is_global_across_posts():
    posts = [PostPayload(str(i), "a", f"https://link.clashofclans.com/{i}", (f"https://img/{i}.jpg",)) for i in range(1, 8)]
    assert len(extract_layouts(posts)) == 5


def test_unrelated_posts_without_official_layout_link_are_skipped():
    posts = [
        PostPayload("other", "a", "今天的比赛回顾", ("https://img/other.jpg",)),
        PostPayload("layout", "a", "https://link.clashofclans.com/layout", ("https://img/layout.jpg",)),
    ]
    layouts = extract_layouts(posts)
    assert len(layouts) == 1
    assert layouts[0].post_id == "layout"


def test_compose_uses_first_image_as_cover_and_blank_line_between_layouts():
    layouts = [LayoutCandidate("https://img/1.jpg", "https://link.clashofclans.com/a", author="alice")]
    article = compose_article(layouts, date(2026, 9, 3))
    assert article["title"] == "国际服-顶尖冲杯阵型 2026-09-03"
    assert article["cover_image_url"] == "https://img/1.jpg"
    assert "来源：alice" in article["body"]
    assert article["body"].endswith("<p><br /></p>")
