"""pytest 共享 fixtures。

采用真实内存 SQLite（Database(":memory:")）驱动各模块的 Repository 与
PlayerService，既贴近真实行为（含外键与唯一约束），又无需维护并行的内存假实现。
表格 IO 仍用 FakeExcelIO 以脱离真实文件。
"""
from __future__ import annotations

import pytest

from modules.cwl_registration.repository import RegistrationRepository
from modules.player.repository import PlayerRepository
from modules.player.service import PlayerService
from modules.war_result.repository import ResultRepository
from shared.db.connection import Database
from tests.fakes import FakeExcelIO


@pytest.fixture
def db():
    """内存 SQLite 库，每个用例独立建表、用完销毁。"""
    d = Database(":memory:")
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def player_repo(db) -> PlayerRepository:
    return PlayerRepository(db.conn)


@pytest.fixture
def player_service(player_repo) -> PlayerService:
    return PlayerService(player_repo)


@pytest.fixture
def reg_repo(db) -> RegistrationRepository:
    return RegistrationRepository(db.conn)


@pytest.fixture
def result_repo(db) -> ResultRepository:
    return ResultRepository(db.conn)


@pytest.fixture
def fake_io() -> FakeExcelIO:
    return FakeExcelIO()
