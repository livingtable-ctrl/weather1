import time

from forecast_cache import ForecastCache


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
