from . import test_x_live


def test_live_script_returns_success_for_mock(monkeypatch, capsys):
    class Page:
        posts = ()
        next_token = None

    monkeypatch.setattr(test_x_live, "load_env", lambda: None)
    monkeypatch.setattr(test_x_live.WarLayoutSettings, "from_env", classmethod(lambda cls: cls(("alice",), "token")))
    monkeypatch.setattr(test_x_live, "XHttpTransport", lambda _: type("T", (), {"__call__": lambda *_: Page()})())
    assert test_x_live.main() == 0
    assert "token" not in capsys.readouterr().out
