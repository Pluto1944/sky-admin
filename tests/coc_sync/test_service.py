"""CocSyncService 编排测试：注入 FakeCocApiClient，全程离线。

覆盖：多部落汇总建档 / 新增·更新统计 / 跨部落去重 / 单部落失败隔离 / 退部对账。
"""
from __future__ import annotations

import json

from modules.coc_sync import config as coc_config
from modules.coc_sync.service import CocSyncService
from tests.fakes import FakeCocApiClient, coc_member


def test_sync_single_clan_creates_accounts(player_service):
    api = FakeCocApiClient({"#C1": [coc_member("#A", "甲", trophies=5000), coc_member("#B", "乙")]})
    stats = CocSyncService(player_service, api).sync_clans([{"tag": "#C1", "name": "一部"}])

    assert stats["clans"] == 1
    assert stats["members"] == 2
    assert stats["created"] == 2
    assert stats["updated"] == 0

    a = player_service.get("#A")
    assert a["account_name"] == "甲"
    assert a["trophies"] == 5000
    assert a["clan_tag"] == "#C1"
    assert a["last_synced_at"] is not None


def test_resync_updates_not_duplicates(player_service):
    api = FakeCocApiClient({"#C1": [coc_member("#A", "甲", trophies=100)]})
    svc = CocSyncService(player_service, api)
    svc.sync_clans([{"tag": "#C1"}])

    api2 = FakeCocApiClient({"#C1": [coc_member("#A", "甲", trophies=999)]})
    stats = CocSyncService(player_service, api2).sync_clans([{"tag": "#C1"}])

    assert stats["created"] == 0
    assert stats["updated"] == 1
    assert player_service.get("#A")["trophies"] == 999
    assert len(player_service.list_all()) == 1


def test_dedup_same_tag_across_clans(player_service, capsys):
    api = FakeCocApiClient(
        {"#C1": [coc_member("#A", "甲")], "#C2": [coc_member("#A", "甲"), coc_member("#B", "乙")]}
    )
    stats = CocSyncService(player_service, api).sync_clans(
        [{"tag": "#C1", "name": "一部"}, {"tag": "#C2", "name": "二部"}]
    )

    assert stats["members"] == 2          # #A 只算一次
    assert stats["duplicates"] == 1
    assert player_service.get("#A")["clan_tag"] == "#C1"  # 取首个部落
    assert "同时出现在" in capsys.readouterr().err


def test_failed_clan_isolated_when_not_fail_fast(player_service, capsys, monkeypatch):
    monkeypatch.setattr(coc_config, "FAIL_FAST", False)
    api = FakeCocApiClient({"#OK": [coc_member("#A", "甲")]}, fail_clans={"#BAD"})

    stats = CocSyncService(player_service, api).sync_clans([{"tag": "#BAD"}, {"tag": "#OK"}])

    assert stats["failed_clans"] == ["#BAD"]
    assert stats["created"] == 1          # #OK 仍成功
    assert "同步失败" in capsys.readouterr().err


def test_fetch_clan_members_readonly_no_write(player_service):
    api = FakeCocApiClient({"#C1": [coc_member("#A", "甲")]})
    svc = CocSyncService(player_service, api)
    members = svc.fetch_clan_members("#C1", "一部")

    assert members[0]["player_tag"] == "#A"
    assert json.loads(members[0]["coc_raw"])["_clan_tag"] == "#C1"
    assert player_service.list_all() == []            # 只读，不落库


# ---------------------------------------------------------------------------
# 退部对账
# ---------------------------------------------------------------------------
def test_member_leaves_with_no_clan_marked_left(player_service):
    # 首次同步：#A 在 #C1
    CocSyncService(
        player_service, FakeCocApiClient({"#C1": [coc_member("#A", "甲"), coc_member("#B", "乙")]})
    ).sync_clans([{"tag": "#C1"}])

    # 再次同步：#A 从成员列表消失，且 get_player 查不到新部落 -> 判定退部
    api2 = FakeCocApiClient({"#C1": [coc_member("#B", "乙")]})
    stats = CocSyncService(player_service, api2).sync_clans([{"tag": "#C1"}])

    assert stats["left"] == 1
    a = player_service.get("#A")
    assert a["membership_status"] == "left"
    assert a["clan_tag"] is None
    assert player_service.get("#B")["membership_status"] == "member"


def test_member_moves_to_external_clan_marked_left(player_service):
    CocSyncService(
        player_service, FakeCocApiClient({"#C1": [coc_member("#A", "甲")]})
    ).sync_clans([{"tag": "#C1"}])

    # #A 转去联盟外部落 #EXT（默认 config.CLANS 不含 #EXT）
    api2 = FakeCocApiClient(
        {"#C1": []},
        players_by_tag={"#A": {"tag": "#A", "role": "member", "clan": {"tag": "#EXT"}}},
    )
    stats = CocSyncService(player_service, api2).sync_clans([{"tag": "#C1"}])

    assert stats["left"] == 1
    a = player_service.get("#A")
    assert a["membership_status"] == "left"
    assert a["clan_tag"] == "#EXT"


def test_member_moves_within_alliance_not_left(player_service, monkeypatch):
    # 联盟含 #C1 与 #C2；本轮只同步 #C1
    monkeypatch.setattr(coc_config, "CLANS", [{"tag": "#C1"}, {"tag": "#C2"}])
    CocSyncService(
        player_service, FakeCocApiClient({"#C1": [coc_member("#A", "甲")]})
    ).sync_clans([{"tag": "#C1"}])

    # #A 转到联盟内的 #C2（本轮未同步）-> 不判退部，只更新归属
    api2 = FakeCocApiClient(
        {"#C1": []},
        players_by_tag={"#A": {"tag": "#A", "role": "elder", "clan": {"tag": "#C2"}}},
    )
    stats = CocSyncService(player_service, api2).sync_clans([{"tag": "#C1"}])

    assert stats["left"] == 0
    a = player_service.get("#A")
    assert a["membership_status"] == "member"
    assert a["clan_tag"] == "#C2"
    assert a["clan_role"] == "elder"


def test_failed_clan_does_not_trigger_left(player_service, monkeypatch):
    monkeypatch.setattr(coc_config, "FAIL_FAST", False)
    CocSyncService(
        player_service, FakeCocApiClient({"#C1": [coc_member("#A", "甲")]})
    ).sync_clans([{"tag": "#C1"}])

    # #C1 本轮抓取失败：不能把其成员误判为退部
    api2 = FakeCocApiClient({}, fail_clans={"#C1"})
    stats = CocSyncService(player_service, api2).sync_clans([{"tag": "#C1"}])

    assert stats["left"] == 0
    assert player_service.get("#A")["membership_status"] == "member"
