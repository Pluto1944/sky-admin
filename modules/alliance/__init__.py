"""联盟租户领域入口（M1 仅提供数据模型与迁移能力）。"""

from .migration import (
    SKY_ALLIANCE_KEY,
    SKY_ALLIANCE_NAME,
    apply_sky_migration,
    build_existing_user_assignments,
    build_sky_manifest,
    preview_sky_migration,
)

__all__ = [
    "SKY_ALLIANCE_KEY",
    "SKY_ALLIANCE_NAME",
    "apply_sky_migration",
    "build_existing_user_assignments",
    "build_sky_manifest",
    "preview_sky_migration",
]
