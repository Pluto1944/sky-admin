"""Live queue handlers that reuse the established business write paths."""
from __future__ import annotations

import config
from modules.coc_sync.official.mapper import normalize_tag
from shared.db.connection import Database


class SyncTaskExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _clan_context(resource_key: str) -> dict:
    tag = normalize_tag(resource_key)
    if not tag:
        raise SyncTaskExecutionError("同步任务缺少有效部落 Tag", retryable=False)
    db = Database(config.DB_PATH)
    db.init_schema()
    try:
        row = db.conn.execute(
            """SELECT clan_tag, clan_name, category
               FROM alliance_clans
               WHERE clan_tag = ? AND status = 'active'
               ORDER BY CASE category
                          WHEN 'combat' THEN 0 WHEN 'normal' THEN 1
                          WHEN 'farm' THEN 2 WHEN 'flat' THEN 3 ELSE 4 END,
                        sort_order, id
               LIMIT 1""",
            (tag,),
        ).fetchone()
    finally:
        db.close()
    if row:
        return {"tag": tag, "name": row["clan_name"], "category": row["category"]}
    configured = next(
        (item for item in config.CLANS if normalize_tag(item.get("tag")) == tag),
        None,
    )
    if configured:
        return {
            "tag": tag,
            "name": configured.get("name"),
            "category": configured.get("category", "normal"),
        }
    raise SyncTaskExecutionError("同步目标已不在有效联盟订阅中", retryable=False)


def _cwl_team(resource_key: str) -> tuple[str, dict]:
    period, separator, raw_tag = resource_key.partition(":")
    tag = normalize_tag(raw_tag)
    if not separator or not tag:
        raise SyncTaskExecutionError("CWL 任务资源键无效", retryable=False)
    from scripts.scheduler import _cwl_live_teams_for_period

    db = Database(config.DB_PATH)
    db.init_schema()
    try:
        team = next(
            (
                item for item in _cwl_live_teams_for_period(db, period)
                if normalize_tag(item.get("clan_tag")) == tag
            ),
            None,
        )
    finally:
        db.close()
    if team is None:
        raise SyncTaskExecutionError("CWL 月度队伍配置已失效", retryable=False)
    return period, team


def _raise_on_failure(result: dict) -> dict:
    if result.get("status") == "failed":
        reason = result.get("reason") or "同步处理失败"
        non_retryable = any(code in str(reason) for code in (" 400", " 401", " 403"))
        raise SyncTaskExecutionError(str(reason), retryable=not non_retryable)
    return result


def _refresh_subscription_names(clan_tag: str) -> None:
    """Replace the temporary Tag display name after profile initialization."""
    tag = normalize_tag(clan_tag)
    if not tag:
        return
    db = Database(config.DB_PATH)
    db.init_schema()
    try:
        profile = db.conn.execute(
            """SELECT clan_name, updated_at FROM clan_profile_cache
               WHERE clan_tag=? AND data_json IS NOT NULL""",
            (tag,),
        ).fetchone()
        if profile and profile["clan_name"]:
            with db.conn:
                db.conn.execute(
                    """UPDATE alliance_clans SET clan_name=?, updated_at=?
                       WHERE clan_tag=? AND status='active'
                         AND (clan_name IS NULL OR clan_name='' OR clan_name=clan_tag)""",
                    (profile["clan_name"], profile["updated_at"], tag),
                )
    finally:
        db.close()


def execute_resource_task(resource_type: str, resource_key: str) -> dict:
    """Execute exactly one globally deduplicated resource target."""
    from scripts.scheduler import _run_coc_sync, _run_current_wars, _run_cwl_live

    if resource_type == "clan_profile":
        clan = _clan_context(resource_key)
        result = _raise_on_failure(_run_coc_sync(
            clans=[clan], sync_members=False, sync_profiles=True,
        ))
        _refresh_subscription_names(resource_key)
        return result
    if resource_type == "clan_members":
        clan = _clan_context(resource_key)
        return _raise_on_failure(_run_coc_sync(
            clans=[clan], sync_members=True, sync_profiles=False,
        ))
    if resource_type == "current_war":
        return _raise_on_failure(_run_current_wars(
            force=True, clans=[_clan_context(resource_key)],
        ))
    if resource_type == "cwl_live":
        period, team = _cwl_team(resource_key)
        return _raise_on_failure(_run_cwl_live(
            # The queue wakes high-quality CWL targets every two minutes, but
            # the established per-group/per-war policy still decides whether
            # an external request is due.  Forcing here would refetch every
            # preparation war and defeat M4's pressure reduction.
            force=False, teams=[team], period_override=period,
        ))
    raise SyncTaskExecutionError(
        f"unsupported resource type: {resource_type}", retryable=False,
    )
