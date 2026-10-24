"""互刷独立账号仓储。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from shared.db.connection import now_iso

from .security import normalize_username
from .tags import coc_tag_key


class FarmAccountRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_by_id(self, account_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM farm_auth_accounts WHERE id = ?",
            (int(account_id),),
        ).fetchone()

    def get_by_username(self, username: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM farm_auth_accounts WHERE username = ?",
            (normalize_username(username),),
        ).fetchone()

    def list_accounts(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM farm_auth_accounts ORDER BY id"
        ).fetchall()

    def create_account(
        self,
        *,
        username: str,
        display_name: str,
        password_hash: str,
        role: str = "member",
        actor_account_id: int | None = None,
    ) -> sqlite3.Row:
        normalized = normalize_username(username)
        display = str(display_name or "").strip()
        if not display or len(display) > 80:
            raise ValueError("账号显示名称不能为空且不能超过 80 个字符")
        if role not in {"creator", "admin", "member"}:
            raise ValueError("无效的互刷账号角色")
        now = now_iso()
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO farm_auth_accounts
                   (username, display_name, password_hash, role, status,
                    token_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', 1, ?, ?)""",
                (normalized, display, password_hash, role, now, now),
            )
            account_id = int(cursor.lastrowid)
            self._audit(
                actor_account_id=actor_account_id,
                action="account.created",
                entity_type="farm_account",
                entity_id=str(account_id),
                after={"username": normalized, "display_name": display, "role": role, "status": "active"},
                created_at=now,
            )
        row = self.get_by_id(account_id)
        if row is None:  # pragma: no cover - SQLite insert invariant
            raise RuntimeError("互刷账号创建后无法读取")
        return row

    def mark_login(self, account_id: int) -> sqlite3.Row:
        now = now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE farm_auth_accounts SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now, now, int(account_id)),
            )
        row = self.get_by_id(account_id)
        if row is None:
            raise LookupError("互刷账号不存在")
        return row

    def change_password(
        self,
        account_id: int,
        password_hash: str,
        *,
        actor_account_id: int | None = None,
    ) -> sqlite3.Row:
        row = self.get_by_id(account_id)
        if row is None:
            raise LookupError("互刷账号不存在")
        now = now_iso()
        next_version = int(row["token_version"]) + 1
        with self.conn:
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET password_hash = ?, token_version = ?, updated_at = ?
                   WHERE id = ?""",
                (password_hash, next_version, now, int(account_id)),
            )
            self._audit(
                actor_account_id=actor_account_id or int(account_id),
                action="account.password_changed",
                entity_type="farm_account",
                entity_id=str(account_id),
                before={"token_version": int(row["token_version"])},
                after={"token_version": next_version},
                created_at=now,
            )
        updated = self.get_by_id(account_id)
        if updated is None:  # pragma: no cover
            raise RuntimeError("互刷账号更新后无法读取")
        return updated

    def reset_password(
        self,
        account_id: int,
        password_hash: str,
        *,
        actor_account_id: int | None = None,
    ) -> sqlite3.Row:
        """管理员重置密码并使该账号的全部旧令牌失效。"""
        row = self.get_by_id(account_id)
        if row is None:
            raise LookupError("互刷账号不存在")
        now = now_iso()
        next_version = int(row["token_version"]) + 1
        with self.conn:
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET password_hash = ?, token_version = ?, updated_at = ?
                   WHERE id = ?""",
                (password_hash, next_version, now, int(account_id)),
            )
            self._audit(
                actor_account_id=actor_account_id,
                action="account.password_reset",
                entity_type="farm_account",
                entity_id=str(account_id),
                before={"token_version": int(row["token_version"])},
                after={"token_version": next_version},
                created_at=now,
            )
        updated = self.get_by_id(account_id)
        if updated is None:  # pragma: no cover
            raise RuntimeError("互刷账号更新后无法读取")
        return updated

    def set_status(
        self,
        account_id: int,
        status: str,
        *,
        actor_account_id: int | None = None,
    ) -> sqlite3.Row:
        """启用或停用账号；状态变化总是使旧令牌失效。"""
        if status not in {"active", "disabled"}:
            raise ValueError("无效的互刷账号状态")
        row = self.get_by_id(account_id)
        if row is None:
            raise LookupError("互刷账号不存在")
        if row["status"] == status:
            return row
        now = now_iso()
        next_version = int(row["token_version"]) + 1
        with self.conn:
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET status = ?, token_version = ?, updated_at = ?
                   WHERE id = ?""",
                (status, next_version, now, int(account_id)),
            )
            self._audit(
                actor_account_id=actor_account_id,
                action="account.status_changed",
                entity_type="farm_account",
                entity_id=str(account_id),
                before={"status": row["status"], "token_version": int(row["token_version"])},
                after={"status": status, "token_version": next_version},
                created_at=now,
            )
        updated = self.get_by_id(account_id)
        if updated is None:  # pragma: no cover
            raise RuntimeError("互刷账号更新后无法读取")
        return updated

    def update_account(
        self,
        account_id: int,
        *,
        display_name: str | None = None,
        role: str | None = None,
        status: str | None = None,
        actor_account_id: int | None = None,
    ) -> sqlite3.Row:
        row = self.get_by_id(account_id)
        if row is None:
            raise LookupError("互刷账号不存在")
        next_display = row["display_name"] if display_name is None else str(display_name).strip()
        next_role = row["role"] if role is None else role
        next_status = row["status"] if status is None else status
        if not next_display or len(next_display) > 80:
            raise ValueError("账号显示名称不能为空且不能超过 80 个字符")
        if next_role not in {"creator", "admin", "member"}:
            raise ValueError("无效的互刷账号角色")
        if next_status not in {"active", "disabled"}:
            raise ValueError("无效的互刷账号状态")
        changed_identity = next_role != row["role"] or next_status != row["status"]
        next_version = int(row["token_version"]) + (1 if changed_identity else 0)
        if (
            next_display == row["display_name"]
            and next_role == row["role"]
            and next_status == row["status"]
        ):
            return row
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET display_name = ?, role = ?, status = ?, token_version = ?, updated_at = ?
                   WHERE id = ?""",
                (next_display, next_role, next_status, next_version, now, int(account_id)),
            )
            self._audit(
                actor_account_id=actor_account_id,
                action="account.updated",
                entity_type="farm_account",
                entity_id=str(account_id),
                before={
                    "display_name": row["display_name"], "role": row["role"],
                    "status": row["status"], "token_version": int(row["token_version"]),
                },
                after={
                    "display_name": next_display, "role": next_role,
                    "status": next_status, "token_version": next_version,
                },
                created_at=now,
            )
        updated = self.get_by_id(account_id)
        if updated is None:  # pragma: no cover
            raise RuntimeError("互刷账号更新后无法读取")
        return updated

    def transfer_creator(self, from_account_id: int, to_account_id: int) -> tuple[sqlite3.Row, sqlite3.Row]:
        """原子转移唯一创建者；受控运维脚本专用。"""
        source = self.get_by_id(from_account_id)
        target = self.get_by_id(to_account_id)
        if source is None or target is None:
            raise LookupError("创建者转移账号不存在")
        if int(source["id"]) == int(target["id"]):
            raise ValueError("新旧创建者不能是同一账号")
        if source["role"] != "creator" or source["status"] != "active":
            raise ValueError("原账号不是有效创建者")
        if target["status"] != "active":
            raise ValueError("新创建者账号必须处于启用状态")
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET role = 'admin', token_version = token_version + 1, updated_at = ?
                   WHERE id = ?""",
                (now, int(source["id"])),
            )
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET role = 'creator', token_version = token_version + 1, updated_at = ?
                   WHERE id = ?""",
                (now, int(target["id"])),
            )
            self._audit(
                actor_account_id=int(source["id"]),
                action="creator.transferred",
                entity_type="farm_account",
                entity_id=str(target["id"]),
                before={"creator_account_id": int(source["id"])},
                after={"creator_account_id": int(target["id"])},
                created_at=now,
            )
        old_creator = self.get_by_id(int(source["id"]))
        new_creator = self.get_by_id(int(target["id"]))
        if old_creator is None or new_creator is None:  # pragma: no cover
            raise RuntimeError("创建者转移后无法读取账号")
        return old_creator, new_creator

    def initialize_creator(self, account_id: int) -> sqlite3.Row:
        """Promote one active account when no active creator exists."""
        target = self.get_by_id(account_id)
        if target is None:
            raise LookupError("创建者账号不存在")
        if target["status"] != "active":
            raise ValueError("创建者账号必须处于启用状态")
        current = self.conn.execute(
            """SELECT id FROM farm_auth_accounts
               WHERE role='creator' AND status='active' LIMIT 1"""
        ).fetchone()
        if current is not None:
            if int(current["id"]) == int(target["id"]):
                return target
            raise ValueError("已经存在有效创建者，请使用创建者转移命令")
        now = now_iso()
        next_version = int(target["token_version"]) + 1
        with self.conn:
            self.conn.execute(
                """UPDATE farm_auth_accounts
                   SET role='creator', token_version=?, updated_at=? WHERE id=?""",
                (next_version, now, int(target["id"])),
            )
            self._audit(
                actor_account_id=int(target["id"]),
                action="creator.initialized",
                entity_type="farm_account",
                entity_id=str(target["id"]),
                before={"role": target["role"], "token_version": int(target["token_version"])},
                after={"role": "creator", "token_version": next_version},
                created_at=now,
            )
        result = self.get_by_id(int(target["id"]))
        if result is None:  # pragma: no cover
            raise RuntimeError("创建者初始化后无法读取账号")
        return result

    def _audit(
        self,
        *,
        actor_account_id: int | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO farm_audit_logs
               (actor_account_id, action, entity_type, entity_id,
                before_json, after_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                actor_account_id,
                action,
                entity_type,
                entity_id,
                json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
                created_at or now_iso(),
            ),
        )


class FarmClanRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_by_id(self, clan_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM farm_clans WHERE id = ?", (int(clan_id),)
        ).fetchone()

    def get_by_tag(self, clan_tag: str) -> sqlite3.Row | None:
        key = coc_tag_key(clan_tag)
        if key is None:
            return None
        return self.conn.execute(
            "SELECT * FROM farm_clans WHERE clan_tag_key = ?", (key,)
        ).fetchone()

    def list_clans(self, account_id: int | None = None) -> list[sqlite3.Row]:
        if account_id is None:
            return self.conn.execute(
                """SELECT * FROM farm_clans
                   ORDER BY COALESCE(enabled_at, created_at) DESC, id DESC"""
            ).fetchall()
        return self.conn.execute(
            """SELECT * FROM farm_clans WHERE account_id = ?
               ORDER BY COALESCE(enabled_at, created_at) DESC, id DESC""",
            (int(account_id),),
        ).fetchall()

    def create_clan(
        self,
        *,
        clan_tag: str,
        clan_name: str,
        account_id: int,
        actor_account_id: int,
    ) -> sqlite3.Row:
        key = coc_tag_key(clan_tag)
        name = str(clan_name or "").strip()
        if not key or not name:
            raise ValueError("部落标签和名称不能为空")
        now = now_iso()
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO farm_clans
                   (clan_tag, clan_tag_key, clan_name, account_id, status, score,
                    enabled_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', 0, ?, ?, ?)""",
                (key, key, name, int(account_id), now, now, now),
            )
            clan_id = int(cursor.lastrowid)
            self._audit(
                actor_account_id, "clan.created", clan_id, None,
                {"clan_tag": key, "clan_name": name, "account_id": int(account_id),
                 "status": "active", "score": 0}, now,
            )
        row = self.get_by_id(clan_id)
        if row is None:  # pragma: no cover
            raise RuntimeError("互刷部落创建后无法读取")
        return row

    def update_clan(
        self,
        clan_tag: str,
        *,
        clan_name: str | None = None,
        status: str | None = None,
        actor_account_id: int,
    ) -> sqlite3.Row:
        row = self.get_by_tag(clan_tag)
        if row is None:
            raise LookupError("互刷部落不存在")
        next_name = row["clan_name"] if clan_name is None else str(clan_name).strip()
        next_status = row["status"] if status is None else status
        if not next_name:
            raise ValueError("部落名称不能为空")
        if next_status not in {"active", "disabled"}:
            raise ValueError("无效的互刷部落状态")
        if next_name == row["clan_name"] and next_status == row["status"]:
            return row
        now = now_iso()
        next_enabled_at = (
            now
            if row["status"] != "active" and next_status == "active"
            else row["enabled_at"]
        )
        with self.conn:
            self.conn.execute(
                """UPDATE farm_clans
                   SET clan_name = ?, status = ?, enabled_at = ?, updated_at = ?
                   WHERE id = ?""",
                (next_name, next_status, next_enabled_at, now, int(row["id"])),
            )
            self._audit(
                actor_account_id, "clan.updated", int(row["id"]),
                {"clan_name": row["clan_name"], "status": row["status"],
                 "enabled_at": row["enabled_at"]},
                {"clan_name": next_name, "status": next_status,
                 "enabled_at": next_enabled_at}, now,
            )
        return self.get_by_id(int(row["id"]))

    def transfer(
        self,
        clan_tag: str,
        *,
        account_id: int,
        actor_account_id: int,
    ) -> sqlite3.Row:
        row = self.get_by_tag(clan_tag)
        if row is None:
            raise LookupError("互刷部落不存在")
        if int(row["account_id"]) == int(account_id):
            return row
        now = now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE farm_clans SET account_id = ?, updated_at = ? WHERE id = ?",
                (int(account_id), now, int(row["id"])),
            )
            self._audit(
                actor_account_id, "clan.transferred", int(row["id"]),
                {"account_id": int(row["account_id"]), "score": int(row["score"])},
                {"account_id": int(account_id), "score": int(row["score"])}, now,
            )
        return self.get_by_id(int(row["id"]))

    def _audit(
        self,
        actor_account_id: int,
        action: str,
        clan_id: int,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        created_at: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO farm_audit_logs
               (actor_account_id, action, entity_type, entity_id,
                before_json, after_json, created_at)
               VALUES (?, ?, 'farm_clan', ?, ?, ?, ?)""",
            (
                int(actor_account_id), action, str(clan_id),
                json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
                created_at,
            ),
        )
