"""互刷联盟系统 API。"""
from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from modules.farm_system.management import (
    ClanProfileUnavailableError,
    FarmManagementService,
    FarmPermissionError,
)
from modules.farm_system.monitoring import FarmMonitoringService
from modules.farm_system.clan_sync import FarmClanSyncService
from modules.farm_system.operations import (
    CreatorPermissionError,
    FarmCreatorOperations,
)
from modules.farm_system.repository import FarmAccountRepository
from modules.farm_system.rate_limit import LoginFailureLimiter
from modules.farm_system.registration import FarmRegistrationService, RegistrationError
from modules.farm_system.rounds import FarmRoundService, public_round
from modules.farm_system.service import (
    DisabledAccountError,
    FarmAuthService,
    InvalidCredentialsError,
)
from shared.db.connection import Database, now_iso
from modules.coc_sync.official.api_client import CocApiClient

from .deps import get_db
from .farm_system_auth import (
    create_farm_token,
    ensure_farm_account_allowed,
    require_farm_account,
)


router = APIRouter(prefix="/api/farm-system", tags=["farm-system"])
login_failure_limiter = LoginFailureLimiter()


def _record_auth_event(db: Database, outcome: str, account_id: int | None = None) -> None:
    try:
        with db.conn:
            db.conn.execute(
                "INSERT INTO farm_auth_events (account_id, outcome, created_at) VALUES (?, ?, ?)",
                (account_id, outcome, now_iso()),
            )
    except sqlite3.Error:
        # 登录观测不能改变认证结果。
        pass


def _enabled() -> bool:
    return os.environ.get("FARM_SYSTEM_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def require_farm_system_enabled() -> None:
    if not _enabled():
        raise HTTPException(status_code=404, detail="互刷系统暂未开放")


def require_farm_registration_enabled() -> None:
    if not _registration_enabled():
        raise HTTPException(status_code=404, detail="互刷登记功能暂未开放")


def _registration_enabled() -> bool:
    return os.environ.get("FARM_SYSTEM_REGISTRATION_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def get_farm_coc_client() -> CocApiClient:
    return CocApiClient()


def _public_account(account) -> dict:
    return {
        "id": int(account["id"]),
        "username": account["username"],
        "display_name": account["display_name"],
        "role": account["role"],
        "status": account["status"],
        "last_login_at": account["last_login_at"],
    }


def _public_clan(clan) -> dict:
    return {
        "id": int(clan["id"]),
        "clan_tag": clan["clan_tag"],
        "clan_name": clan["clan_name"],
        "account_id": int(clan["account_id"]),
        "status": clan["status"],
        "score": int(clan["score"]),
        "enabled_at": clan["enabled_at"],
        "created_at": clan["created_at"],
        "updated_at": clan["updated_at"],
    }


def require_farm_manager(account: dict = Depends(require_farm_account)) -> dict:
    if account["role"] not in {"creator", "admin"}:
        raise HTTPException(status_code=403, detail="需要互刷系统管理员权限")
    return account


def require_farm_creator(account: dict = Depends(require_farm_account)) -> dict:
    if account["role"] != "creator":
        raise HTTPException(status_code=403, detail="仅互刷系统超级管理员可以执行该操作")
    return account


def _management_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FarmPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, sqlite3.IntegrityError):
        detail = "账号名或部落标签已存在"
        if "uq_farm_auth_active_creator" in str(exc):
            detail = "只能存在一个有效超级管理员账号"
        return HTTPException(status_code=409, detail=detail)
    if isinstance(exc, ClanProfileUnavailableError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/login", dependencies=[Depends(require_farm_system_enabled)])
def login(payload: dict, db: Database = Depends(get_db)):
    username = payload.get("username", "")
    if login_failure_limiter.is_limited(username):
        _record_auth_event(db, "rate_limited")
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")
    service = FarmAuthService(FarmAccountRepository(db.conn))
    try:
        account = service.authenticate(username, payload.get("password", ""))
    except InvalidCredentialsError as exc:
        login_failure_limiter.record_failure(username)
        _record_auth_event(db, "invalid")
        raise HTTPException(status_code=401, detail="账号或密码错误") from exc
    except DisabledAccountError as exc:
        login_failure_limiter.record_failure(username)
        _record_auth_event(db, "disabled")
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    login_failure_limiter.clear(username)
    try:
        ensure_farm_account_allowed(account)
    except HTTPException:
        _record_auth_event(db, "not_allowed", int(account["id"]))
        raise
    _record_auth_event(db, "success", int(account["id"]))
    return {"token": create_farm_token(account), "account": _public_account(account)}


@router.post("/auth/logout", dependencies=[Depends(require_farm_system_enabled)])
def logout(account: dict = Depends(require_farm_account)):
    # JWT 为无状态凭证；客户端删除 farm_token 即完成当前设备退出。
    return {"ok": True, "account_id": account["id"]}


@router.post("/auth/change-password", dependencies=[Depends(require_farm_system_enabled)])
def change_password(
    payload: dict,
    account: dict = Depends(require_farm_account),
    db: Database = Depends(get_db),
):
    current_password = payload.get("current_password", "")
    new_password = payload.get("new_password", "")
    service = FarmAuthService(FarmAccountRepository(db.conn))
    try:
        updated = service.change_password(account["id"], current_password, new_password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"token": create_farm_token(updated), "account": _public_account(updated)}


@router.get("/me", dependencies=[Depends(require_farm_system_enabled)])
def me(account: dict = Depends(require_farm_account)):
    return account


@router.get("/clans", dependencies=[Depends(require_farm_system_enabled)])
def own_clans(
    account: dict = Depends(require_farm_account),
    db: Database = Depends(get_db),
):
    rows = FarmManagementService(db.conn).list_own_clans(account)
    return {"clans": [_public_clan(row) for row in rows]}


@router.get("/admin/accounts", dependencies=[Depends(require_farm_system_enabled)])
def admin_accounts(
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    rows = FarmManagementService(db.conn).list_accounts(account)
    return {"accounts": [_public_account(row) for row in rows]}


@router.post("/admin/accounts", dependencies=[Depends(require_farm_system_enabled)])
def admin_create_account(
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        created = FarmManagementService(db.conn).create_account(account, payload)
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"account": _public_account(created)}


@router.patch("/admin/accounts/{account_id}", dependencies=[Depends(require_farm_system_enabled)])
def admin_update_account(
    account_id: int,
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        updated = FarmManagementService(db.conn).update_account(account, account_id, payload)
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"account": _public_account(updated)}


@router.get("/admin/clans", dependencies=[Depends(require_farm_system_enabled)])
def admin_clans(
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    rows = FarmManagementService(db.conn).list_clans(account)
    return {"clans": [_public_clan(row) for row in rows]}


@router.get(
    "/clans/{clan_tag}/detail",
    dependencies=[Depends(require_farm_system_enabled)],
)
def clan_detail(
    clan_tag: str,
    account: dict = Depends(require_farm_account),
    db: Database = Depends(get_db),
):
    try:
        result = FarmManagementService(db.conn).get_clan_detail(account, clan_tag)
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc
    return {
        "clan": _public_clan(result["clan"]),
        "profile": result["profile"],
        "profile_status": result["profile_status"],
        "profile_error": result["profile_error"],
        "profile_updated_at": result["profile_updated_at"],
        "profile_attempted_at": result["profile_attempted_at"],
        "current_war": result["current_war"],
        "current_war_source": result["current_war_source"],
        "current_war_updated_at": result["current_war_updated_at"],
        "current_war_error": result["current_war_error"],
        "farm_round": result["farm_round"],
        "farm_registration": result["farm_registration"],
        "opponent": result["opponent"],
    }


@router.post(
    "/clans/{clan_tag}/detail-refresh",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_farm_system_enabled)],
)
def request_clan_detail_refresh(
    clan_tag: str,
    account: dict = Depends(require_farm_account),
    db: Database = Depends(get_db),
):
    try:
        result = FarmClanSyncService(db.conn).request_detail_profiles(
            account, clan_tag
        )
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc
    return {"refresh": result}


@router.post("/admin/clans", dependencies=[Depends(require_farm_system_enabled)])
def admin_create_clan(
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        created = FarmManagementService(db.conn).create_clan(account, payload)
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"clan": _public_clan(created)}


@router.post(
    "/admin/clan-sync-requests",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_farm_system_enabled)],
)
def admin_request_clan_sync(
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        result = FarmClanSyncService(db.conn).request(
            account, payload.get("clan_tag", ""), payload.get("account_id")
        )
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"sync": result}


