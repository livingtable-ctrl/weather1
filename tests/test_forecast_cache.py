import threading
import time

from forecast_cache import ForecastCache, PersistentForecastCache


def test_get_returns_none_for_missing_key():
    c = ForecastCache(ttl_secs=60)
    assert c.get("missing") is None


def test_get_returns_value_within_ttl():
    c = ForecastCache(ttl_secs=60)
    c.set("k", "v")
    assert c.get("k") == "v"


def test_get_returns_none_after_ttl(monkeypatch):
    c = ForecastCache(ttl_secs=1)
    c.set("k", "v")
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 2)
    assert c.get("k") is None


def test_clear_empties_cache():
    c = ForecastCache(ttl_secs=60)
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert len(c) == 0


# ── L5-A: per-entry TTL (set_with_ttl) tests ─────────────────────────────────


def test_set_with_ttl_returns_value_within_per_entry_ttl():
    """L5-A: set_with_ttl stores value accessible before per-entry TTL expires."""
    c = ForecastCache(ttl_secs=60)  # class default is 60s
    c.set_with_ttl("k", "cycle_data", ttl_secs=300)  # per-entry: 300s
    assert c.get("k") == "cycle_data"


def test_set_with_ttl_expires_before_class_default(monkeypatch):
    """L5-A: per-entry TTL of 2s expires before class-default 60s TTL.

    A cache written just before an NWS cycle (TTL=30s) must expire at
    the cycle boundary, not 60s (class default) or 4h (old flat window).
    """
    c = ForecastCache(ttl_secs=60)  # class TTL: 60s
    c.set_with_ttl("k", "stale_after_cycle", ttl_secs=2)  # per-entry: 2s

    original = time.monotonic
    # Advance 3 seconds — past the 2s per-entry TTL, before the 60s class TTL
    monkeypatch.setattr(time, "monotonic", lambda: original() + 3)
    assert c.get("k") is None, (
        "Per-entry TTL (2s) must cause expiry before class-default TTL (60s)"
    )


def test_set_with_ttl_does_not_affect_other_entries():
    """L5-A: per-entry TTL is isolated — other entries keep their own TTL."""
    c = ForecastCache(ttl_secs=60)
    c.set("default_entry", "d")
    c.set_with_ttl("cycle_entry", "c", ttl_secs=300)
    assert c.get("default_entry") == "d"
    assert c.get("cycle_entry") == "c"


def test_ttl_until_next_cycle_returns_at_least_1800():
    """L5-A: _ttl_until_next_cycle must return at least 1800s (30 min) to prevent thrashing."""
    from weather_markets import _ttl_until_next_cycle

    ttl = _ttl_until_next_cycle()
    assert ttl >= 1800, (
        f"_ttl_until_next_cycle() returned {ttl}s — must be >= 1800s (30 min floor)"
    )


# ── P1-1: get_with_ts tests ───────────────────────────────────────────────────


def test_get_with_ts_miss_returns_triple_none():
    """get_with_ts returns (None, False, 0.0) for a cache miss."""
    c = ForecastCache(ttl_secs=60)
    val, hit, ts = c.get_with_ts("missing")
    assert val is None
    assert hit is False
    assert ts == 0.0


def test_get_with_ts_hit_returns_value_and_true():
    """get_with_ts returns (value, True, wall_ts) on a cache hit."""
    c = ForecastCache(ttl_secs=60)
    c.set("k", "v")
    val, hit, ts = c.get_with_ts("k")
    assert val == "v"
    assert hit is True
    assert ts > 0


def test_get_with_ts_expired_returns_miss(monkeypatch):
    """get_with_ts returns (None, False, 0.0) when the entry has expired."""
    c = ForecastCache(ttl_secs=1)
    c.set("k", "v")
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 2)
    val, hit, ts = c.get_with_ts("k")
    assert val is None
    assert hit is False
    assert ts == 0.0


def test_get_with_ts_wall_clock_reflects_original_store_time(monkeypatch):
    """P1-1: wall_clock_fetch_ts must reflect when the entry was stored, not now.

    We store an entry, then advance monotonic by 2 hours.  The returned
    wall-clock timestamp must be ~2 hours in the past (within 5s tolerance),
    NOT the current time.
    """
    c = ForecastCache(ttl_secs=4 * 3600)
    store_wall = time.time()
    c.set("k", "data")

    advance = 7200  # 2 hours
    original_mono = time.monotonic
    original_wall = time.time

    monkeypatch.setattr(time, "monotonic", lambda: original_mono() + advance)
    monkeypatch.setattr(time, "time", lambda: original_wall() + advance)

    val, hit, returned_wall_ts = c.get_with_ts("k")
    assert hit is True
    # returned timestamp should be close to the original store time, not now
    assert abs(returned_wall_ts - store_wall) < 5, (
        f"Expected timestamp near store time ({store_wall:.0f}), "
        f"got {returned_wall_ts:.0f} (diff={returned_wall_ts - store_wall:.1f}s)"
    )


