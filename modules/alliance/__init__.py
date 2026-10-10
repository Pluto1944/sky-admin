"""联盟租户领域入口。"""

from .access import (
    AllianceClanAccess,
    AllianceContext,
    ensure_sky_admin_membership,
    list_alliance_contexts,
    resolve_alliance_context,
)

from .migration import (
    SKY_ALLIANCE_KEY,
    SKY_ALLIANCE_NAME,
    apply_sky_migration,
    build_existing_user_assignments,
    build_sky_manifest,
    preview_sky_migration,
)

__all__ = [
    "AllianceClanAccess",
    "AllianceContext",
    "SKY_ALLIANCE_KEY",
    "SKY_ALLIANCE_NAME",
    "apply_sky_migration",
    "build_existing_user_assignments",
    "build_sky_manifest",
    "ensure_sky_admin_membership",
    "list_alliance_contexts",
    "preview_sky_migration",
    "resolve_alliance_context",
]