@router.get(
    "/admin/clan-sync-requests/{clan_tag}",
    dependencies=[Depends(require_farm_system_enabled)],
)
def admin_clan_sync_status(
    clan_tag: str,
    account_id: int,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        result = FarmClanSyncService(db.conn).status(account, clan_tag, account_id)
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc
    return {"sync": result}


@router.patch("/admin/clans/{clan_tag}", dependencies=[Depends(require_farm_system_enabled)])
def admin_update_clan(
    clan_tag: str,
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        updated = FarmManagementService(db.conn).update_clan(account, clan_tag, payload)
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"clan": _public_clan(updated)}


@router.post("/admin/clans/{clan_tag}/transfer", dependencies=[Depends(require_farm_system_enabled)])
def admin_transfer_clan(
    clan_tag: str,
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        updated = FarmManagementService(db.conn).transfer_clan(
            account, clan_tag, payload.get("account_id")
        )
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"clan": _public_clan(updated)}


@router.get("/dashboard", dependencies=[Depends(require_farm_system_enabled)])
def dashboard(
    account: dict = Depends(require_farm_account),
    db: Database = Depends(get_db),
):
    result = FarmRoundService(db.conn).dashboard(account)
    result["registration_enabled"] = _registration_enabled()
    return result


@router.get(
    "/creator/accounts/{account_id}/dashboard",
    dependencies=[Depends(require_farm_system_enabled)],
)
def creator_account_dashboard(
    account_id: int,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
):
    target = FarmAccountRepository(db.conn).get_by_id(account_id)
    if target is None:
        raise HTTPException(status_code=404, detail="互刷账号不存在")
    result = FarmRoundService(db.conn).dashboard({"id": int(target["id"])})
    result["registration_enabled"] = _registration_enabled()
    return result


@router.post("/admin/rounds", dependencies=[Depends(require_farm_system_enabled)])
def admin_create_round(
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        created = FarmRoundService(db.conn).create_round(account, payload)
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        if isinstance(exc, sqlite3.IntegrityError):
            raise HTTPException(status_code=409, detail="当前已有未结束的互刷场次") from exc
        raise _management_error(exc) from exc
    return {"round": public_round(created)}


@router.patch("/admin/rounds/{round_id}", dependencies=[Depends(require_farm_system_enabled)])
def admin_update_round(
    round_id: int,
    payload: dict,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        updated = FarmRoundService(db.conn).update_round(account, round_id, payload)
    except (ValueError, LookupError, FarmPermissionError, sqlite3.IntegrityError) as exc:
        raise _management_error(exc) from exc
    return {"round": public_round(updated)}


@router.get("/admin/rounds/{round_id}/results", dependencies=[Depends(require_farm_system_enabled)])
def admin_round_results(
    round_id: int,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        return FarmRoundService(db.conn).results(account, round_id)
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc


@router.get("/admin/monitor/overview", dependencies=[Depends(require_farm_system_enabled)])
def admin_monitor_overview(
    round_id: int | None = None,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        return FarmMonitoringService(db.conn).overview(account, round_id)
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc


@router.get("/admin/monitor/clans", dependencies=[Depends(require_farm_system_enabled)])
def admin_monitor_clans(
    round_id: int | None = None,
    status_filter: str = "attention",
    account_id: int | None = None,
    search: str = "",
    sort: str = "attention",
    page: int = 1,
    page_size: int = 30,
    account: dict = Depends(require_farm_manager),
    db: Database = Depends(get_db),
):
    try:
        return FarmMonitoringService(db.conn).list_clans(
            account,
            round_id=round_id,
            status_filter=status_filter,
            account_id=account_id,
            search=search,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc


@router.post("/creator/monitor/refresh", dependencies=[Depends(require_farm_system_enabled)])
def creator_refresh_monitor(
    round_id: int | None = None,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
):
    try:
        return FarmMonitoringService(db.conn).request_refresh(account, round_id)
    except (ValueError, LookupError, FarmPermissionError) as exc:
        raise _management_error(exc) from exc


@router.post(
    "/rounds/{round_id}/clans/{clan_tag}/register",
    dependencies=[
        Depends(require_farm_system_enabled),
        Depends(require_farm_registration_enabled),
    ],
)
def register_farm_clan(
    round_id: int,
    clan_tag: str,
    account: dict = Depends(require_farm_account),
    db: Database = Depends(get_db),
    coc_client: CocApiClient = Depends(get_farm_coc_client),
):
    try:
        return FarmRegistrationService(db.conn, coc_client).register(account, round_id, clan_tag)
    except RegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="登记结果发生并发冲突，请重试") from exc


@router.post(
    "/creator/accounts/{account_id}/rounds/{round_id}/clans/{clan_tag}/register",
    dependencies=[
        Depends(require_farm_system_enabled),
        Depends(require_farm_registration_enabled),
    ],
)
def creator_register_farm_clan(
    account_id: int,
    round_id: int,
    clan_tag: str,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
    coc_client: CocApiClient = Depends(get_farm_coc_client),
):
    try:
        return FarmRegistrationService(db.conn, coc_client).register_for_account(
            account, account_id, round_id, clan_tag
        )
    except RegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="登记结果发生并发冲突，请重试") from exc


@router.post("/creator/matches/{match_id}/revoke", dependencies=[Depends(require_farm_system_enabled)])
def creator_revoke_match(
    match_id: int,
    payload: dict,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
):
    try:
        return FarmCreatorOperations(db.conn).revoke_match(
            account, match_id, payload.get("reason", "")
        )
    except CreatorPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/creator/matches/{match_id}/reopen", dependencies=[Depends(require_farm_system_enabled)])
def creator_reopen_match(
    match_id: int,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
):
    try:
        return FarmCreatorOperations(db.conn).reopen_match(account, match_id)
    except CreatorPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/creator/rounds/{round_id}/cancel", dependencies=[Depends(require_farm_system_enabled)])
def creator_cancel_round(
    round_id: int,
    payload: dict,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
):
    try:
        return FarmCreatorOperations(db.conn).cancel_round(
            account, round_id, payload.get("reason", "")
        )
    except CreatorPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/creator/accounts/{account_id}/reset-password", dependencies=[Depends(require_farm_system_enabled)])
def creator_reset_password(
    account_id: int,
    payload: dict,
    account: dict = Depends(require_farm_creator),
    db: Database = Depends(get_db),
):
    try:
        updated = FarmAuthService(FarmAccountRepository(db.conn)).reset_password(
            account_id,
            payload.get("new_password", ""),
            actor_account_id=int(account["id"]),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"account": _public_account(updated)}
