from .live_dry_run import run_live_dry_run
from .settings import WarLayoutSettings


class Response:
    def raise_for_status(self):
        pass

    def json(self):
        return {"tweets": [{"id_str": "1", "full_text": "https://link.clashofclans.com/en?action=OpenLayout&id=1", "entities": {"media": [{"type": "photo", "media_url_https": "https://img/1"}]}}]}


class Session:
    def get(self, url, **kwargs):
        return Response()


def test_live_dry_run_is_read_only_and_builds_preview():
    settings = WarLayoutSettings(
        ("alice",), "", socialdata_api_key="key", source="socialdata", socialdata_user_ids={"alice": "42"}
    )
    result = run_live_dry_run(settings, session=Session())
    assert result["posts"] == 1
    assert result["posts_with_images"] == 1
    assert result["layouts"] == 1
    assert result["article"]["cover_image_url"] == "https://img/1"
