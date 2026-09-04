import pytest

from .socialdata_guard import SocialDataBudgetExceeded, SocialDataBudgetGuard


def test_guard_rejects_fourth_request(monkeypatch):
    clock = iter([0.0, 1.0, 2.0, 3.0])
    monkeypatch.setattr("modules.war_layout.socialdata_guard.time.monotonic", lambda: next(clock))
    guard = SocialDataBudgetGuard()
    guard.check_and_record()
    guard.check_and_record()
    guard.check_and_record()
    with pytest.raises(SocialDataBudgetExceeded):
        guard.check_and_record()


def test_guard_allows_next_window(monkeypatch):
    clock = iter([0.0, 1.0, 2.0, 60.0])
    monkeypatch.setattr("modules.war_layout.socialdata_guard.time.monotonic", lambda: next(clock))
    guard = SocialDataBudgetGuard()
    for _ in range(3):
        guard.check_and_record()
    guard.check_and_record()
