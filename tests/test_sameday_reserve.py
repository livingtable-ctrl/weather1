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
