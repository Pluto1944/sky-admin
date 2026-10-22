from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api_server.auth import create_token, decode_token
from api_server.farm_system_auth import create_farm_token, require_farm_account
from api_server.farm_system_routes import (
    change_password,
    dashboard,
    login,
    me,
    require_farm_registration_enabled,
    require_farm_system_enabled,
)
from modules.farm_system.repository import FarmAccountRepository
from modules.farm_system.service import FarmAuthService


def _enable(monkeypatch):
    monkeypatch.setenv("FARM_SYSTEM_ENABLED", "true")
    monkeypatch.setenv("FARM_JWT_SECRET", "farm-test-secret-that-is-long-enough")
    monkeypatch.setenv("JWT_SECRET", "wechat-test-secret-that-is-long-enough")


def _create_account(db, **overrides):
    values = {
        "username": "farm.member@example.com",
        "display_name": "测试部落联盟",
        "password": "strong-password",
        "role": "member",
    }
    values.update(overrides)
    return FarmAuthService(FarmAccountRepository(db.conn)).create_account(**values)


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_feature_flag_hides_login(monkeypatch):
    monkeypatch.delenv("FARM_SYSTEM_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_farm_system_enabled()
    assert exc.value.status_code == 404


def test_registration_has_a_separate_feature_flag(monkeypatch):
    monkeypatch.delenv("FARM_SYSTEM_REGISTRATION_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_farm_registration_enabled()
    assert exc.value.status_code == 404

    monkeypatch.setenv("FARM_SYSTEM_REGISTRATION_ENABLED", "true")
    require_farm_registration_enabled()


def test_dashboard_exposes_registration_capability(db, monkeypatch):
    account = dict(_create_account(db))
    monkeypatch.delenv("FARM_SYSTEM_REGISTRATION_ENABLED", raising=False)
    assert dashboard(account, db)["registration_enabled"] is False

    monkeypatch.setenv("FARM_SYSTEM_REGISTRATION_ENABLED", "true")
    assert dashboard(account, db)["registration_enabled"] is True


def test_login_and_me_use_independent_token(db, monkeypatch):
    _enable(monkeypatch)
    _create_account(db)

    body = login({"username": "FARM.MEMBER@EXAMPLE.COM", "password": "strong-password"}, db)
    assert body["account"]["display_name"] == "测试部落联盟"
    assert "password_hash" not in body["account"]

    account = require_farm_account(_credentials(body["token"]), db)
    assert me(account)["username"] == "farm.member@example.com"
    assert db.conn.execute(
        "SELECT outcome FROM farm_auth_events ORDER BY id DESC LIMIT 1"
    ).fetchone()[0] == "success"


def test_gray_allowlist_is_enforced_on_login_and_existing_tokens(db, monkeypatch):
    _enable(monkeypatch)
    account = _create_account(db)
    monkeypatch.setenv("FARM_SYSTEM_ALLOWED_ACCOUNT_IDS", str(account["id"] + 1))

    with pytest.raises(HTTPException) as login_error:
        login({"username": "farm.member@example.com", "password": "strong-password"}, db)
    assert login_error.value.status_code == 403
    assert db.conn.execute(
        "SELECT outcome FROM farm_auth_events ORDER BY id DESC LIMIT 1"
    ).fetchone()[0] == "not_allowed"

    token = create_farm_token(account)
    with pytest.raises(HTTPException) as token_error:
        require_farm_account(_credentials(token), db)
    assert token_error.value.status_code == 403


def test_wechat_token_cannot_access_farm_me(db, monkeypatch):
    _enable(monkeypatch)
    _create_account(db)
    with pytest.raises(HTTPException) as exc:
        require_farm_account(_credentials(create_token("openid-1")), db)
    assert exc.value.status_code == 401


def test_farm_token_cannot_access_wechat_auth(db, monkeypatch):
    _enable(monkeypatch)
    account = _create_account(db)
    with pytest.raises(HTTPException) as exc:
        decode_token(create_farm_token(account))
    assert exc.value.status_code == 401


def test_password_change_invalidates_old_token(db, monkeypatch):
    _enable(monkeypatch)
    _create_account(db)
    logged_in = login({"username": "farm.member@example.com", "password": "strong-password"}, db)
    old_token = logged_in["token"]
    account = require_farm_account(_credentials(old_token), db)

    changed = change_password(
        {"current_password": "strong-password", "new_password": "new-strong-password"},
        account,
        db,
    )
    with pytest.raises(HTTPException) as exc:
        require_farm_account(_credentials(old_token), db)
    assert exc.value.status_code == 401
    assert require_farm_account(_credentials(changed["token"]), db)["id"] == account["id"]


def test_disabled_account_is_rejected(db, monkeypatch):
    _enable(monkeypatch)
    account = _create_account(db)
    db.conn.execute(
        "UPDATE farm_auth_accounts SET status = 'disabled' WHERE id = ?",
        (account["id"],),
    )
    db.conn.commit()
    with pytest.raises(HTTPException) as exc:
        login({"username": "farm.member@example.com", "password": "strong-password"}, db)
    assert exc.value.status_code == 403
