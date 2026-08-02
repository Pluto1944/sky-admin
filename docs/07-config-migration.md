# 07 — 配置集中化方案（Python → YAML）

> 配置迁移设计文档
> 版本：v1.0（2026-08）

---

## 一、背景与动机

### 1.1 现状

当前项目配置散落在 **4 个层级、8 个文件**：

| 层级 | 文件 | 行数 | 内容类型 |
|------|------|------|----------|
| 环境变量 | `.env` | ~25 | 敏感凭证（API Token、Doc ID、Client Secret） |
| 环境变量模板 | `.env.example` | ~22 | .env 模板 |
| 共享常量 | `shared/config/common.py` | 47 | 账号类型/状态常量、DB 路径、IO 开关 |
| 环境加载 | `shared/config/env_loader.py` | 40 | .env → os.environ 加载逻辑 |
| 玩家模块 | `modules/player/config.py` | 38 | 导出列映射、排序、sheet 名 |
| 同步模块 | `modules/coc_sync/config.py` | 49 | 部落列表、同步策略 + 工具函数 |
| 报名模块 | `modules/cwl_registration/config.py` | 204 | 排序权重、列映射、队伍定义、升降级、管理员等 |
| 战绩模块 | `modules/war_result/config.py` | 19 | 战绩列映射 |
| 测试 | `pytest.ini` | 8 | pytest 运行参数 |

### 1.2 痛点

1. **查找困难**：修改一个队伍配置要翻到 `modules/cwl_registration/config.py` 第 100 行，新人不知道在哪
2. **格式不统一**：有的用全大写常量，有的用函数，有的用字典
3. **`shared/config/` 名不副实**：名为"共享配置"，实际只有 47 行常量 + env loader
4. **敏感信息裸露**：`.env` 文件中的 Token 是明文 JWT
5. **配置与逻辑耦合**：`coc_sync/config.py` 中有 `alliance_clan_tags()` 函数，本质是常量派生，不应放在配置文件
6. **不利于未来 Web 后台**：Python 文件配置无法被前端读写

### 1.3 目标

为后续改造为 **后端服务 + 前端管理后台** 做准备，前端可以直接读写 YAML 配置，实现"管理后台改配置、服务端即时生效"。

---

## 二、目标架构

```
sky-admin/
├── .env                          # 不变：敏感凭证（Token、Doc ID、Client Secret）
├── .env.example                  # 不变：模板
├── pytest.ini                    # 不变：pytest 标准位置
│
├── config/
│   ├── __init__.py               # 统一入口：加载 settings.yaml → 模块级变量
│   ├── settings.yaml             # ★ 新建：全部非敏感业务配置
│   └── loader.py                 # YAML 加载 + 可选校验逻辑
│
├── shared/config/
│   └── env_loader.py             # 保留：.env 加载逻辑
│
├── modules/
│   ├── player/                   # 删除 config.py
│   ├── coc_sync/                 # 删除 config.py
│   ├── cwl_registration/         # 删除 config.py
│   └── war_result/               # 删除 config.py
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **单点存放** | 所有业务配置统一在 `config/settings.yaml`，一处修改全局生效 |
| **敏感分离** | `.env` 放凭证，`settings.yaml` 放非敏感业务配置 |
| **Python 兼容层** | `config/__init__.py` 将 YAML 展平为模块级变量，保持 `from config import XXX` 风格 |
| **向后兼容** | 无过渡期，直接切换到新路径 |
| **零运行时变化** | 只改变配置的存储格式和 import 路径，不改变任何运行时行为 |
| **未来扩展** | YAML 天然支持前端读写，后续接 Web 后台零成本 |

---

## 三、`config/settings.yaml` 完整结构

```yaml
# ============================================================================
# 应用全局配置（原 shared/config/common.py）
# ============================================================================
app:
  io_adapter: tencent              # local | tencent
  db_path: data/league.db

# ============================================================================
# 账号体系常量（原 shared/config/common.py）
# ============================================================================
account:
  type:
    combat: combat
    normal: normal
  status:
    active: active
    missed: missed
    maybe_left: maybe_left
    left: left
  membership:
    member: member
    left: left

