from __future__ import annotations

import sqlite3

import pytest

from modules.farm_system.repository import FarmAccountRepository
from modules.farm_system.service import FarmAuthService
from shared.db.connection import Database


def _service(db):
    return FarmAuthService(FarmAccountRepository(db.conn))


def test_farm_core_tables_are_created(db):
    tables = {
        row[0]
        for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"farm_auth_accounts", "farm_clans", "farm_audit_logs"} <= tables


def test_farm_core_schema_is_idempotent(db):
    db.init_schema()
    db.init_schema()
    assert db.conn.execute("SELECT COUNT(*) FROM farm_auth_accounts").fetchone()[0] == 0


def test_legacy_farm_clans_backfills_enabled_at(tmp_path):
    path = tmp_path / "legacy-farm.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE farm_clans (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               clan_tag TEXT NOT NULL,
               clan_tag_key TEXT NOT NULL UNIQUE,
               clan_name TEXT NOT NULL,
               account_id INTEGER NOT NULL,
               status TEXT NOT NULL DEFAULT 'active',
               score INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           );
           INSERT INTO farm_clans
               (clan_tag, clan_tag_key, clan_name, account_id, status, score,
                created_at, updated_at)
           VALUES
               ('#2QQ', '#2QQ', '旧部落', 1, 'active', 0,
                '2026-10-01T00:00:00+00:00', '2026-10-20T00:00:00+00:00');"""
    )
    conn.close()

    database = Database(str(path))
    database.init_schema()
    database.init_schema()
    row = database.conn.execute(
        "SELECT enabled_at FROM farm_clans WHERE clan_tag='#2QQ'"
    ).fetchone()
    database.close()

    assert row["enabled_at"] == "2026-10-01T00:00:00+00:00"


def test_create_account_normalizes_username_and_writes_audit(db):
    account = _service(db).create_account(
        username=" Farm.Admin@Example.COM ",
        display_name="测试联盟",
        password="strong-password",
        role="creator",
    )

    assert account["username"] == "farm.admin@example.com"
    assert account["role"] == "creator"
    assert account["password_hash"] != "strong-password"
    audit = db.conn.execute("SELECT * FROM farm_audit_logs").fetchone()
    assert audit["action"] == "account.created"
    assert "password" not in (audit["after_json"] or "")


def test_only_one_active_creator_is_allowed(db):
    service = _service(db)
    service.create_account(
        username="creator.one@example.com",
        display_name="创建者一",
        password="strong-password",
        role="creator",
    )
    with pytest.raises(sqlite3.IntegrityError):
        service.create_account(
            username="creator.two@example.com",
            display_name="创建者二",
            password="strong-password",
            role="creator",
        )


def test_password_change_increments_token_version(db):
    service = _service(db)
    account = service.create_account(
        username="member.one@example.com",
        display_name="成员一",
        password="old-password",
    )
    updated = service.change_password(account["id"], "old-password", "new-password")

    assert updated["token_version"] == account["token_version"] + 1
    assert service.authenticate("member.one@example.com", "new-password")["id"] == account["id"]


def test_admin_reset_and_disable_invalidate_tokens_and_write_audit(db):
    service = _service(db)
    account = service.create_account(
        username="member.two@example.com",
        display_name="成员二",
        password="old-password",
    )
    reset = service.reset_password(account["id"], "reset-password")
    disabled = service.set_status(account["id"], "disabled")

    assert reset["token_version"] == account["token_version"] + 1
    assert disabled["token_version"] == reset["token_version"] + 1
    assert disabled["status"] == "disabled"
    actions = [
        row[0]
        for row in db.conn.execute(
            "SELECT action FROM farm_audit_logs ORDER BY id"
        ).fetchall()
    ]
    assert actions == [
        "account.created",
        "account.password_reset",
        "account.status_changed",
    ]


def test_creator_transfer_is_atomic_and_invalidates_both_tokens(db):
    service = _service(db)
    old = service.create_account(
        username="creator.one@example.com", display_name="创建者一",
        password="strong-password", role="creator",
    )
    new = service.create_account(
        username="admin.one@example.com", display_name="管理员一",
        password="strong-password", role="admin",
    )
    old_after, new_after = FarmAccountRepository(db.conn).transfer_creator(old["id"], new["id"])

    assert old_after["role"] == "admin"
    assert new_after["role"] == "creator"
    assert old_after["token_version"] == old["token_version"] + 1
    assert new_after["token_version"] == new["token_version"] + 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_auth_accounts WHERE role = 'creator' AND status = 'active'"
    ).fetchone()[0] == 1


def test_initialize_creator_requires_empty_creator_slot_and_invalidates_token(db):
    service = _service(db)
    target = service.create_account(
        username="admin.one@example.com", display_name="管理员一",
        password="strong-password", role="admin",
    )
    repository = FarmAccountRepository(db.conn)

    creator = repository.initialize_creator(target["id"])
    repeated = repository.initialize_creator(target["id"])

    assert creator["role"] == "creator"
    assert creator["token_version"] == target["token_version"] + 1
    assert repeated["token_version"] == creator["token_version"]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM farm_audit_logs WHERE action='creator.initialized'"
    ).fetchone()[0] == 1
