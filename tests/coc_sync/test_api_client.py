import json

from modules.coc_sync.official.api_client import CocApiClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _Opener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _Response({"items": [{"startTime": "20261002T070000.000Z"}]})


def test_capital_raid_request_uses_injected_direct_opener():
    opener = _Opener()
    client = CocApiClient(token="test-token", opener=opener)

    seasons = client.get_capital_raid_seasons("#ABC", limit=4)

    assert seasons[0]["startTime"] == "20261002T070000.000Z"
    request, timeout = opener.requests[0]
    assert request.full_url.endswith("/clans/%23ABC/capitalraidseasons?limit=4")
    assert request.headers["Authorization"] == "Bearer test-token"
    assert timeout == 15
