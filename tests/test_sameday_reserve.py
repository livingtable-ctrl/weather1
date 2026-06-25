"""Tests for the same-day slot reservation system (order_executor._sameday_effective_cap)."""

import order_executor

MAX = 8  # MAX_SAME_DAY_POSITIONS used across all tests


def _patch_env(monkeypatch, slots=0, after_hour=12, min_samples=40):
    monkeypatch.setenv("SAME_DAY_RESERVE_SLOTS", str(slots))
    monkeypatch.setenv("SAME_DAY_RESERVE_AFTER_HOUR_UTC", str(after_hour))
    monkeypatch.setenv("SAME_DAY_RESERVE_MIN_SAMPLES", str(min_samples))
    # Force utils module to re-read env vars on next import
    import importlib

    import utils

    importlib.reload(utils)


def test_feature_disabled_returns_max(monkeypatch):
    """SAME_DAY_RESERVE_SLOTS=0 → full cap, no DB call."""
    _patch_env(monkeypatch, slots=0)

    call_count = {"n": 0}

    def fake_count():
        call_count["n"] += 1
        return 99

    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", fake_count, raising=False
    )

    result = order_executor._sameday_effective_cap(MAX)
    assert result == MAX
    assert call_count["n"] == 0  # no DB call when feature is off


def test_threshold_not_met_returns_max(monkeypatch):
    """Slots > 0 but settled < threshold → full cap (not enough data)."""
    _patch_env(monkeypatch, slots=2, after_hour=12, min_samples=40)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 15, raising=False
    )

    result = order_executor._sameday_effective_cap(MAX)
    assert result == MAX


def test_reservation_active_before_cutoff(monkeypatch):
    """Slots > 0, threshold met, hour < cutoff → cap reduced."""
    _patch_env(monkeypatch, slots=2, after_hour=12, min_samples=40)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 45, raising=False
    )

    # Patch datetime so current hour is before cutoff
    from datetime import UTC
    from datetime import datetime as real_dt

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return real_dt(2026, 6, 10, 8, 30, tzinfo=UTC)  # 08:30 UTC < 12:00

    monkeypatch.setattr("order_executor.datetime", _FakeDT)

    result = order_executor._sameday_effective_cap(MAX)
    assert result == MAX - 2  # 8 - 2 = 6


def test_reservation_released_at_cutoff(monkeypatch):
    """Slots > 0, threshold met, hour >= cutoff → full cap released."""
    _patch_env(monkeypatch, slots=2, after_hour=12, min_samples=40)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 45, raising=False
    )

    from datetime import UTC
    from datetime import datetime as real_dt

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return real_dt(2026, 6, 10, 14, 0, tzinfo=UTC)  # 14:00 UTC >= 12:00

    monkeypatch.setattr("order_executor.datetime", _FakeDT)

    result = order_executor._sameday_effective_cap(MAX)
    assert result == MAX


def test_db_error_fails_open(monkeypatch):
    """If count_settled_sameday_predictions raises, return full cap (fail open)."""
    _patch_env(monkeypatch, slots=2, after_hour=12, min_samples=40)

    def _raise():
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", _raise, raising=False
    )

    result = order_executor._sameday_effective_cap(MAX)
    assert result == MAX


# ---------------------------------------------------------------------------
# Dynamic mode tests
# ---------------------------------------------------------------------------


def _patch_dynamic_env(monkeypatch, k=5, band_hours=6, min_samples=150):
    monkeypatch.setenv("SAME_DAY_DYNAMIC_SLOTS", "1")
    monkeypatch.setenv("SAME_DAY_DYNAMIC_K", str(k))
    monkeypatch.setenv("SAME_DAY_DYNAMIC_BAND_HOURS", str(band_hours))
    monkeypatch.setenv("SAME_DAY_RESERVE_MIN_SAMPLES", str(min_samples))
    monkeypatch.setenv("SAME_DAY_RESERVE_SLOTS", "0")
    import importlib

    import utils

    importlib.reload(utils)


def _fake_dt(hour: int):
    """Return a fake datetime class that reports the given UTC hour."""
    from datetime import UTC
    from datetime import datetime as real_dt

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return real_dt(2026, 6, 25, hour, 0, tzinfo=UTC)

    return _FakeDT