def test_get_with_ts_per_entry_ttl_respected(monkeypatch):
    """get_with_ts honours per-entry TTL set via set_with_ttl."""
    c = ForecastCache(ttl_secs=3600)
    c.set_with_ttl("k", "v", ttl_secs=5)
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 10)
    val, hit, ts = c.get_with_ts("k")
    assert hit is False


# ── prune_expired() tests ─────────────────────────────────────────────────────


def test_prune_expired_removes_expired_returns_count(monkeypatch):
    """prune_expired() removes all expired entries and returns the correct count."""
    c = ForecastCache(ttl_secs=10)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 20)
    removed = c.prune_expired()
    assert removed == 3
    assert len(c) == 0


def test_prune_expired_leaves_non_expired(monkeypatch):
    """prune_expired() only removes expired entries — fresh entries survive."""
    c = ForecastCache(ttl_secs=60)
    c.set("fresh", "v")
    original = time.monotonic

    # Advance 30s — within 60s TTL, so "fresh" must survive
    monkeypatch.setattr(time, "monotonic", lambda: original() + 30)
    removed = c.prune_expired()
    assert removed == 0
    assert c.get("fresh") == "v"


def test_prune_expired_respects_per_entry_ttl(monkeypatch):
    """prune_expired() uses per-entry TTL for set_with_ttl() entries."""
    c = ForecastCache(ttl_secs=3600)
    c.set_with_ttl("short", "x", ttl_secs=5)
    c.set("long", "y")  # class TTL 3600s
    original = time.monotonic

    # Advance 10s — past short's 5s TTL, well within long's 3600s TTL
    monkeypatch.setattr(time, "monotonic", lambda: original() + 10)
    removed = c.prune_expired()
    assert removed == 1
    assert c.get("short") is None
    assert c.get("long") == "y"


def test_prune_expired_empty_cache():
    """prune_expired() on an empty cache returns 0 without error."""
    c = ForecastCache(ttl_secs=60)
    assert c.prune_expired() == 0


def test_ttl_until_next_cycle_at_cycle_boundary():
    """L5-A: just before a model cycle, TTL is short; just after, TTL is long.

    At 07:58 UTC (2 minutes before 08:00 availability), TTL should be ~120s
    clamped to the 1800s floor. At 08:02 UTC (just after), TTL should be ~6h.
    """
    from datetime import UTC, datetime

    from weather_markets import _ttl_until_next_cycle

    # Just before 08:00 cycle — 2 minutes away → floor at 1800s
    before_cycle = datetime(2026, 4, 24, 7, 58, 0, tzinfo=UTC)
    ttl_before = _ttl_until_next_cycle(before_cycle)
    assert ttl_before == 1800, (
        f"At 07:58 UTC (2 min before cycle), TTL should be floored at 1800s, got {ttl_before}"
    )

    # Just after 08:00 cycle — next cycle at 14:00 is ~6h away
    after_cycle = datetime(2026, 4, 24, 8, 2, 0, tzinfo=UTC)
    ttl_after = _ttl_until_next_cycle(after_cycle)
    assert ttl_after > 3600, (
        f"At 08:02 UTC (2 min after cycle), TTL should be ~6h, got {ttl_after}s"
    )
    assert ttl_after <= 6 * 3600, f"At 08:02 UTC, TTL should be <= 6h, got {ttl_after}s"


# ── PersistentForecastCache (backlog.txt "ForecastCache EXISTS, BUT ~14
# HAND-ROLLED TTL DICTS" -- nws.py's _station_cache, 2026-07-25) ────────────


def _tuple_key_to_str(key: tuple[float, float]) -> str:
    return f"{key[0]},{key[1]}"


def _tuple_str_to_key(key_str: str) -> tuple[float, float]:
    lat_str, lon_str = key_str.split(",")
    return (float(lat_str), float(lon_str))


