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
            # L5-A: entries may carry a per-entry TTL (3-tuple) or use the class
            # default (2-tuple). Per-entry TTL enables NWS-cycle-aligned expiry.
            if len(entry) == 3:
                value, ts, entry_ttl = entry
                effective_ttl = entry_ttl
            else:
                value, ts = entry
                effective_ttl = self._ttl
            if time.monotonic() - ts > effective_ttl:
                del self._store[key]
                return None
            return value

    def set(self, key, value: T) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic())

    def set_with_ttl(self, key, value: T, ttl_secs: float) -> None:
        """Store with a per-entry TTL, overriding the class-level default.

        L5-A: used to align cache expiry with the next NWS model cycle rather
        than a flat 4-hour window.  Call with ttl_secs=_ttl_until_next_cycle().
        """
        with self._lock:
            self._store[key] = (value, time.monotonic(), ttl_secs)

    def set_at(self, key, value: T, ts: float) -> None:
        """Store with an explicit monotonic timestamp (e.g. when restoring from disk)."""
        with self._lock:
            self._store[key] = (value, ts)

    def get_with_ts(self, key) -> tuple:
        """Return (value, hit, wall_clock_fetch_ts).

        wall_clock_fetch_ts is derived from the stored monotonic timestamp so it
        reflects when the entry was originally fetched, not when get_with_ts was
        called.  Returns (None, False, 0.0) on miss or expiry.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None, False, 0.0
            if len(entry) == 3:
                value, ts, entry_ttl = entry
                effective_ttl = entry_ttl
            else:
                value, ts = entry
                effective_ttl = self._ttl
            if time.monotonic() - ts > effective_ttl:
                del self._store[key]
                return None, False, 0.0
            age = time.monotonic() - ts
            wall_clock_ts = time.time() - age
            return value, True, wall_clock_ts

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