def test_dynamic_strong_band(monkeypatch):
    """Strong band win rate (>baseline) → cap clamped to MAX."""
    _patch_dynamic_env(monkeypatch)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 160, raising=False
    )
    monkeypatch.setattr("order_executor.datetime", _fake_dt(8))  # hour=8 → band=1

    # baseline_wr=0.70, band_wr=14/15≈0.933, N=15, K=5
    # blended=(15/20)*0.933+(5/20)*0.70=0.875, scale=1.25 → clamped to MAX
    monkeypatch.setattr(
        "paper.get_sameday_band_stats",
        lambda band_hours=6: {
            "baseline": {"wins": 7, "total": 10},
            "bands": {1: {"wins": 14, "total": 15}},
        },
        raising=False,
    )

    assert order_executor._sameday_effective_cap(MAX) == MAX


def test_dynamic_weak_band(monkeypatch):
    """Weak band with enough data → cap materially reduced."""
    _patch_dynamic_env(monkeypatch)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 160, raising=False
    )
    monkeypatch.setattr("order_executor.datetime", _fake_dt(8))  # hour=8 → band=1

    # baseline_wr=0.70, band_wr=7/20=0.35, N=20, K=5
    # blended=(20/25)*0.35+(5/25)*0.70=0.42, scale=0.60 → cap=round(8*0.60)=5
    monkeypatch.setattr(
        "paper.get_sameday_band_stats",
        lambda band_hours=6: {
            "baseline": {"wins": 7, "total": 10},
            "bands": {1: {"wins": 7, "total": 20}},
        },
        raising=False,
    )

    assert order_executor._sameday_effective_cap(MAX) == 5


def test_dynamic_sparse_band(monkeypatch):
    """Sparse band (N=3) → shrinkage pulls toward baseline, moderate reduction."""
    _patch_dynamic_env(monkeypatch)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 160, raising=False
    )
    monkeypatch.setattr("order_executor.datetime", _fake_dt(8))  # hour=8 → band=1

    # baseline_wr=0.70, band_wr=0/3=0.00, N=3, K=5
    # blended=(3/8)*0+(5/8)*0.70=0.4375, scale=0.625 → cap=round(8*0.625)=5
    monkeypatch.setattr(
        "paper.get_sameday_band_stats",
        lambda band_hours=6: {
            "baseline": {"wins": 7, "total": 10},
            "bands": {1: {"wins": 0, "total": 3}},
        },
        raising=False,
    )

    assert order_executor._sameday_effective_cap(MAX) == 5


def test_dynamic_unknown_band(monkeypatch):
    """Band with no historical data → treated as baseline → cap = MAX."""
    _patch_dynamic_env(monkeypatch)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 160, raising=False
    )
    monkeypatch.setattr(
        "order_executor.datetime", _fake_dt(8)
    )  # hour=8 → band=1, not in bands dict

    monkeypatch.setattr(
        "paper.get_sameday_band_stats",
        lambda band_hours=6: {
            "baseline": {"wins": 7, "total": 10},
            "bands": {},  # no data for any band
        },
        raising=False,
    )

    assert order_executor._sameday_effective_cap(MAX) == MAX


def test_dynamic_insufficient_samples(monkeypatch):
    """Dynamic enabled but settled < threshold → full cap, feature stays dormant."""
    _patch_dynamic_env(monkeypatch, min_samples=150)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 99, raising=False
    )

    assert order_executor._sameday_effective_cap(MAX) == MAX


def test_dynamic_zero_baseline_wins_returns_minimum(monkeypatch):
    """0% baseline win rate (all losses) → cap = 1, not max_positions.

    The wins==0 guard must NOT short-circuit to max_positions — that would defeat
    the dynamic system for its worst-case input. Instead, 0.0 baseline_wr should
    produce cap=1 (the floor).
    """
    _patch_dynamic_env(monkeypatch)
    monkeypatch.setattr(
        "tracker.count_settled_sameday_predictions", lambda: 160, raising=False
    )
    monkeypatch.setattr("order_executor.datetime", _fake_dt(8), raising=False)

    monkeypatch.setattr(
        "paper.get_sameday_band_stats",
        lambda band_hours=6: {
            "baseline": {"wins": 0, "total": 20},  # 0% win rate
            "bands": {1: {"wins": 0, "total": 10}},
        },
        raising=False,
    )

    assert order_executor._sameday_effective_cap(MAX) == 1
