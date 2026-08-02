"""status_rule 纯函数测试（player 模块）。"""
from __future__ import annotations

from config import STATUS_ACTIVE, STATUS_MAYBE_LEFT, STATUS_MISSED
from modules.player.status_rule import infer_status, period_diff


def test_period_diff_basic():
    assert period_diff("2026-06", "2026-07") == 1
    assert period_diff("2026-01", "2026-07") == 6
    assert period_diff("2025-12", "2026-01") == 1
    assert period_diff("2025-07", "2026-07") == 12


def test_period_diff_invalid_returns_zero():
    assert period_diff("bad", "2026-07") == 0
    assert period_diff(None, "2026-07") == 0


def test_registered_this_period_is_active():
    assert infer_status("2026-06", "2026-07", True) == STATUS_ACTIVE


def test_missed_one_month():
    # 上月报名，本月没报，间隔 1 月 < 阈值(2) -> missed
    assert infer_status("2026-06", "2026-07", False, maybe_left_months=2) == STATUS_MISSED


def test_maybe_left_after_threshold():
    # 距最后报名 >= 2 月且本月没报 -> maybe_left
    assert infer_status("2026-05", "2026-07", False, maybe_left_months=2) == STATUS_MAYBE_LEFT


def test_missed_then_register_back_to_active():
    assert infer_status("2026-05", "2026-07", True, maybe_left_months=2) == STATUS_ACTIVE


def test_never_registered_and_not_this_period():
    assert infer_status(None, "2026-07", False) == STATUS_MAYBE_LEFT
