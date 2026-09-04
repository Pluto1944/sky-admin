import pytest

from .settings import WarLayoutSettings


def test_settings_parse_author_list(monkeypatch):
    monkeypatch.setenv("WAR_LAYOUT_X_AUTHORS", "@alice, bob")
    monkeypatch.setenv("X_BEARER_TOKEN", "token")
    monkeypatch.setenv("WAR_LAYOUT_SOURCE", "official")
    settings = WarLayoutSettings.from_env()
    assert settings.authors == ("alice", "bob")
    settings.validate_x()


def test_missing_token_is_rejected(monkeypatch):
    monkeypatch.setenv("WAR_LAYOUT_X_AUTHORS", "alice")
    monkeypatch.setenv("X_BEARER_TOKEN", "")
    monkeypatch.setenv("WAR_LAYOUT_SOURCE", "official")
    with pytest.raises(ValueError, match="X_BEARER_TOKEN"):
        WarLayoutSettings.from_env().validate_x()


def test_database_defaults_inside_ignored_runtime_dir(monkeypatch):
    monkeypatch.delenv("WAR_LAYOUT_DB_PATH", raising=False)
    settings = WarLayoutSettings.from_env()
    assert settings.db_path.parent.name == "runtime"
    assert settings.db_path.name == "war_layout.db"
