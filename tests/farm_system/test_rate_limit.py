from __future__ import annotations

from modules.farm_system.rate_limit import LoginFailureLimiter


def test_login_failure_limiter_blocks_and_success_clear_resets():
    now = [100.0]
    limiter = LoginFailureLimiter(max_failures=2, window_seconds=60, clock=lambda: now[0])

    limiter.record_failure(" Farm.User@Example.COM ")
    assert not limiter.is_limited("farm.user@example.com")
    limiter.record_failure("FARM.USER@EXAMPLE.COM")
    assert limiter.is_limited("farm.user@example.com")

    limiter.clear("farm.user@example.com")
    assert not limiter.is_limited("farm.user@example.com")


def test_login_failure_limiter_expires_window():
    now = [100.0]
    limiter = LoginFailureLimiter(max_failures=1, window_seconds=60, clock=lambda: now[0])
    limiter.record_failure("farm.user@example.com")
    assert limiter.is_limited("farm.user@example.com")

    now[0] = 160.0
    assert not limiter.is_limited("farm.user@example.com")
