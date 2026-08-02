"""统一配置入口。加载 settings.yaml，展平为模块级变量，保持兼容现有 import 路径。"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml


_SETTINGS_PATH = Path(__file__).parent / "settings.yaml"

with open(_SETTINGS_PATH, encoding="utf-8") as _f:
    _cfg: dict[str, Any] = yaml.safe_load(_f)


# ============================================================================
# 应用全局（原 shared/config/common.py）
# ============================================================================
IO_ADAPTER: str = _cfg["app"]["io_adapter"]
DB_PATH: str = _cfg["app"]["db_path"]

# ============================================================================
# 账号体系常量（原 shared/config/common.py）
# ============================================================================
ACCOUNT_TYPE_COMBAT: str = _cfg["account"]["type"]["combat"]
ACCOUNT_TYPE_NORMAL: str = _cfg["account"]["type"]["normal"]
STATUS_ACTIVE: str = _cfg["account"]["status"]["active"]
STATUS_MISSED: str = _cfg["account"]["status"]["missed"]
STATUS_MAYBE_LEFT: str = _cfg["account"]["status"]["maybe_left"]
STATUS_LEFT: str = _cfg["account"]["status"]["left"]
MEMBERSHIP_MEMBER: str = _cfg["account"]["membership"]["member"]
MEMBERSHIP_LEFT: str = _cfg["account"]["membership"]["left"]
LEAGUE_COMBAT: str = _cfg["league"]["type"]["combat"]
LEAGUE_SHELL: str = _cfg["league"]["type"]["shell"]

# ============================================================================
# 玩家模块（原 modules/player/config.py）
# ============================================================================
MAYBE_LEFT_MONTHS: int = _cfg["player"]["maybe_left_months"]
PLAYER_EXPORT_COLUMNS: dict = _cfg["player"]["export"]["columns"]
PLAYER_EXPORT_DEFAULT_SORT: str = _cfg["player"]["export"]["default_sort"]
PLAYER_EXPORT_DEFAULT_DESC: bool = _cfg["player"]["export"]["default_desc"]
PLAYER_EXPORT_SHEET: str = _cfg["player"]["export"]["sheet_name"]

# ============================================================================
# 部落同步（原 modules/coc_sync/config.py）
# ============================================================================
CLANS: list[dict] = _cfg["coc_sync"]["clans"]
ALLIANCE_CLAN_TAGS: list[str] = [c["tag"] for c in CLANS]
DUP_ACROSS_CLANS: str = _cfg["coc_sync"]["dup_across_clans"]
FAIL_FAST: bool = _cfg["coc_sync"]["fail_fast"]

# ============================================================================
# 联赛报名（原 modules/cwl_registration/config.py）
# ============================================================================
_cwl = _cfg["cwl_registration"]
SORT_WEIGHTS: dict = _cwl["sort_weights"]
COMBAT_MIN_MATCH_VALUE: int = _cwl["combat_min_match_value"]
REGISTRATION_COLUMN_KEYWORDS: dict = _cwl["registration_column_keywords"]
REGISTRATION_TAG_SOURCE: str = _cwl["registration_tag_source"]
REGISTRATION_DEDUP: str = _cwl["registration_dedup"]
JOIN_COMBAT_TRUE_TEXTS: set = set(_cwl["join_combat_true_texts"])
CAMP_CLAN_TAG: str = _cwl["camp_clan_tag"]
EXCLUDED_CAMP_NAMES: set = set(_cwl["excluded_camp_names"])
CAMP_SHEET_NAME: str = _cwl["camp_sheet_name"]
CAMP_COLUMN_KEYWORDS: dict = _cwl["camp_column_keywords"]
ARRANGEMENT_OUTPUT_HEADERS: list = _cwl["arrangement_output_headers"]
TEAMS: list[dict] = _cwl["teams"]
TEAM_OUTPUT_HEADERS: list = _cwl["team_output_headers"]
PROMOTION_RELEGATION_CONFIG: dict = _cwl["promotion_relegation"]
MANAGER_CANDIDATES: list = _cwl["manager_candidates"]
BLACK_LIST: set = set(_cwl["black_list"])
WHITE_LIST: list = _cwl["white_list"]
NEW_COMBAT_INSERT_START: int = _cwl["new_combat_insert_start"]
NEW_NORMAL_INSERT_START: int = _cwl["new_normal_insert_start"]

# ============================================================================
# 战绩模块（原 modules/war_result/config.py）
# ============================================================================
RESULT_COLUMN_KEYWORDS: dict = _cfg["war_result"]["column_keywords"]
RESULT_TAG_SOURCE: str = _cfg["war_result"]["tag_source"]
