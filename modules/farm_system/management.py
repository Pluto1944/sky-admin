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

    def get_clan_detail(self, actor: dict, clan_tag: str) -> dict:
        clan = self.clans.get_by_tag(clan_tag)
        if clan is None:
            raise LookupError("互刷部落不存在")
        if (
            actor.get("role") not in {"creator", "admin"}
            and int(clan["account_id"]) != int(actor["id"])
        ):
            raise FarmPermissionError("只能查看当前账号绑定的互刷部落")
        key = coc_tag_key(clan["clan_tag"])
        rows = self.conn.execute(
            """SELECT clan_tag, status, data_json, error, updated_at, attempted_at
               FROM clan_profile_cache"""
        ).fetchall()
        profile_row = next(
            (row for row in rows if coc_tag_key(row["clan_tag"]) == key),
            None,
        )
        profile = None
        if profile_row is not None and profile_row["data_json"]:
            try:
                loaded = json.loads(profile_row["data_json"])
                profile = loaded if isinstance(loaded, dict) else None
            except (TypeError, json.JSONDecodeError):
                profile = None
        current_war_row = next(
            (
                row for row in self.conn.execute(
                    """SELECT clan_tag, status, data_json, error, updated_at, attempted_at
                       FROM current_war_cache"""
                ).fetchall()
                if coc_tag_key(row["clan_tag"]) == key
            ),
            None,
        )
        current_war = self._json_object(
            current_war_row["data_json"] if current_war_row else None
        )
        if current_war is not None:
            current_war.pop("rows", None)

        # 与首页保持相同的“当前场次”口径：优先未结束场次，否则显示最近完成场次。
        from .rounds import FarmRoundService, public_round, public_round_clan

        round_row = FarmRoundService(self.conn).current_round()
        round_clan = None
        if round_row is not None:
            round_clan = self.conn.execute(
                """SELECT rc.*, c.score AS current_score
                   FROM farm_round_clans rc
                   JOIN farm_clans c ON c.id = rc.clan_id
                   WHERE rc.round_id = ? AND rc.clan_id = ?""",
                (int(round_row["id"]), int(clan["id"])),
            ).fetchone()

        # 动态添加的互刷部落可能尚未进入常规 current_war_cache；此时用本轮
        # 登记时保存的官方战争摘要补足“当前部落战”，仍然不在读接口调用 COC API。
        current_war_source = "current_war_cache" if current_war is not None else None
        current_war_updated_at = current_war_row["updated_at"] if current_war_row else None
        current_war_error = current_war_row["error"] if current_war_row else None
        if current_war is None and round_row is not None:
            attempt = self.conn.execute(
                """SELECT summary_json, error_message, created_at
                   FROM farm_registration_attempts
                   WHERE round_id = ? AND clan_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (int(round_row["id"]), int(clan["id"])),
            ).fetchone()
            current_war = self._json_object(attempt["summary_json"] if attempt else None)
            if current_war is not None:
                current_war_source = "registration_attempt"
                current_war_updated_at = attempt["created_at"]
                current_war_error = attempt["error_message"]

        farm_registration = public_round_clan(round_clan) if round_clan else None
        opponent_tag = None
        opponent_name = None
        opponent_source = None
        if farm_registration and farm_registration.get("opponent_tag"):
            opponent_tag = farm_registration["opponent_tag"]
            opponent_name = farm_registration.get("opponent_name")
            opponent_source = "farm_registration"

        opponent = None
        if opponent_tag:
            opponent_key = coc_tag_key(opponent_tag)
            opponent_profile_row = next(
                (row for row in rows if coc_tag_key(row["clan_tag"]) == opponent_key),
                None,
            )
            opponent_profile = self._json_object(
                opponent_profile_row["data_json"] if opponent_profile_row else None
            )
            opponent = {
                "clan_tag": opponent_tag,
                "clan_name": opponent_name,
                "source": opponent_source,
                "profile": opponent_profile,
                "profile_status": (
                    opponent_profile_row["status"] if opponent_profile_row else "pending"
                ),
                "profile_error": (
                    opponent_profile_row["error"] if opponent_profile_row else None
                ),
                "profile_updated_at": (
                    opponent_profile_row["updated_at"] if opponent_profile_row else None
                ),
            }

        return {
            "clan": clan,
            "profile": profile,
            "profile_status": profile_row["status"] if profile_row else "pending",
            "profile_error": profile_row["error"] if profile_row else None,
            "profile_updated_at": profile_row["updated_at"] if profile_row else None,
            "profile_attempted_at": profile_row["attempted_at"] if profile_row else None,
            "current_war": current_war,
            "current_war_source": current_war_source,
            "current_war_updated_at": current_war_updated_at,
            "current_war_error": current_war_error,
            "farm_round": public_round(round_row),
            "farm_registration": farm_registration,
            "opponent": opponent,
        }

    @staticmethod
    def _json_object(value) -> dict | None:
        if not value:
            return None
        try:
            loaded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
        return loaded if isinstance(loaded, dict) else None

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