league:
  type:
    combat: combat
    shell: shell

# ============================================================================
# 玩家模块 - player（原 modules/player/config.py）
# ============================================================================
player:
  maybe_left_months: 2

  export:
    columns:
      player_tag: 玩家Tag
      account_name: 游戏昵称
      player_name: 归属人
      town_hall_level: 大本
      exp_level: 等级
      trophies: 奖杯
      league_name: 段位
      clan_tag: 部落Tag
      clan_role: 部落职位
      membership_status: 部落身份
      status: 报名状态
      history_score: 历史分
      last_reg_period: 最后报名
      last_synced_at: 最后同步
      updated_at: 更新时间
    default_sort: history_score
    default_desc: true
    sheet_name: 玩家档案

# ============================================================================
# 部落同步 - coc_sync（原 modules/coc_sync/config.py）
# ============================================================================
coc_sync:
  clans:
    - tag: "#2QQ"
      name: "云深不知处 战营"
      enabled: true
    - tag: "#LQR"
      name: "秋雨不问梧桐意"
      enabled: true
    - tag: "#U2L"
      name: "仙境"
      enabled: true
    - tag: "#2COUL898"
      name: "Avalon"
      enabled: true
    - tag: "#YCOC"
      name: "Minecraft(互刷一营)"
      enabled: true
    - tag: "#9V9"
      name: "清风追明月(互刷二营)"
      enabled: true
    - tag: "#U2UL"
      name: "白马啸西风(互刷三营)"
      enabled: true
    - tag: "#R88U8"
      name: "苍穹(互刷四营)"
      enabled: true
    - tag: "#2LRQ88JQR"
      name: "新手村(互刷五营)"
      enabled: true
    - tag: "#U89"
      name: "执手听风吟(互刷六营)"
      enabled: true
    - tag: "#2JU"
      name: "清夜坠玄天(互刷七营)"
      enabled: true
    - tag: "#L0YLR02L"
      name: "冰风谷wy(互刷八营)"
      enabled: true
    # - tag: "#YYYYY"
    #   name: "苍穹三部"
    #   enabled: false

  dup_across_clans: warn          # warn | silent
  fail_fast: false

