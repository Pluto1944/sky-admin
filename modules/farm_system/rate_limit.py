"""互刷系统登录失败的进程内基础限流。"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from .security import normalize_username


class LoginFailureLimiter:
    """按规范化账号限制连续失败；成功登录后清零。

    这是 F1 的基础防爆破措施。状态仅保存在当前 API worker 内，后续若需要跨
    worker 的严格限流，可在网关或共享存储层升级，而不改变认证服务接口。
    """

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 15 * 60,
        max_keys: int = 4096,
        clock=time.monotonic,
    ):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._failures: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(username: str) -> str:
        try:
            return normalize_username(username)
        except ValueError:
            return str(username or "").strip().casefold()[:64]

    def is_limited(self, username: str) -> bool:
        key = self._key(username)
        now = self._clock()
        with self._lock:
            state = self._failures.get(key)
            if state is None:
                return False
            count, started_at = state
            if now - started_at >= self.window_seconds:
                self._failures.pop(key, None)
                return False
            self._failures.move_to_end(key)
            return count >= self.max_failures

    def record_failure(self, username: str) -> None:
        key = self._key(username)
        now = self._clock()
        with self._lock:
            count, started_at = self._failures.get(key, (0, now))
            if now - started_at >= self.window_seconds:
                count, started_at = 0, now
            self._failures[key] = (count + 1, started_at)
            self._failures.move_to_end(key)
            while len(self._failures) > self.max_keys:
                self._failures.popitem(last=False)

    def clear(self, username: str) -> None:
        with self._lock:
            self._failures.pop(self._key(username), None)
