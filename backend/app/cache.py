from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

T = TypeVar("T")


class TTLCache:
    """Thread-safe in-memory cache with per-entry expiry."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if expires < self._clock():
                del self._data[key]
                return None
            return value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        with self._lock:
            self._data[key] = (self._clock() + ttl, value)

    def get_or_set(self, key: Hashable, ttl: float, fn: Callable[[], T]) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = fn()
        self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
