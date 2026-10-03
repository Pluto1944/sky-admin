# 13 — 普通部落战统计

> 状态：已实现。实现依据为 `modules/coc_sync/current_war.py`、
> `modules/coc_sync/war_history.py`、`modules/player/member_stats.py`、
> `scripts/scheduler.py` 和 `api_server/routes.py`。

普通部落战与 CWL 是两个独立领域。本页只说明普通部落战；不得以
`registrations`、`league_teams` 或 CWL 的月度 `period` 参与普通战统计。

## 数据链路

```text
COC currentwar / 显式 ClashKing 历史回填
  -> current_war_cache       当前、可覆盖的状态
  -> war_history_cache       每部落最近 45 场已结束普通战完整档案
  -> member_war_facts        每人每战可重建的攻防事实（metric_version=2）
  -> API / 小程序展示
```

`current_war_cache` 一部落一行，保存最近可用快照、尝试时间、失败次数、
`war_key`、载荷哈希和 `history_sealed_at`。临时请求失败不会覆盖已有成功快照。

`war_history_cache` 的唯一键是 `(clan_tag, war_key)`，只归档 `warEnded` 的非
CWL 普通战争。`data_json` 必须含双方完整阵容与**全部**攻击事件；不得按两刀截断。
每个启用自有部落最多保留最近 45 场，清理历史和对应成员事实在同一事务中进行。

`member_war_facts` 的唯一键是 `(clan_tag, war_key, player_tag)`。它保存战争当时的
大本、地图位、观测攻击数、满星前有效攻击/三星数、同口径防守数据和版本号。它是
查询加速投影，不是第二个原始来源，必要时可从 `war_history_cache` 全量重建。

## 统计对象和窗口

接口为：

```text
GET /api/clan/war-stats?clan_tag=<已启用的自有部落 Tag>
```

未传 `clan_tag` 时为兼容旧入口默认战营 `#2QQ`。展示对象始终是当前实际成员：

```sql
accounts.clan_tag = 查询 clan_tag
AND accounts.membership_status != 'left'
```

成员今天加入但没有历史样本仍显示；成员离开后不再显示。历史数据不会因转部落删除。

窗口按该部落的已结束战争 `end_time DESC` 固定切片：前 5、前 15、前 45 场。它们不是
“该玩家自己的最近 N 场”。若部落只归档了 27 场，45 窗口按 27 场计算，响应
`history_coverage` 会返回 `available=27`、`target=45`、`complete=false`。

成员主页的普通战摘要是另一口径：全部自有部落、最近 90 天、该玩家实际参战的最多 15 场；
同样只读取 `member_war_facts` 和已结束档案。

## 满星前规则和展示

每场战争的满星阈值为 `team_size * 3`。进攻、 防守分别按各自全局攻击 `order` 处理：

1. 维护每个被攻击目标的 `best_stars_by_target`；一刀仅贡献相对该目标历史最高星数的增量；
2. 已达阈值前的攻击计入；使有效总星数首次达到阈值的攻击也计入；
3. 达阈值后的同侧攻击不计入；另一侧独立计算，不被截断。

因此补刀不会重复累加同一目标已有的星数。统计为：

```text
进攻三星率 = 满星前进攻三星数 / 满星前有效进攻数
防守三星率 = 满星前被三星数 / 满星前有效防守攻击数
```

小程序单元格默认显示百分比和三段样本强度条：百分比颜色表示表现，亮起的段数表示有效攻击
样本由少到多。轻触单元格才显示完整计数：进攻为“`三星 2 次 / 有效进攻 10 刀`”，防守为
“`被三星 2 次 / 有效被进攻 10 刀`”。这里的“有效”均指满星前计入统计的攻击，分母为 0
显示 `无`，不得显示为 `0%`。

## 调度、补档与回滚

- `current_wars` 每两分钟检查，按战争状态限频；只有最终 `warEnded` 快照可归档。
- `scripts/backfill_war_history.py --limit 100 --keep 45` 默认 dry-run。所有部落成功后，
  显式 `--apply` 才写入；它仅接受包含双方完整逐刀详情的历史战争。
- 旧 `war_results` 与 `member_combat_stats_cache` 已在 2026-10-03 完成完整性校验、COS 备份后
  物理删除；新 schema 不会重建它们。
- 发布或 schema 迁移前使用 `scripts/backup_to_cos.py` 创建可校验 COS 快照。回滚应恢复该
  SQLite 快照并重启服务，而不是重新引入旧聚合写入链路。
- `scripts/retire_normal_war_legacy.py` 保留为可重复的显式退役工具：默认 dry-run，`--yes`
  会先备份并确认每场结束战争均已有 `metric_version >= 2` 事实。
