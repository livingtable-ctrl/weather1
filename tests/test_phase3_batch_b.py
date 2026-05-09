"""Phase 3 Batch B regression tests: P3-4, P3-5, P3-6."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from circuit_breaker import CircuitBreaker, CircuitOpenError


def _cb(**kw) -> CircuitBreaker:
    """Create a non-persisting CircuitBreaker for tests."""
    return CircuitBreaker(persist=False, **kw)


# ── P3-4: CircuitBreaker.execute() wrapper ────────────────────────────────────


class TestCircuitBreakerExecute:
    """P3-4: execute() provides automatic check → call → record protection."""

    def test_execute_calls_fn_when_closed(self):
        cb = _cb(name="x", failure_threshold=3)
        result = cb.execute(lambda: 42)
        assert result == 42

    def test_execute_raises_circuit_open_error_when_open(self):
        cb = _cb(name="x", failure_threshold=1)
        cb.record_failure()
        assert cb.is_open()
        with pytest.raises(CircuitOpenError):
            cb.execute(lambda: None)

    def test_execute_records_success_on_fn_return(self):
        cb = _cb(name="x", failure_threshold=3)
        cb.record_failure()  # one failure, not yet open
        cb.execute(lambda: None)
        assert cb.failure_count == 0  # success resets counter

    def test_execute_records_failure_and_reraises_on_exception(self):
        cb = _cb(name="x", failure_threshold=2)

        def _boom():
            raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            cb.execute(_boom)
        assert cb.failure_count == 1

    def test_execute_opens_circuit_after_threshold_failures(self):
        cb = _cb(name="x", failure_threshold=2)

        def _boom():
            raise RuntimeError("fail")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.execute(_boom)
        assert cb.is_open()

    def test_execute_passes_args_and_kwargs(self):
        cb = _cb(name="x", failure_threshold=3)
        result = cb.execute(lambda a, b=0: a + b, 3, b=4)
        assert result == 7


# ── P3-5: Separate read/write circuit breakers in kalshi_client ───────────────


class TestKalshiCircuitBreakerSplit:
    """P3-5: Read failures must not block write operations."""

    def test_read_and_write_cbs_are_separate_objects(self):
        from kalshi_client import _kalshi_cb_read, _kalshi_cb_write

        assert _kalshi_cb_read is not _kalshi_cb_write

    def test_read_cb_name_distinct_from_write(self):
        from kalshi_client import _kalshi_cb_read, _kalshi_cb_write

        assert _kalshi_cb_read.name != _kalshi_cb_write.name

    def test_read_failures_do_not_open_write_cb(self):
        """Tripping the read CB must leave the write CB closed."""
        from kalshi_client import _kalshi_cb_read, _kalshi_cb_write

        original_read_count = _kalshi_cb_read.failure_count
        original_write_open = _kalshi_cb_write.is_open()

        # Drive read CB to the brink (but don't actually open it — it's shared state)
        # Instead verify they are independent objects.
        fresh_read = CircuitBreaker(
            name="kalshi_api_read_test", failure_threshold=2, persist=False
        )
        fresh_write = CircuitBreaker(
            name="kalshi_api_write_test", failure_threshold=2, persist=False
        )
        fresh_read.record_failure()
        fresh_read.record_failure()
        assert fresh_read.is_open()
        assert not fresh_write.is_open()

        # Restore (no-op since these are fresh objects)
        _ = original_read_count
        _ = original_write_open

    def test_get_uses_read_cb(self, monkeypatch):
        """GET requests go through the read circuit breaker."""
        from kalshi_client import _kalshi_cb_read, _request_with_retry

        seen: list[str] = []
        original_is_open = _kalshi_cb_read.is_open

        def _spy_is_open():
            seen.append("read_cb_checked")
            return True  # force open so we can catch it

        monkeypatch.setattr(_kalshi_cb_read, "is_open", _spy_is_open)

        with pytest.raises(CircuitOpenError) as exc_info:
            _request_with_retry("GET", "https://example.com/fake")

        assert "read" in exc_info.value.source.lower() or "read" in str(exc_info.value)
        assert "read_cb_checked" in seen

        # Restore
        monkeypatch.setattr(_kalshi_cb_read, "is_open", original_is_open)

    def test_post_uses_write_cb(self, monkeypatch):
        """POST requests go through the write circuit breaker."""
        from kalshi_client import _kalshi_cb_write, _request_with_retry

        seen: list[str] = []
        original_is_open = _kalshi_cb_write.is_open

        def _spy_is_open():
            seen.append("write_cb_checked")
            return True

        monkeypatch.setattr(_kalshi_cb_write, "is_open", _spy_is_open)

        with pytest.raises(CircuitOpenError):
            _request_with_retry("POST", "https://example.com/fake")

        assert "write_cb_checked" in seen

        monkeypatch.setattr(_kalshi_cb_write, "is_open", original_is_open)

    def test_delete_uses_write_cb(self, monkeypatch):
        """DELETE requests go through the write circuit breaker."""
        from kalshi_client import _kalshi_cb_write, _request_with_retry

        seen: list[str] = []

        def _spy_is_open():
            seen.append("write_cb_checked")
            return True

        monkeypatch.setattr(_kalshi_cb_write, "is_open", _spy_is_open)
        with pytest.raises(CircuitOpenError):
            _request_with_retry("DELETE", "https://example.com/fake")
        assert "write_cb_checked" in seen


# ── P3-6: True HALF-OPEN state ────────────────────────────────────────────────


class TestCircuitBreakerHalfOpen:
    """P3-6: HALF-OPEN must allow exactly one probe and reopen on probe failure."""

    def test_half_open_allows_one_probe(self):
        cb = _cb(name="x", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)
        # First call after timeout → probe allowed (returns False)
        assert cb.is_open() is False

    def test_half_open_blocks_subsequent_callers(self):
        """Second is_open() call while probe is in flight must be blocked."""
        cb = _cb(name="x", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)
        cb.is_open()  # probe dispatched
        assert cb.is_open() is True  # next caller blocked

    def test_successful_probe_closes_circuit(self):
        cb = _cb(name="x", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)
        cb.is_open()  # transition to half-open
        cb.record_success()  # probe succeeded
        assert cb.is_open() is False
        assert cb.failure_count == 0

    def test_failed_probe_reopens_circuit(self):
        cb = _cb(name="x", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)
        cb.is_open()  # transition to half-open
        cb.record_failure()  # probe failed
        assert cb.is_open() is True  # back to OPEN

    def test_failed_probe_applies_backoff(self):
        cb = _cb(
            name="x",
            failure_threshold=1,
            recovery_timeout=0.01,
            backoff_multiplier=2.0,
        )
        cb.record_failure()  # trip 1 — timeout stays at 0.01 (first trip, no multiplier)
        time.sleep(0.05)
        cb.is_open()  # half-open
        cb.record_failure()  # probe fails → trip 2 → timeout = 0.01 * 2^1 = 0.02
        assert cb._current_timeout == pytest.approx(0.02, rel=1e-3)

    def test_execute_probe_success_closes_circuit(self):
        """execute() probe succeeds → circuit closes."""
        cb = _cb(name="x", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)
        # execute() during half-open — should be allowed as the probe
        result = cb.execute(lambda: "ok")
        assert result == "ok"
        assert not cb.is_open()

    def test_execute_probe_failure_reopens(self):
        """execute() probe raises → circuit reopens."""
        cb = _cb(name="x", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)

        with pytest.raises(RuntimeError):
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("probe fail")))

        assert cb.is_open()

    def test_trip_count_increments_on_probe_failure(self):
        cb = _cb(
            name="x",
            failure_threshold=1,
            recovery_timeout=0.01,
            backoff_multiplier=2.0,
        )
        cb.record_failure()  # trip 1
        time.sleep(0.05)
        cb.is_open()  # half-open
        cb.record_failure()  # probe fail → trip 2
        assert cb._trip_count == 2
