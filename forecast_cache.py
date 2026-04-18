"""
Thread-safe in-memory forecast cache with TTL expiry.
Replaces the module-level globals in weather_markets.py.
"""

import threading
import time


class ForecastCache[T]:
    """
    Thread-safe dict-based cache with per-entry TTL.
    Keys are arbitrary hashable objects; values are typed by the T parameter.
    """

    def __init__(self, ttl_secs: float = 4 * 3600) -> None:
        self._ttl = ttl_secs
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key) -> T | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key, value: T) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic())

    def set_at(self, key, value: T, ts: float) -> None:
        """Store with an explicit monotonic timestamp (e.g. when restoring from disk)."""
        with self._lock:
            self._store[key] = (value, ts)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
