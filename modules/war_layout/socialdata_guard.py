"""Hard safety guards for low-balance SocialData usage.

The guard fails closed: once the free request budget is exhausted it raises
instead of waiting, retrying, or making a billable request.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SocialDataBudgetExceeded(RuntimeError):
    """Raised before a request that could exceed the configured free budget."""


class SocialDataBudgetGuard:
    """Allow at most ``max_requests`` in every rolling ``window_seconds``."""

    def __init__(self, max_requests: int = 3, window_seconds: float = 60.0):
        if max_requests < 1 or window_seconds <= 0:
            raise ValueError("invalid SocialData budget guard configuration")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def check_and_record(self) -> None:
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] >= self.window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self.max_requests:
                raise SocialDataBudgetExceeded(
                    "SocialData free request budget reached; refusing additional request"
                )
        self._calls.append(now)
