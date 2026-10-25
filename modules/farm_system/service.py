"""互刷账号认证服务。"""
from __future__ import annotations

from .repository import FarmAccountRepository
from .security import hash_password, normalize_username, verify_password


_DUMMY_PASSWORD_HASH = hash_password("farm-system-dummy-password")


class InvalidCredentialsError(ValueError):
    pass


class DisabledAccountError(PermissionError):
    pass


class FarmAuthService:
    def __init__(self, repository: FarmAccountRepository):
        self.repository = repository

    def authenticate(self, username: str, password: str):
        try:
            normalized = normalize_username(username)
        except ValueError as exc:
            raise InvalidCredentialsError("账号或密码错误") from exc
        row = self.repository.get_by_username(normalized)
        if row is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError("账号或密码错误")
        if not verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError("账号或密码错误")
        if row["status"] != "active":
            raise DisabledAccountError("账号已停用，请联系超级管理员")
        return self.repository.mark_login(int(row["id"]))

    def create_account(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str = "member",
        actor_account_id: int | None = None,
    ):
        return self.repository.create_account(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            role=role,
            actor_account_id=actor_account_id,
        )

    def change_password(self, account_id: int, current_password: str, new_password: str):
        row = self.repository.get_by_id(account_id)
        if row is None or not verify_password(current_password, row["password_hash"]):
            raise InvalidCredentialsError("当前密码错误")
        return self.repository.change_password(
            account_id,
            hash_password(new_password),
            actor_account_id=account_id,
        )

    def reset_password(
        self,
        account_id: int,
        new_password: str,
        *,
        actor_account_id: int | None = None,
    ):
        return self.repository.reset_password(
            account_id,
            hash_password(new_password),
            actor_account_id=actor_account_id,
        )

    def set_status(
        self,
        account_id: int,
        status: str,
        *,
        actor_account_id: int | None = None,
    ):
        return self.repository.set_status(
            account_id,
            status,
            actor_account_id=actor_account_id,
        )
