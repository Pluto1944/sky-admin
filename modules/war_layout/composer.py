from datetime import date
from html import escape

from .models import LayoutCandidate


def compose_article(layouts: list[LayoutCandidate], published_on: date | None = None) -> dict[str, str | None]:
    """Create the deterministic公众号 article representation."""
    day = published_on or date.today()
    title = f"国际服-顶尖冲杯阵型 {day.isoformat()}"
    body_parts: list[str] = []
    for layout in layouts[:5]:
        body_parts.extend((
            "".join(f"<p><img src=\"{image}\" /></p>" for image in layout.image_urls),
            "".join(f"<p style=\"text-align:left;\">阵型链接：<a href=\"{escape(url, quote=True)}\">{escape(url)}</a></p>" for url in layout.layout_urls),
            f"<p>来源：{layout.author}</p>",
            "<p><br /></p>",
        ))
    return {"title": title, "cover_image_url": layouts[0].image_url if layouts else None, "body": "".join(body_parts)}