# ============================================================================
# 联赛报名 - cwl_registration（原 modules/cwl_registration/config.py）
# ============================================================================
cwl_registration:
  sort_weights:
    match_value: 0.6
    history_score: 0.4

  combat_min_match_value: 600

  registration_column_keywords:
    player_name:
      include: [主号游戏昵称, 主号]
      exclude: []
    account_name:
      include: [游戏昵称]
      exclude: [主号]
    match_value:
      include: [匹配值]
      exclude: []
    join_combat:
      include: [想实战]
      exclude: []
    submit_time:
      include: [提交时间]
      exclude: []
    willing_to_manage:
      include: [愿意做联赛管理员]
      exclude: []

  registration_tag_source: account_name
  registration_dedup: latest_submit

  join_combat_true_texts: [是, yes, y, true, "1", 参加]

  camp_clan_tag: "#2QQ"
  excluded_camp_names:
    - Pluto2QQ
    - 落花归尘
    - misael
    - AltriaPendragon
    - 葉丶
    - 飞的煎饼
    - 幻想鄉
    - "Timo⚡️Z⚔️ephyr™"

  # 已弃用（兼容历史）
  camp_sheet_name: 战营名单
  camp_column_keywords:
    account_name:
      include: [游戏昵称]
      exclude: [主号]
    player_tag:
      include: [玩家tag, tag]
      exclude: []
    camp_group:
      include: [战营]
      exclude: [是否]
    match_value:
      include: [匹配值]
      exclude: []

  arrangement_output_headers:
    - rank_order
    - league_type
    - cur_team
    - prev_team
    - movement
    - player_tag
    - account_name
    - player_name
    - team_name
    - account_type
    - trophies
    - match_value
    - history_score

  # 队伍定义
  teams:
    # === 实战队伍 ===
    - name: 泰坦二
      clan_tag: "#2QQ"
      leader: leader2QQ
      member_count: 15
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    - name: 冠一 一队
      clan_tag: "#2GGGGGGG"
      leader: leader5
      member_count: 15
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    - name: 冠二
      clan_tag: "#2C822CJJC"
      leader: "Pluto leader6"
      member_count: 15
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    - name: 冠三
      clan_tag: "#2QQQQ2G"
      leader: leader4
      member_count: 15
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    - name: 大一
      clan_tag: "#UUP2"
      leader: leader
      member_count: 15
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    - name: 大一
      clan_tag: "#CYYL"
      leader: leader2
      member_count: 30
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    - name: 大一
      clan_tag: "#2CU9JPYU8"
      leader: "南门 "
      member_count: 30
      league_level: ""
      manager: ""
      category: combat
      reserved_slots: 0
    # === 壳子队伍 ===
    - name: 大一
      clan_tag: "#2R9Y209LY"
      leader: leader10
      member_count: 30
      league_level: ""
      manager: ""
      category: shell
      reserved_slots: 0
    - name: 大三
      clan_tag: "#2JQR89P9G"
      leader: leader6
      member_count: 30
      league_level: ""
      manager: ""
      category: shell
      reserved_slots: 0
    - name: 水一
      clan_tag: "#2JUJRYVQP"
      leader: 登悟
      member_count: 30
      league_level: ""
      manager: ""
      category: shell
      reserved_slots: 0
    - name: 水二
      clan_tag: "#2GR0LPGVQ"
      leader: leader8
      member_count: 30
      league_level: ""
      manager: ""
      category: shell
      reserved_slots: 0

  team_output_headers:
    - rank_order
    - account_name
    - player_name
    - match_value
    - league_type
    - trophies
    - history_score

  # 升降级配置
  promotion_relegation:
    count: 2
    promotion_min_stars: 21
    relegation_max_stars: 18

  # 备选管理员（顺序即优先级）
  manager_candidates:
    - 鸟不拉不拉
    - ELIKI
    - Sunken ship
    - TT
    - 星空之翼
    - QAQ
    - "星空:宗主"
    - "Ghost✨Almighty"
    - 小小龙
    - 帝都
    - 武瞾
    - 武曌
    - Always
    - always
    - ghost
    - yolo
    - "Always#3"
    - 沉舟大大1号
    - 爱吃贝果小太阳
    - Snzed
    - 于我
    - 如梦
    - 故浅
    - 芝士芒果龙利鱼
    - 苏瞬卿
    - "虚伪、"

  # 黑白名单
  black_list: []
  white_list:
    - ["10°C✨Godwin 2", "#2QQ"]

  new_combat_insert_start: 30
  new_normal_insert_start: 45    # 已废弃

# ============================================================================
# 战绩模块 - war_result（原 modules/war_result/config.py）
# ============================================================================
war_result:
  column_keywords:
    account_name:
      include: [游戏昵称, 账号名]
      exclude: [主号]
    player_tag:
      include: [玩家tag, tag]
      exclude: []
    league_type:
      include: [联赛类型, 联赛]
      exclude: []

  tag_source: account_name