def test_persistent_cache_is_a_forecast_cache():
    """PersistentForecastCache must still behave as a normal ForecastCache
    for get/set -- it only adds dump/load, it doesn't change base behavior."""
    c = PersistentForecastCache(ttl_secs=float("inf"))
    assert isinstance(c, ForecastCache)
    c.set((40.0, -75.0), "KPHL")
    assert c.get((40.0, -75.0)) == "KPHL"
    assert c.get((1.0, 1.0)) is None


def test_dump_then_load_round_trips_values(tmp_path):
    """The exact property nws.py's station cache depends on: dump the
    current cache to disk, load it into a fresh instance, get back the same
    values under the same keys."""
    path = tmp_path / "cache.json"
    c1 = PersistentForecastCache(ttl_secs=float("inf"))
    c1.set((40.7128, -74.006), "KNYC")
    c1.set((41.8781, -87.6298), "KORD")
    c1.dump_to_disk(path, _tuple_key_to_str)

    c2 = PersistentForecastCache(ttl_secs=float("inf"))
    assert c2.get((40.7128, -74.006)) is None  # sanity: fresh instance is empty
    c2.load_from_disk(path, _tuple_str_to_key)
    assert c2.get((40.7128, -74.006)) == "KNYC"
    assert c2.get((41.8781, -87.6298)) == "KORD"


def test_load_from_disk_reads_file_written_with_explicit_utf8(tmp_path):
    """L-10/L-3: load_from_disk's path.read_text() used to omit
    encoding="utf-8" -- safe_io.atomic_write_json (which dump_to_disk
    itself uses) always writes UTF-8, so a read relying on a different
    platform default codec (e.g. cp1252 on a non-English-locale Windows, or
    any Python below the 3.15 UTF-8-mode-by-default PEP 686 change) could
    silently mis-decode any non-ASCII byte a station identifier or future
    key ever contained. This locks in correct non-ASCII round-tripping as a
    regression guard; it does not itself discriminate the `encoding="utf-8"`
    keyword on THIS machine, since this interpreter's own platform default
    already resolves to UTF-8 (mutation-tested and confirmed non-
    discriminating here -- kept anyway as real behavioral coverage for
    platforms where the default differs)."""
    import json

    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"40.0,-75.0": "Zürich-é"}), encoding="utf-8")

    c = PersistentForecastCache(ttl_secs=float("inf"))
    c.load_from_disk(path, _tuple_str_to_key)
    assert c.get((40.0, -75.0)) == "Zürich-é"


def test_load_from_disk_is_a_noop_when_file_does_not_exist(tmp_path):
    """First-ever process start (no prior dump) must not raise -- matches
    nws.py's _load_station_cache try/except-and-log convention expecting a
    plain no-op, not an exception, on a missing file."""
    c = PersistentForecastCache(ttl_secs=float("inf"))
    c.load_from_disk(tmp_path / "does_not_exist.json", _tuple_str_to_key)
    assert len(c) == 0


def test_dump_creates_missing_parent_directories(tmp_path):
    """nws.py's real cache path is data/.nws_station_cache.json -- the
    parent directory may not exist yet on a fresh checkout."""
    path = tmp_path / "nested" / "dir" / "cache.json"
    c = PersistentForecastCache(ttl_secs=float("inf"))
    c.set((1.0, 2.0), "KTEST")
    c.dump_to_disk(path, _tuple_key_to_str)
    assert path.exists()


def test_dump_only_persists_values_not_internal_timestamps(tmp_path):
    """Regression: dump_to_disk must write v[0] (the value), not the raw
    (value, ts) tuple -- a naive dump would corrupt the persisted format
    and break every consumer expecting a bare value back from load."""
    path = tmp_path / "cache.json"
    c = PersistentForecastCache(ttl_secs=float("inf"))
    c.set((1.0, 2.0), "KTEST")
    c.dump_to_disk(path, _tuple_key_to_str)
    import json

    on_disk = json.loads(path.read_text())
    assert on_disk == {"1.0,2.0": "KTEST"}


def test_persistent_cache_get_set_is_thread_safe():
    """Concurrent set() calls for DIFFERENT keys from multiple threads must
    not corrupt the store or raise -- base ForecastCache-level thread
    safety (already provided by the shared lock), re-verified here since
    PersistentForecastCache is meant to be used exactly this way. The
    dict-comprehension-over-.items()-racing-a-concurrent-write hazard this
    subclass specifically closes is covered by
    test_persistent_cache_dump_is_thread_safe_against_concurrent_writes
    below, not this test -- this one never iterates the store at all."""
    c = PersistentForecastCache(ttl_secs=float("inf"))
    errors: list[Exception] = []

    def _writer(i: int) -> None:
        try:
            for j in range(50):
                c.set((float(i), float(j)), f"STATION_{i}_{j}")
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(c) == 8 * 50
    assert c.get((3.0, 10.0)) == "STATION_3_10"


