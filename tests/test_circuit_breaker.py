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
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.is_open()
        time.sleep(0.05)
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