```

---

## 四、`config/__init__.py` 设计

统一入口，加载 YAML 并展平为模块级变量，保持现有 `from config import XXX` 使用风格不变：

```python
"""统一配置入口。加载 settings.yaml，展平为模块级变量。"""
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
```

### 关键设计决策

1. **`ALLIANCE_CLAN_TAGS` 改为常量**：原 `alliance_clan_tags()` 函数只是 `[c["tag"] for c in CLANS]` 一行逻辑，CLANS 是只读常量，派生值在模块加载时计算一次即可，不需要函数封装
2. **`JOIN_COMBAT_TRUE_TEXTS` / `EXCLUDED_CAMP_NAMES` 转为 set**：原 Python 文件中是 set，YAML 存为 list，在 `__init__.py` 中转换为 set
3. **`BLACK_LIST` 转为 set**：同上

---

## 五、`config/loader.py` 设计（可选）

提供 YAML 加载和基础校验能力，为未来热重载预留接口：

```python
"""YAML 配置加载与校验。"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml


class ConfigLoadError(Exception):
    """配置加载失败。"""


def load_settings(path: str | Path) -> dict[str, Any]:
    """加载并校验 settings.yaml。

    Raises:
        ConfigLoadError: 文件不存在或 YAML 格式错误
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigLoadError(f"配置文件不存在: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"YAML 解析失败: {e}") from e

    if not isinstance(cfg, dict):
        raise ConfigLoadError("配置文件顶层必须是字典")

    # 可选：校验必要字段
    _validate(cfg)

    return cfg


def _validate(cfg: dict) -> None:
    """校验必要字段存在性。可按需扩展。"""
    required_sections = ["app", "account", "league", "coc_sync", "cwl_registration"]
    for section in required_sections:
        if section not in cfg:
            raise ConfigLoadError(f"缺少配置节: {section}")

    # 校验队伍 category 值合法
    for team in cfg.get("cwl_registration", {}).get("teams", []):
        cat = team.get("category")
        if cat not in ("combat", "shell"):
            raise ConfigLoadError(f"队伍 {team.get('name')} 的 category 值非法: {cat}")
```

---

## 六、Import 路径变更对照表

### 6.1 删除的文件

| 文件 | 说明 |
|------|------|
| `shared/config/common.py` | 常量全部迁入 `settings.yaml` |
| `modules/player/config.py` | 迁入 `settings.yaml` |
| `modules/coc_sync/config.py` | 迁入 `settings.yaml`，`alliance_clan_tags()` 改为常量 |
| `modules/cwl_registration/config.py` | 迁入 `settings.yaml` |
| `modules/war_result/config.py` | 迁入 `settings.yaml` |

### 6.2 Import 变更（共 17 处）

| # | 文件 | 原 import | 新 import |
|---|------|-----------|-----------|
| 1 | `cli.py` | `from modules.cwl_registration.config import COMBAT_MIN_MATCH_VALUE, TEAMS` | `from config import COMBAT_MIN_MATCH_VALUE, TEAMS` |
| 2 | `cli.py` | `from shared.config import common as config` | `import config` |
| 3 | `modules/player/status_rule.py` | `from modules.player.config import MAYBE_LEFT_MONTHS` | `from config import MAYBE_LEFT_MONTHS` |
| 4 | `modules/player/status_rule.py` | `from shared.config.common import (...)` | `from config import (...)` |
| 5 | `modules/player/service.py` | `from modules.player.config import MAYBE_LEFT_MONTHS` | `from config import MAYBE_LEFT_MONTHS` |
| 6 | `modules/player/service.py` | `from shared.config.common import MEMBERSHIP_LEFT, MEMBERSHIP_MEMBER` | `from config import MEMBERSHIP_LEFT, MEMBERSHIP_MEMBER` |
| 7 | `modules/player/exporter.py` | `from modules.player.config import (...)` | `from config import (...)` |
| 8 | `modules/coc_sync/service.py` | `from modules.coc_sync import config as coc_config` | `from config import CLANS, DUP_ACROSS_CLANS, FAIL_FAST, ALLIANCE_CLAN_TAGS` |
| 9 | `modules/coc_sync/mapper.py` | `from shared.config.common import MEMBERSHIP_MEMBER` | `from config import MEMBERSHIP_MEMBER` |
| 10 | `modules/cwl_registration/roster.py` | `from modules.cwl_registration.config import (...)` | `from config import (...)` |
| 11 | `modules/cwl_registration/roster.py` | `from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import LEAGUE_COMBAT, LEAGUE_SHELL` |
| 12 | `modules/cwl_registration/importer.py` | `from modules.cwl_registration.config import (...)` | `from config import (...)` |
| 13 | `modules/cwl_registration/importer.py` | `from shared.config.common import ACCOUNT_TYPE_COMBAT, ACCOUNT_TYPE_NORMAL` | `from config import ACCOUNT_TYPE_COMBAT, ACCOUNT_TYPE_NORMAL` |
| 14 | `modules/cwl_registration/sorter.py` | `from modules.cwl_registration.config import SORT_WEIGHTS` | `from config import SORT_WEIGHTS` |
| 15 | `modules/cwl_registration/sorter.py` | `from shared.config.common import (...)` | `from config import (...)` |
| 16 | `modules/cwl_registration/rank_score.py` | `from modules.cwl_registration.config import SORT_WEIGHTS` | `from config import SORT_WEIGHTS` |
| 17 | `modules/cwl_registration/baseline_rebuilder.py` | `from modules.cwl_registration.config import (...)` | `from config import (...)` |
| 18 | `modules/cwl_registration/baseline_rebuilder.py` | `from shared.config.common import ACCOUNT_TYPE_COMBAT, LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import ACCOUNT_TYPE_COMBAT, LEAGUE_COMBAT, LEAGUE_SHELL` |
| 19 | `modules/cwl_registration/team_filler.py` | `from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import LEAGUE_COMBAT, LEAGUE_SHELL` |
| 20 | `modules/cwl_registration/team_filler.py` | `from shared.config.common import ACCOUNT_TYPE_COMBAT` (函数内) | `from config import ACCOUNT_TYPE_COMBAT` |
| 21 | `modules/war_result/importer.py` | `from modules.war_result.config import RESULT_COLUMN_KEYWORDS, RESULT_TAG_SOURCE` | `from config import RESULT_COLUMN_KEYWORDS, RESULT_TAG_SOURCE` |
| 22 | `scripts/backfill_team_names.py` | `from shared.config.common import DB_PATH` | `from config import DB_PATH` |
| 23 | `scripts/fetch_cwl_data.py` | `from shared.config.common import DB_PATH, LEAGUE_COMBAT` | `from config import DB_PATH, LEAGUE_COMBAT` |
| 24 | `scripts/migrate_results_202607.py` | `from shared.config.common import DB_PATH, LEAGUE_COMBAT` | `from config import DB_PATH, LEAGUE_COMBAT` |
| 25 | `scripts/dump_clans_to_xlsx.py` | `from modules.coc_sync import config as coc_config` | `from config import CLANS as coc_config_CLANS` (或改为直接用 `CLANS`) |

### 6.3 测试文件 Import 变更（共 9 处）

| # | 文件 | 原 import | 新 import |
|---|------|-----------|-----------|
| 26 | `tests/player/test_exporter.py` | `from modules.player.config import PLAYER_EXPORT_COLUMNS, PLAYER_EXPORT_SHEET` | `from config import PLAYER_EXPORT_COLUMNS, PLAYER_EXPORT_SHEET` |
| 27 | `tests/player/test_exporter.py` | `from shared.config.common import MEMBERSHIP_LEFT, MEMBERSHIP_MEMBER` | `from config import MEMBERSHIP_LEFT, MEMBERSHIP_MEMBER` |
| 28 | `tests/player/test_status_rule.py` | `from shared.config.common import STATUS_ACTIVE, STATUS_MAYBE_LEFT, STATUS_MISSED` | `from config import STATUS_ACTIVE, STATUS_MAYBE_LEFT, STATUS_MISSED` |
| 29 | `tests/coc_sync/test_service.py` | `from modules.coc_sync import config as coc_config` | `import config as coc_config` (或直接引用) |
| 30 | `tests/cwl_registration/test_roster.py` | `from modules.cwl_registration.config import ARRANGEMENT_OUTPUT_HEADERS, TEAMS` | `from config import ARRANGEMENT_OUTPUT_HEADERS, TEAMS` |
| 31 | `tests/cwl_registration/test_roster.py` | `from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import LEAGUE_COMBAT, LEAGUE_SHELL` |
| 32 | `tests/cwl_registration/test_importer.py` | `from modules.cwl_registration.config import CAMP_CLAN_TAG` | `from config import CAMP_CLAN_TAG` |
| 33 | `tests/cwl_registration/test_importer.py` | `from shared.config.common import (...)` | `from config import (...)` |
| 34 | `tests/cwl_registration/test_promotion.py` | `from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import LEAGUE_COMBAT, LEAGUE_SHELL` |
| 35 | `tests/cwl_registration/test_sorter.py` | `from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import LEAGUE_COMBAT, LEAGUE_SHELL` |
| 36 | `tests/cwl_registration/test_team_filler.py` | `from shared.config.common import LEAGUE_COMBAT, LEAGUE_SHELL` | `from config import LEAGUE_COMBAT, LEAGUE_SHELL` |

---

## 七、迁移步骤

### 阶段 1：加依赖

在 `requirements.txt` 添加：

```
pyyaml>=6.0
```

### 阶段 2：创建新文件

```
config/
├── __init__.py       # 统一入口（如上设计）
├── settings.yaml     # 全部业务配置（如上设计）
└── loader.py         # 加载 + 校验（可选）
```

### 阶段 3：更新 import 引用

按 6.2 和 6.3 的对照表，批量替换 36 处 import。

**`cli.py` 中 `config.IO_ADAPTER` 用法注意**：原 `from shared.config import common as config` 改为 `import config` 后，`config.IO_ADAPTER` 用法不变，因为新的 `config` 包（`config/__init__.py`）同样暴露了 `IO_ADAPTER`。

### 阶段 4：删除旧文件

- `shared/config/common.py`
- `modules/player/config.py`
- `modules/coc_sync/config.py`
- `modules/cwl_registration/config.py`
- `modules/war_result/config.py`

### 阶段 5：验证

```bash
# 1. 运行全量测试
pytest

# 2. 运行 CLI 冒烟测试
python cli.py --help

# 3. 检查是否有遗漏引用
grep -r "from modules.*config import\|from shared.config.common import" --include="*.py" .
```

---

## 八、`alliance_clan_tags` 处理说明

原 `modules/coc_sync/config.py` 中的 `alliance_clan_tags()` 函数：

```python
def alliance_clan_tags() -> list[str]:
    return [c["tag"] for c in CLANS]
```

**迁移方案**：在 `config/__init__.py` 中改为常量：

```python
CLANS: list[dict] = _cfg["coc_sync"]["clans"]
ALLIANCE_CLAN_TAGS: list[str] = [c["tag"] for c in CLANS]
```

**理由**：
- `CLANS` 是 YAML 中的只读数据，模块加载后不会变
- 派生值 `ALLIANCE_CLAN_TAGS` 只需计算一次
- 调用方从 `coc_config.alliance_clan_tags()` 改为 `ALLIANCE_CLAN_TAGS`，更简洁

---

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| import 路径遗漏 | 运行时 ImportError | 先建新文件、再改引用、最后删旧；全量跑测试 |
| YAML 解析错误 | 启动失败 | `loader.py` 加校验；CI 中加配置合法性检查 |
| `pytest.ini` 需同步 | 测试运行失败 | 测试文件 import 路径一并更新（已在对照表中） |
| `config` 包与 `config` 变量名冲突 | `cli.py` 中 `import config` 与原有 `config.IO_ADAPTER` 用法 | 新的 `config` 是包（`config/__init__.py`），`config.IO_ADAPTER` 访问方式不变，无冲突 |
| Git 冲突 | 多人协作冲突 | 在 feat 分支操作，合并 main 后推进 |

---

## 十、未来扩展路径

有了 YAML 配置后，后续接 Web 管理后台的路径清晰：

```
现在:   settings.yaml → config/__init__.py → 代码
                    ↓
Phase1: Web 后台 ←→ settings.yaml ←→ config/__init__.py → 代码
                    ↓
Phase2: Web 后台 ←→ 数据库 ←→ config/__init__.py → 代码
```

管理后台直接读写 `settings.yaml`，服务端通过 `loader.py` 提供热重载能力。

### 热重载预留设计

```python
# config/loader.py
import threading

_settings_cache: dict | None = None
_cache_lock = threading.Lock()

def reload_settings() -> dict:
    """热重载配置（可由信号/API 触发）。"""
    global _settings_cache
    with _cache_lock:
        _settings_cache = load_settings("config/settings.yaml")
    return _settings_cache
```

当前版本不需要热重载（配置只在启动时加载一次），接口已预留。

---

## 十一、相关文档

- `01-architecture.md` — 系统架构（需同步更新文件结构章节）
- `06-operations.md` — 运维脚本
