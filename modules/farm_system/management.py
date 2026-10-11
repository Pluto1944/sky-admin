"""互刷账号与部落归属管理服务。"""
from __future__ import annotations

import json
import sqlite3

from .repository import FarmAccountRepository, FarmClanRepository
from .service import FarmAuthService
from .tags import coc_tag_key


class FarmPermissionError(PermissionError):
    pass


class ClanProfileUnavailableError(ValueError):
    pass


def _assert_manager(actor: dict) -> None:
    if actor.get("role") not in {"creator", "admin"}:
        raise FarmPermissionError("需要互刷系统管理员权限")


class FarmManagementService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.accounts = FarmAccountRepository(conn)
        self.clans = FarmClanRepository(conn)
        self.auth = FarmAuthService(self.accounts)

    def list_accounts(self, actor: dict) -> list[sqlite3.Row]:
        _assert_manager(actor)
        return self.accounts.list_accounts()

    def create_account(self, actor: dict, payload: dict) -> sqlite3.Row:
        _assert_manager(actor)
        role = payload.get("role") or "member"
        if role == "creator":
            raise FarmPermissionError("创建者账号只能通过受控运维入口初始化或转移")
        if actor["role"] != "creator" and role != "member":
            raise FarmPermissionError("只有创建者可以设置管理员或创建者角色")
        return self.auth.create_account(
            username=payload.get("username", ""),
            display_name=payload.get("display_name", ""),
            password=payload.get("password", ""),
            role=role,
            actor_account_id=int(actor["id"]),
        )

    def update_account(self, actor: dict, account_id: int, payload: dict) -> sqlite3.Row:
        _assert_manager(actor)
        target = self.accounts.get_by_id(account_id)
        if target is None:
            raise LookupError("互刷账号不存在")
        requested_role = payload.get("role")
        requested_status = payload.get("status")
        if target["role"] == "creator" and (
            (requested_role is not None and requested_role != "creator")
            or requested_status == "disabled"
        ):
            raise FarmPermissionError("创建者账号不能在页面中停用或降级")
        if actor["role"] != "creator":
            if target["role"] == "creator":
                raise FarmPermissionError("管理员不能修改创建者账号")
            if requested_role is not None and requested_role != target["role"]:
                raise FarmPermissionError("只有创建者可以修改账号角色")
        return self.accounts.update_account(
            account_id,
            display_name=payload.get("display_name"),
            role=requested_role,
            status=requested_status,
            actor_account_id=int(actor["id"]),
        )

    def list_clans(self, actor: dict) -> list[sqlite3.Row]:
        _assert_manager(actor)
        return self.clans.list_clans()

    def list_own_clans(self, actor: dict) -> list[sqlite3.Row]:
        return self.clans.list_clans(int(actor["id"]))

    def create_clan(self, actor: dict, payload: dict) -> sqlite3.Row:
        _assert_manager(actor)
        target = self._active_account(payload.get("account_id"))
        tag, name = self._cached_official_profile(payload.get("clan_tag"))
        return self.clans.create_clan(
            clan_tag=tag,
            clan_name=name,
            account_id=int(target["id"]),
            actor_account_id=int(actor["id"]),
        )

    def update_clan(self, actor: dict, clan_tag: str, payload: dict) -> sqlite3.Row:
        _assert_manager(actor)
        return self.clans.update_clan(
            clan_tag,
            clan_name=payload.get("clan_name"),
            status=payload.get("status"),
            actor_account_id=int(actor["id"]),
        )

    def transfer_clan(self, actor: dict, clan_tag: str, account_id: int) -> sqlite3.Row:
        _assert_manager(actor)
        target = self._active_account(account_id)
        return self.clans.transfer(
            clan_tag,
            account_id=int(target["id"]),
            actor_account_id=int(actor["id"]),
        )

    def _active_account(self, account_id) -> sqlite3.Row:
        try:
            row = self.accounts.get_by_id(int(account_id))
        except (TypeError, ValueError):
            row = None
        if row is None:
            raise LookupError("目标互刷账号不存在")
        if row["status"] != "active":
            raise ValueError("不能把部落分配给已停用账号")
        return row

    def _cached_official_profile(self, clan_tag) -> tuple[str, str]:
        key = coc_tag_key(clan_tag)
        if not key:
            raise ValueError("部落标签不能为空")
        rows = self.conn.execute(
            """SELECT clan_tag, clan_name, status, data_json
               FROM clan_profile_cache WHERE data_json IS NOT NULL"""
        ).fetchall()
        for row in rows:
            if coc_tag_key(row["clan_tag"]) != key:
                continue
            try:
                profile = json.loads(row["data_json"])
            except (TypeError, json.JSONDecodeError):
                profile = {}
            official_tag = coc_tag_key(profile.get("tag") or profile.get("clan_tag") or row["clan_tag"])
            official_name = str(profile.get("name") or row["clan_name"] or "").strip()
            if official_tag == key and official_name and row["status"] in {"success", "stale"}:
                return official_tag, official_name
        raise ClanProfileUnavailableError(
            "尚无该部落的官方资料缓存，请先由受控同步任务验证部落标签"
        )