def test_persistent_cache_dump_is_thread_safe_against_concurrent_writes():
    """Regression for the specific bug this migration fixes: dump_to_disk
    (iterates the store) running concurrently with set() (writes a new key)
    on the plain-dict version could raise 'dictionary changed size during
    iteration'. PersistentForecastCache's dump_to_disk holds the same lock
    set() does, so this must complete without error regardless of
    interleaving.

    max_size is raised above the total entries this test ever writes
    (60,000) deliberately: with the default max_size=500, the writer thread
    evicts-then-inserts once past 500 entries, which keeps the store's
    *size* stable -- and CPython's iteration guard fires on a size change,
    not a content change, so a size-stable store never trips it even with
    the lock removed.

    The store must actually be large (30,000 pre-seeded + 30,000 written
    during the race) for the race to be reliably reproducible at all: a
    small dict's comprehension completes in far too few bytecode steps for
    the writer thread's inserts to have a realistic chance of landing
    mid-iteration, so a version of this test with only ~5000 entries and 30
    dump attempts passed identically whether or not dump_to_disk's lock was
    present (false confidence, caught only by deliberately mutating a
    scratch copy of the class and re-running this exact test body). At
    these tuned sizes, mutation-testing an unlocked dump_to_disk (via a
    standalone subclass, not editing the real source) reproduced
    RuntimeError 20/20 times across repeated runs, and the real (locked)
    implementation produced zero false positives across 20 runs -- both
    complete in well under a second, since only 5 dump_to_disk calls are
    needed once the store is this size."""
    c = PersistentForecastCache(ttl_secs=float("inf"), max_size=500_000)
    for i in range(30_000):
        c.set((float(i), 0.0), f"STATION_{i}")
    errors: list[Exception] = []

    def _writer() -> None:
        for i in range(1_000_000, 1_030_000):
            c.set((float(i), 0.0), f"STATION_{i}")

    def _dumper(path) -> None:
        try:
            for _ in range(5):
                c.dump_to_disk(path, _tuple_key_to_str)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cache.json"
        writer = threading.Thread(target=_writer)
        dumper = threading.Thread(target=_dumper, args=(path,))
        writer.start()
        dumper.start()
        writer.join()
        dumper.join()

    assert errors == []
    assert len(c) == 30_000 + 30_000


def test_dump_to_disk_raises_on_per_entry_ttl_entry(tmp_path):
    """dump_to_disk must refuse (not silently drop the TTL) when the cache
    holds an entry written via set_with_ttl -- a per-entry TTL is a
    *remaining* duration, meaningless once the timestamp it's relative to
    is gone across a dump/load round-trip. Silently dropping it would
    resurrect an entry that should already have expired."""
    import pytest

    c = PersistentForecastCache(ttl_secs=float("inf"))
    c.set_with_ttl((1.0, 2.0), "KTEST", ttl_secs=30)
    with pytest.raises(ValueError, match="per-entry TTL"):
        c.dump_to_disk(tmp_path / "cache.json", _tuple_key_to_str)


def test_load_from_disk_does_not_evict_beyond_max_size(tmp_path):
    """Regression: load_from_disk must restore the ENTIRE persisted
    snapshot even if it exceeds max_size -- routing restoration through the
    normal set() (which evicts at max_size) would silently truncate a
    dump/load round-trip, and the very next dump_to_disk() call would then
    make that data loss permanent on disk."""
    path = tmp_path / "cache.json"
    c1 = PersistentForecastCache(ttl_secs=float("inf"), max_size=10_000_000)
    for i in range(600):
        c1.set((float(i), 0.0), f"STATION_{i}")
    c1.dump_to_disk(path, _tuple_key_to_str)

    c2 = PersistentForecastCache(ttl_secs=float("inf"), max_size=500)
    c2.load_from_disk(path, _tuple_str_to_key)
    assert len(c2) == 600, (
        "load_from_disk truncated the restore to max_size instead of "
        "restoring the full persisted snapshot"
    )
    assert c2.get((0.0, 0.0)) == "STATION_0"
    assert c2.get((599.0, 0.0)) == "STATION_599"
