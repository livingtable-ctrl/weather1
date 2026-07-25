"""
Thread-safe in-memory forecast cache with TTL expiry.
Replaces the module-level globals in weather_markets.py.
"""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from safe_io import atomic_write_json


class ForecastCache[T]:
    """
    Thread-safe dict-based cache with per-entry TTL and LRU eviction.
    Keys are arbitrary hashable objects; values are typed by the T parameter.
    """

    def __init__(self, ttl_secs: float = 4 * 3600, max_size: int = 500) -> None:
        self._ttl = ttl_secs
        self._max_size = max_size
        self._store: dict = {}
        self._lock = threading.Lock()

    def _effective_ttl(self, entry: tuple) -> float:
        """Return the TTL for an entry: per-entry (3-tuple) or class default (2-tuple)."""
        return entry[2] if len(entry) == 3 else self._ttl

    def get(self, key) -> T | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, ts = entry[0], entry[1]
            if time.monotonic() - ts > self._effective_ttl(entry):
                del self._store[key]
                return None
            return value

    def _evict_oldest(self) -> None:
        """Remove the entry with the smallest (oldest) timestamp. Must hold _lock."""
        if not self._store:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k][1])
        del self._store[oldest_key]

    def set(self, key, value: T) -> None:
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_size:
                self._evict_oldest()
            self._store[key] = (value, time.monotonic())

    def set_with_ttl(self, key, value: T, ttl_secs: float) -> None:
        """Store with a per-entry TTL, overriding the class-level default.

        L5-A: used to align cache expiry with the next NWS model cycle rather
        than a flat 4-hour window.  Call with ttl_secs=_ttl_until_next_cycle().
        """
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_size:
                self._evict_oldest()
            self._store[key] = (value, time.monotonic(), ttl_secs)

    def set_at(self, key, value: T, ts: float) -> None:
        """Store with an explicit monotonic timestamp (e.g. when restoring from disk).

        ts must be a monotonic timestamp (time.monotonic()), not a wall-clock timestamp.
        """
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_size:
                self._evict_oldest()
            self._store[key] = (value, ts)

    def set_at_with_ttl(self, key, value: T, ts: float, ttl_secs: float) -> None:
        """Store with both an explicit monotonic timestamp AND a per-entry TTL.

        Use when restoring an entry from disk that was originally written with
        set_with_ttl() — set_at() alone would silently widen a short,
        cycle-aligned TTL back out to the class default, resurrecting data
        that was already meant to have expired.
        """
        with self._lock:
            if key not in self._store and len(self._store) >= self._max_size:
                self._evict_oldest()
            self._store[key] = (value, ts, ttl_secs)

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
            value, ts = entry[0], entry[1]
            if time.monotonic() - ts > self._effective_ttl(entry):
                del self._store[key]
                return None, False, 0.0
            age = time.monotonic() - ts
            wall_clock_ts = time.time() - age
            return value, True, wall_clock_ts

    def prune_expired(self) -> int:
        """Remove all expired entries. Returns the number of entries removed."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired = [
                k
                for k, entry in self._store.items()
                if now - entry[1] > self._effective_ttl(entry)
            ]
            for k in expired:
                del self._store[k]
                removed += 1
        return removed

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class PersistentForecastCache[T](ForecastCache[T]):
    """ForecastCache with whole-dict persistence to a JSON file.

    For permanent (ttl_secs=inf) caches whose entries should survive process
    restarts -- e.g. nws.py's station-ID lookup cache, where the underlying
    fact (which NWS station serves a given lat/lon) never changes. Adds
    dump_to_disk()/load_from_disk() on top of the base class without
    touching any of ForecastCache's existing methods, so every other
    ForecastCache consumer (weather_markets.py's _ensemble_cache and the
    rest) is unaffected by this subclass existing.

    Keys must be representable as JSON object keys via the caller-provided
    key_to_str/str_to_key round-trip (e.g. a (lat, lon) float tuple <->
    "lat,lon" string) -- arbitrary hashable keys, the base class's actual
    contract, can't all be JSON object keys directly.

    Error handling is deliberately the caller's job, not this class's: dump/
    load raise on failure rather than swallowing exceptions, matching
    ForecastCache's own "generic mechanism, no embedded policy" shape. A
    caller that wants best-effort persistence (e.g. nws.py's
    _load_station_cache/_save_station_cache, which log-and-continue on
    failure) wraps these calls in its own try/except.

    Only supports plain entries written via set()/set_at() (2-tuple:
    value + timestamp) -- an entry written via set_with_ttl()/
    set_at_with_ttl() (3-tuple: value + timestamp + per-entry TTL) can't be
    round-tripped through dump/load without a real design decision this
    class doesn't make for you: the per-entry TTL is a *remaining* duration,
    which is meaningless once the timestamp it was relative to is gone
    (get_with_ts()'s wall-clock timestamp plus a recomputed remaining-TTL
    would be needed, not the monotonic timestamp set_at()/set_at_with_ttl()
    expect). dump_to_disk() raises rather than silently dropping the TTL
    and resurrecting an entry that should have already expired. If a future
    consumer needs both per-entry TTL AND disk persistence, that's a new,
    deliberate extension -- not something to bolt on here by guessing.

    dump_to_disk() holds this instance's own (non-reentrant) lock for its
    ENTIRE duration, including the file write -- deliberately, so two
    threads calling dump_to_disk() concurrently for the same instance can't
    both write the same safe_io.atomic_write_json temp filename at once
    (that filename is derived only from `path`, not per-call, so without
    this the second writer's temp file could collide with the first's
    still-in-flight one). One consequence: a `key_to_str` callback that
    itself reads/writes this same cache instance would deadlock -- every
    current caller's key_to_str is a pure formatting function with no cache
    access, so this is a documented constraint, not a bug fix pending.
    Another: set()/get() calls from other threads block for the duration
    of the disk write (temp file + fsync + rename, plus retries on
    failure), not just the in-memory snapshot -- acceptable for a cache
    written a handful of times per scan cycle, not a hot path.
    """

    def dump_to_disk(self, path: Path, key_to_str: Callable[[Any], str]) -> None:
        """Persist the entire cache to `path` as JSON, atomically (via
        safe_io.atomic_write_json -- temp file + fsync + rename, so a
        process kill mid-write can't leave truncated/corrupt JSON on disk).
        Creates parent directories if needed; overwrites any existing file.
        Holds this instance's lock for the full call, including the write
        itself -- see the class docstring for why.

        Raises ValueError if any entry was written via set_with_ttl()/
        set_at_with_ttl() (a 3-tuple) -- see the class docstring."""
        with self._lock:
            for entry in self._store.values():
                if len(entry) == 3:
                    raise ValueError(
                        "PersistentForecastCache.dump_to_disk: found an entry "
                        "with a per-entry TTL (set_with_ttl/set_at_with_ttl) -- "
                        "not supported by dump/load, see the class docstring"
                    )
            serializable = {key_to_str(k): v[0] for k, v in self._store.items()}
            atomic_write_json(serializable, path)

    def load_from_disk(self, path: Path, str_to_key: Callable[[str], Any]) -> None:
        """Load a previously dumped cache from `path` into this instance, if
        the file exists (a no-op otherwise). Entries are stored with a
        fresh time.monotonic() timestamp -- correct for a permanent
        (ttl_secs=inf) cache, since an infinite TTL never expires regardless
        of timestamp.

        Bypasses the base class's max_size LRU eviction: a caller loading a
        persisted snapshot wants that exact snapshot back, not a silent
        partial restore truncated to whatever max_size happens to be
        configured today (found live: the base class's default max_size=500
        would otherwise silently drop entries beyond the 500th on load, and
        the next dump_to_disk() call would then make that loss permanent on
        disk). If the restored count exceeds max_size, subsequent set()
        calls still evict normally -- only the load itself is unbounded."""
        if not path.exists():
            return
        raw = json.loads(path.read_text())
        now = time.monotonic()
        with self._lock:
            for k_str, value in raw.items():
                self._store[str_to_key(k_str)] = (value, now)
