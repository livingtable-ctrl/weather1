"""Tests for CircuitBreaker — open/close/half-open, backoff, wall-clock."""

from __future__ import annotations

import time

import pytest

from circuit_breaker import CircuitBreaker


class TestCircuitBreakerBasic:
    def test_initially_closed(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        assert not cb.is_open()
        assert cb.failure_count == 0

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        cb.record_failure()
        assert not cb.is_open()
        cb.record_failure()
        assert cb.is_open()

    def test_success_resets_to_closed(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()
        cb.record_success()
        assert not cb.is_open()
        assert cb.failure_count == 0

    def test_half_open_after_timeout(self):
        # A 10ms recovery_timeout raced the immediate `assert cb.is_open()`
        # right after record_failure() -- under real test-suite load (many
        # tests collected/running), that first assertion alone could take
        # longer than 10ms, making the breaker already past its recovery
        # window and flakily fail. Wider margin (0.5s timeout, 0.6s sleep)
        # keeps the same behavior under test without a realistic race.
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.5)
        cb.record_failure()
        assert cb.is_open()
        time.sleep(0.6)
        # After timeout elapses, is_open() transitions to half-open (returns False)
        assert not cb.is_open()

    def test_seconds_open_is_zero_when_closed(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        assert cb.seconds_open() == pytest.approx(0.0)

    def test_seconds_open_increases_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        time.sleep(0.05)
        assert cb.seconds_open() >= 0.04

    def test_seconds_until_retry_zero_when_closed(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        assert cb.seconds_until_retry() == pytest.approx(0.0)

    def test_seconds_until_retry_positive_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        retry = cb.seconds_until_retry()
        assert 0.0 < retry <= 60.0

    def test_failure_count_property(self):
        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout=60)
        for i in range(3):
            cb.record_failure()
        assert cb.failure_count == 3


class TestCircuitBreakerBackoff:
    def test_first_trip_uses_base_timeout(self):
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=60, backoff_multiplier=2.0
        )
        cb.record_failure()
        assert cb._current_timeout == pytest.approx(60.0)

    def test_second_trip_doubles_timeout(self):
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=60, backoff_multiplier=2.0
        )
        # Trip 1
        cb.record_failure()
        cb.record_success()  # reset
        # Trip 2
        cb.record_failure()
        assert cb._current_timeout == pytest.approx(120.0)

    def test_third_trip_quadruples_timeout(self):
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=60, backoff_multiplier=2.0
        )
        for _ in range(2):  # 2 loops + 1 final = 3 trips total
            cb.record_failure()
            cb.record_success()
        cb.record_failure()  # trip 3 → 60 * 2^2 = 240s
        assert cb._current_timeout == pytest.approx(240.0)

    def test_backoff_capped_at_24h(self):
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=3600, backoff_multiplier=10.0
        )
        for _ in range(10):
            cb.record_failure()
            cb.record_success()
        cb.record_failure()
        assert cb._current_timeout <= 86400.0

    def test_backoff_persists_through_success(self):
        """Backoff accumulates across open/close cycles — success does not reset it."""
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=60, backoff_multiplier=2.0
        )
        cb.record_failure()  # trip 1 → 60s
        cb.record_success()  # closes but preserves trip count
        cb.record_failure()  # trip 2 → 120s
        assert cb._current_timeout == pytest.approx(120.0)

    def test_multiplier_1_gives_constant_timeout(self):
        """backoff_multiplier=1.0 (default) never changes recovery_timeout."""
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=60, backoff_multiplier=1.0
        )
        for _ in range(5):
            cb.record_failure()
            cb.record_success()
        cb.record_failure()
        assert cb._current_timeout == pytest.approx(60.0)


class TestCircuitBreakerBurstWindow:
    def test_parallel_failures_count_as_one_event(self):
        """3 simultaneous failures within burst_window must not count as 3 events.

        Regression for L5-C: 3 parallel model fetches all failing at once used to
        record 3 failure events, tripping a threshold=6 circuit after only 2 batches.
        With burst_window=5s each batch counts as 1 event.
        """
        cb = CircuitBreaker(
            "test", failure_threshold=6, recovery_timeout=1800, burst_window=5.0
        )
        # Simulate 3 parallel failures landing at the same instant (burst 1)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        # Only 1 event should have been counted
        assert cb.failure_count == 1
        assert not cb.is_open()

    def test_sequential_failures_outside_window_each_count(self):
        """Failures spaced further apart than burst_window each increment the counter."""
        cb = CircuitBreaker(
            "test", failure_threshold=3, recovery_timeout=1800, burst_window=0.01
        )
        cb.record_failure()
        time.sleep(0.05)  # outside the 10ms burst window
        cb.record_failure()
        time.sleep(0.05)
        cb.record_failure()
        # All 3 are independent events — circuit should be open
        assert cb.failure_count == 3
        assert cb.is_open()


def test_blend_uses_nws_clim_only_when_ensemble_circuit_open(monkeypatch):
    """When ensemble circuit is OPEN, blended_prob must use only nws+clim weights."""
    import weather_markets as wm

    # Force the circuit open
    monkeypatch.setattr(wm, "_ensemble_circuit_is_open", lambda: True)

    nws_prob = 0.70
    clim_prob = 0.60
    ens_prob = 0.10  # stale / wrong value from before the outage

    w_ens, w_nws, w_clim = 0.60, 0.35, 0.05  # normal above weights
    result = wm._blend_with_circuit_fallback(
        ens_prob, nws_prob, clim_prob, w_ens, w_nws, w_clim
    )

    # With ens excluded, renormalized: w_nws=0.35/0.40=0.875, w_clim=0.05/0.40=0.125
    expected = round(0.875 * nws_prob + 0.125 * clim_prob, 6)
    assert abs(result - expected) < 1e-4
