"""M6-M9 alliance sharing, manual operations and platform administration API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modules.alliance.operations import (
    AllianceOperationError,
    add_alliance_member_by_openid,
    add_managed_clan,
    archive_suspended_alliance,
    create_platform_alliance,
    create_share_link,
    delete_browsing_history,
    grant_alliance_plan,
    join_from_share,
    list_join_requests,
    leave_alliance,
    list_managed_clans,
    list_alliance_members,
    list_share_links,
    manual_set_clan_verification,
    platform_admin_capability,
    platform_add_alliance_member,
    platform_alliance_detail,
    platform_rename_alliance,
    platform_dashboard,
    platform_remove_alliance_member,
    platform_set_alliance_member_role,
    record_share_visit,
    remove_alliance_member,
    remove_managed_clan,
    reorder_managed_clans,
    revoke_share_link,
    set_alliance_member_role,
    set_alliance_status,
    share_preview,
    request_alliance_join,
    review_join_request,
    update_platform_settings,
    update_managed_clan,
    verification_entry,
)
from modules.alliance.free_alliance import (
    FreeAllianceError,
    enqueue_initialization,
    reconcile_sync_targets,
    request_manual_refresh,
    subscription_status,
)
from shared.db.connection import Database

from .auth import require_user
from .deps import get_db


router = APIRouter(prefix="/api")


class ShareCreateInput(BaseModel):
    expires_days: int = Field(default=30, ge=1, le=30)
    share_type: str = "invite"


class ShareTokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class MemberRoleInput(BaseModel):
    role: str


class MemberCreateInput(BaseModel):
    openid: str = Field(min_length=1, max_length=200)
    role: str = "member"


class JoinRequestReviewInput(BaseModel):
    action: str


class PlatformSettingsInput(BaseModel):
    free_registration_enabled: bool
    free_registration_limit: int = Field(ge=0, le=10000)


class PlatformAllianceCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=30)


class PlatformAllianceUpdateInput(BaseModel):
    name: str = Field(min_length=1, max_length=30)


class VerificationInput(BaseModel):
    clan_tag: str
    status: str
    note: str = Field(default="", max_length=500)


class PlanGrantInput(BaseModel):
    plan_code: str
    expires_at: str | None = None
    note: str = Field(default="", max_length=500)


class AllianceStatusInput(BaseModel):
    status: str
    note: str = Field(default="", max_length=500)


class ManagedClanInput(BaseModel):
    clan_tag: str
    category: str
    clan_name: str = Field(default="", max_length=40)


class ManagedClanUpdateInput(BaseModel):
    category: str
    clan_name: str | None = Field(default=None, max_length=40)


class ManagedClanOrderInput(BaseModel):
    clan_tags: list[str]


class ManagedClanRefreshInput(BaseModel):
    resource_types: list[str] = Field(default_factory=lambda: ["current_war"])


def _error(exc: AllianceOperationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/alliance-shares/preview")
def preview_alliance_share(payload: ShareTokenInput, db: Database = Depends(get_db)):
    """Public metadata only; resolving a token never creates membership or sync work."""
    try:
        return share_preview(db.conn, payload.token)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliance-shares/open")
def open_alliance_share(
    payload: ShareTokenInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    """已登录用户打开分享只记录浏览，不自动入盟。"""
    try:
        return record_share_visit(db.conn, user["openid"], payload.token)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliance-shares/join")
def join_alliance_share(
    payload: ShareTokenInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return join_from_share(db.conn, user["openid"], payload.token)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.get("/alliances/{alliance_id}/verification")
def alliance_verification_entry(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return verification_entry(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.get("/alliances/{alliance_id}/managed-clans")
def alliance_managed_clans(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        result = list_managed_clans(db.conn, user["openid"], alliance_id)
        if result["plan_code"] == "free":
            for clan in result["clans"]:
                if clan["status"] == "active":
                    clan["sync"] = subscription_status(
                        db.conn, alliance_id, clan["clan_tag"],
                    )
        result["manual_refresh_available"] = bool(
            result["plan_code"] == "free" and result["can_manage"]
        )
        return result
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliances/{alliance_id}/managed-clans", status_code=201)
def create_alliance_managed_clan(
    alliance_id: int,
    payload: ManagedClanInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        clan = add_managed_clan(
            db.conn, user["openid"], alliance_id, clan_tag=payload.clan_tag,
            category=payload.category, clan_name=payload.clan_name,
        )
        actor = db.conn.execute(
            "SELECT id FROM wechat_users WHERE openid=?", (user["openid"],),
        ).fetchone()
        initialization = enqueue_initialization(
            db.conn, alliance_id=alliance_id, clan_tag=clan["clan_tag"],
            actor_user_id=int(actor["id"]),
        )
        return {"clan": clan, "initialization": initialization}
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.put("/alliances/{alliance_id}/managed-clans/order")
def reorder_alliance_managed_clans(
    alliance_id: int,
    payload: ManagedClanOrderInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return reorder_managed_clans(
            db.conn, user["openid"], alliance_id, payload.clan_tags,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.patch("/alliances/{alliance_id}/managed-clans/{clan_tag}")
def update_alliance_managed_clan(
    alliance_id: int,
    clan_tag: str,
    payload: ManagedClanUpdateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        clan = update_managed_clan(
            db.conn, user["openid"], alliance_id, clan_tag,
            category=payload.category, clan_name=payload.clan_name,
        )
        reconcile_sync_targets(db.conn)
        return clan
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/alliances/{alliance_id}/managed-clans/{clan_tag}")
def delete_alliance_managed_clan(
    alliance_id: int,
    clan_tag: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        result = remove_managed_clan(db.conn, user["openid"], alliance_id, clan_tag)
        reconcile_sync_targets(db.conn)
        return result
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post(
    "/alliances/{alliance_id}/managed-clans/{clan_tag}/refresh",
    status_code=202,
)
def refresh_alliance_managed_clan(
    alliance_id: int,
    clan_tag: str,
    payload: ManagedClanRefreshInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        management = list_managed_clans(db.conn, user["openid"], alliance_id)
        if not management["can_manage"]:
            raise AllianceOperationError("只有联盟管理员或首领可以刷新部落", status_code=403)
        if management["plan_code"] != "free":
            raise AllianceOperationError("当前套餐使用自动刷新，无需手动提交", status_code=409)
        results = request_manual_refresh(
            db.conn, user["openid"], alliance_id, clan_tag,
            resource_types=payload.resource_types,
        )
        return {
            "alliance_id": int(alliance_id),
            "clan_tag": clan_tag,
            "results": results,
            "sync": subscription_status(db.conn, alliance_id, clan_tag),
        }
    except (AllianceOperationError, FreeAllianceError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/alliances/{alliance_id}/shares")
def alliance_shares(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return {"links": list_share_links(db.conn, user["openid"], alliance_id)}
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliances/{alliance_id}/shares", status_code=201)
def create_alliance_share(
    alliance_id: int,
    payload: ShareCreateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return create_share_link(
            db.conn, user["openid"], alliance_id,
            share_type=payload.share_type, expires_days=payload.expires_days,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/alliances/{alliance_id}/shares/{link_id}")
def delete_alliance_share(
    alliance_id: int,
    link_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        revoke_share_link(db.conn, user["openid"], alliance_id, link_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc
    return {"success": True, "link_id": link_id}


@router.get("/alliances/{alliance_id}/user-members")
def alliance_user_members(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return list_alliance_members(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliances/{alliance_id}/user-members", status_code=201)
def create_alliance_user_member(
    alliance_id: int,
    payload: MemberCreateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return add_alliance_member_by_openid(
            db.conn, user["openid"], alliance_id, payload.openid, payload.role,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliances/{alliance_id}/join-requests", status_code=201)
def create_alliance_join_request(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return request_alliance_join(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.get("/alliances/{alliance_id}/join-requests")
def alliance_join_requests(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return list_join_requests(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.patch("/alliances/{alliance_id}/join-requests/{request_id}")
def update_alliance_join_request(
    alliance_id: int,
    request_id: int,
    payload: JoinRequestReviewInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return review_join_request(
            db.conn, user["openid"], alliance_id, request_id, payload.action,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/me/alliance-history/{alliance_id}")
def delete_alliance_history(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return delete_browsing_history(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/alliances/{alliance_id}/leave")
def leave_current_alliance(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return leave_alliance(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.patch("/alliances/{alliance_id}/user-members/{member_id}")
def update_alliance_user_member(
    alliance_id: int,
    member_id: int,
    payload: MemberRoleInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return set_alliance_member_role(
            db.conn, user["openid"], alliance_id, member_id, payload.role,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/alliances/{alliance_id}/user-members/{member_id}")
def delete_alliance_user_member(
    alliance_id: int,
    member_id: int,
    block: bool = Query(default=False),
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return remove_alliance_member(
            db.conn, user["openid"], alliance_id, member_id, block=block,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.get("/platform/capability")
def platform_capability(
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    return platform_admin_capability(db.conn, user["openid"])


@router.get("/platform/alliances")
def platform_alliances(
    search: str = "",
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return platform_dashboard(db.conn, user["openid"], search=search)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/platform/alliances", status_code=201)
def platform_create_alliance_entry(
    payload: PlatformAllianceCreateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return create_platform_alliance(
            db.conn, user["openid"], payload.name,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.get("/platform/alliances/{alliance_id}")
def platform_alliance(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return platform_alliance_detail(db.conn, user["openid"], alliance_id)
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.patch("/platform/alliances/{alliance_id}")
def platform_update_alliance(
    alliance_id: int,
    payload: PlatformAllianceUpdateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return platform_rename_alliance(
            db.conn, user["openid"], alliance_id, payload.name,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/platform/alliances/{alliance_id}/members", status_code=201)
def platform_add_member(
    alliance_id: int,
    payload: MemberCreateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return platform_add_alliance_member(
            db.conn, user["openid"], alliance_id, payload.openid, payload.role,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.patch("/platform/alliances/{alliance_id}/members/{member_id}")
def platform_update_member_role(
    alliance_id: int,
    member_id: int,
    payload: MemberRoleInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return platform_set_alliance_member_role(
            db.conn, user["openid"], alliance_id, member_id, payload.role,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/platform/alliances/{alliance_id}/members/{member_id}")
def platform_delete_member(
    alliance_id: int,
    member_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return platform_remove_alliance_member(
            db.conn, user["openid"], alliance_id, member_id,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.get("/platform/alliances/{alliance_id}/managed-clans")
def platform_alliance_managed_clans(
    alliance_id: int,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return list_managed_clans(
            db.conn, user["openid"], alliance_id, platform=True,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.post("/platform/alliances/{alliance_id}/managed-clans", status_code=201)
def platform_create_alliance_managed_clan(
    alliance_id: int,
    payload: ManagedClanInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        clan = add_managed_clan(
            db.conn, user["openid"], alliance_id, clan_tag=payload.clan_tag,
            category=payload.category, clan_name=payload.clan_name, platform=True,
        )
        actor = db.conn.execute(
            "SELECT id FROM wechat_users WHERE openid=?", (user["openid"],),
        ).fetchone()
        initialization = enqueue_initialization(
            db.conn, alliance_id=alliance_id, clan_tag=clan["clan_tag"],
            actor_user_id=int(actor["id"]),
        )
        return {"clan": clan, "initialization": initialization}
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.put("/platform/alliances/{alliance_id}/managed-clans/order")
def platform_reorder_alliance_managed_clans(
    alliance_id: int,
    payload: ManagedClanOrderInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return reorder_managed_clans(
            db.conn, user["openid"], alliance_id, payload.clan_tags, platform=True,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.patch("/platform/alliances/{alliance_id}/managed-clans/{clan_tag}")
def platform_update_alliance_managed_clan(
    alliance_id: int,
    clan_tag: str,
    payload: ManagedClanUpdateInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        clan = update_managed_clan(
            db.conn, user["openid"], alliance_id, clan_tag,
            category=payload.category, clan_name=payload.clan_name, platform=True,
        )
        reconcile_sync_targets(db.conn)
        return clan
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/platform/alliances/{alliance_id}/managed-clans/{clan_tag}")
def platform_delete_alliance_managed_clan(
    alliance_id: int,
    clan_tag: str,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        result = remove_managed_clan(
            db.conn, user["openid"], alliance_id, clan_tag, platform=True,
        )
        reconcile_sync_targets(db.conn)
        return result
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.put("/platform/settings/free-registration")
def platform_free_registration(
    payload: PlatformSettingsInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return update_platform_settings(
            db.conn, user["openid"],
            free_registration_enabled=payload.free_registration_enabled,
            free_registration_limit=payload.free_registration_limit,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.put("/platform/alliances/{alliance_id}/verification")
def platform_verification(
    alliance_id: int,
    payload: VerificationInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return manual_set_clan_verification(
            db.conn, user["openid"], alliance_id, payload.clan_tag,
            payload.status, note=payload.note,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.put("/platform/alliances/{alliance_id}/plan")
def platform_plan(
    alliance_id: int,
    payload: PlanGrantInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return grant_alliance_plan(
            db.conn, user["openid"], alliance_id,
            plan_code=payload.plan_code, expires_at=payload.expires_at,
            note=payload.note,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.put("/platform/alliances/{alliance_id}/status")
def platform_status(
    alliance_id: int,
    payload: AllianceStatusInput,
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        return set_alliance_status(
            db.conn, user["openid"], alliance_id, payload.status, note=payload.note,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc


@router.delete("/platform/alliances/{alliance_id}")
def platform_delete_alliance(
    alliance_id: int,
    confirmation_name: str = "",
    user: dict = Depends(require_user),
    db: Database = Depends(get_db),
):
    try:
        result = archive_suspended_alliance(
            db.conn, user["openid"], alliance_id, confirmation_name,
        )
    except AllianceOperationError as exc:
        raise _error(exc) from exc
    try:
        reconcile_sync_targets(db.conn)
        result["sync_reconcile"] = "complete"
    except Exception:  # noqa: BLE001 - archive is committed; planner will converge later
        result["sync_reconcile"] = "pending"
    return result
