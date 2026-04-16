# P3: Execution Stability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate cron runs and detect abnormal execution gaps by adding three defence layers to `cmd_cron`: a graceful-shutdown flag that survives crashes, a startup double-execution detector that reads recent execution-log orders, and a process-level file lock that blocks concurrent cron instances.

**Architecture:** All three features are implemented as module-level helper functions in `main.py` with two module-level `Path` constants (`RUNNING_FLAG_PATH`, `LOCK_PATH`) so tests can redirect them via `monkeypatch.setattr`. `cmd_cron` calls them in a fixed sequence: acquire lock → write running flag → check startup orders → ... existing body ... → clear running flag → release lock (in `finally`). No new modules are added.

**Tech Stack:** Python 3.14, pytest, `monkeypatch`, `tmp_path`, `caplog` (stdlib `logging`). No psutil — stale detection uses `os.path.getmtime` / `time.time()`.

---

## Task 12 (P3.1) — Graceful shutdown flag

### 12.1 Add module-level constant

- [x] In `main.py`, near the other `Path(__file__).parent / "data" / ...` constants (around line 73), add:

```python
# P3.1 — graceful shutdown flag
RUNNING_FLAG_PATH: Path = Path(__file__).parent / "data" / ".cron_running"
```

### 12.2 Add helper functions

- [x] After the constant, add the two helpers:

```python
def _write_cron_running_flag() -> None:
    """Write UTC ISO timestamp to RUNNING_FLAG_PATH; warn if a fresh flag already exists."""
    import time as _time

    try:
        if RUNNING_FLAG_PATH.exists():
            age = _time.time() - RUNNING_FLAG_PATH.stat().st_mtime
            if age < 600:
                _log.warning(
                    "cmd_cron: previous cron run may not have completed cleanly "
                    "(flag age=%.0fs < 600s)", age
                )
        RUNNING_FLAG_PATH.parent.mkdir(exist_ok=True)
        RUNNING_FLAG_PATH.write_text(
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        )
    except Exception as _e:
        _log.warning("cmd_cron: could not write running flag: %s", _e)


def _clear_cron_running_flag() -> None:
    """Delete RUNNING_FLAG_PATH if it exists."""
    try:
        RUNNING_FLAG_PATH.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not clear running flag: %s", _e)
```

### 12.3 Wire into cmd_cron

- [x] In `cmd_cron`, immediately after the `import sys as _sys` line (line 1838), insert:

```python
    _write_cron_running_flag()
```

- [x] In `cmd_cron`, immediately before `_sys.exit(0)` (the very last line), insert:

```python
    _clear_cron_running_flag()
```

### 12.4 Write tests

- [x] Create `tests/test_execution_stability.py` with the content below.

```python
"""
Tests for P3: Execution Stability
  Task 12 (P3.1) — graceful shutdown flag
  Task 13 (P3.2) — startup double-execution detection
  Task 14 (P3.4) — file-based cron lock
"""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_main():
    import main
    return main


# ===========================================================================
# Task 12 — Graceful shutdown flag
# ===========================================================================

class TestWriteCronRunningFlag:
    def test_flag_written_at_start(self, tmp_path, monkeypatch):
        """_write_cron_running_flag() creates the flag file with a UTC ISO timestamp."""
        main = _import_main()
        flag = tmp_path / ".cron_running"
        monkeypatch.setattr(main, "RUNNING_FLAG_PATH", flag)

        main._write_cron_running_flag()

        assert flag.exists(), "flag file should be created"
        content = flag.read_text().strip()
        # Must be a valid ISO datetime
        dt = datetime.fromisoformat(content)
        assert dt.tzinfo is not None, "timestamp must be timezone-aware"

    def test_flag_cleared_at_end(self, tmp_path, monkeypatch):
        """_clear_cron_running_flag() removes the flag file."""
        main = _import_main()
        flag = tmp_path / ".cron_running"
        flag.write_text("2026-04-14T00:00:00+00:00")
        monkeypatch.setattr(main, "RUNNING_FLAG_PATH", flag)

        main._clear_cron_running_flag()

        assert not flag.exists(), "flag file should be deleted"

    def test_stale_flag_no_warning(self, tmp_path, monkeypatch, caplog):
        """A flag older than 600 s must NOT trigger a warning."""
        main = _import_main()
        flag = tmp_path / ".cron_running"
        flag.write_text("2026-04-14T00:00:00+00:00")
        # Back-date mtime by 700 s
        stale_mtime = time.time() - 700
        os.utime(flag, (stale_mtime, stale_mtime))
        monkeypatch.setattr(main, "RUNNING_FLAG_PATH", flag)

        with caplog.at_level(logging.WARNING, logger="main"):
            main._write_cron_running_flag()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("may not have completed cleanly" in m for m in warning_msgs), (
            "stale flag (>600s) should not produce a warning"
        )

    def test_fresh_flag_triggers_warning(self, tmp_path, monkeypatch, caplog):
        """A flag younger than 600 s must trigger a WARNING."""
        main = _import_main()
        flag = tmp_path / ".cron_running"
        flag.write_text("2026-04-14T00:00:00+00:00")
        # mtime is implicitly 'now', so age ≈ 0 s
        monkeypatch.setattr(main, "RUNNING_FLAG_PATH", flag)

        with caplog.at_level(logging.WARNING, logger="main"):
            main._write_cron_running_flag()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("may not have completed cleanly" in m for m in warning_msgs), (
            "fresh flag (<600s) must emit a WARNING"
        )

    def test_clear_missing_flag_is_noop(self, tmp_path, monkeypatch):
        """_clear_cron_running_flag() must not raise when flag does not exist."""
        main = _import_main()
        flag = tmp_path / ".cron_running"
        assert not flag.exists()
        monkeypatch.setattr(main, "RUNNING_FLAG_PATH", flag)

        main._clear_cron_running_flag()  # must not raise


# ===========================================================================
# Task 13 — Startup double-execution detection
# ===========================================================================

class TestCheckStartupOrders:
    def _recent_order(self, minutes_ago: float = 2.0) -> dict:
        """Return a fake order dict placed `minutes_ago` minutes in the past."""
        from datetime import timedelta
        placed_at = (
            datetime.now(UTC) - timedelta(minutes=minutes_ago)
        ).isoformat()
        return {
            "id": 1,
            "ticker": "KXTEST-26Apr14-T60",
            "side": "yes",
            "quantity": 1,
            "price": 0.55,
            "status": "filled",
            "placed_at": placed_at,
        }

    def test_recent_order_triggers_warning(self, monkeypatch, caplog):
        """If an order was placed within the last 5 minutes, _check_startup_orders must WARNING."""
        main = _import_main()
        fake_orders = [self._recent_order(minutes_ago=2)]
        monkeypatch.setattr("main.execution_log.get_recent_orders", lambda limit=50: fake_orders)

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_startup_orders()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("KXTEST" in m or "recent order" in m.lower() for m in warning_msgs), (
            "recent order within 5 min must emit a WARNING"
        )

    def test_old_order_no_warning(self, monkeypatch, caplog):
        """Orders older than 5 minutes must not trigger a warning."""
        main = _import_main()
        fake_orders = [self._recent_order(minutes_ago=10)]
        monkeypatch.setattr("main.execution_log.get_recent_orders", lambda limit=50: fake_orders)

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_startup_orders()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("recent order" in m.lower() for m in warning_msgs), (
            "order older than 5 min must not emit a WARNING"
        )

    def test_no_orders_no_warning(self, monkeypatch, caplog):
        """Empty order list must not trigger any warning."""
        main = _import_main()
        monkeypatch.setattr("main.execution_log.get_recent_orders", lambda limit=50: [])

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_startup_orders()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert not warning_msgs

    def test_get_recent_orders_failure_does_not_raise(self, monkeypatch):
        """If execution_log.get_recent_orders raises, _check_startup_orders must not propagate."""
        main = _import_main()
        monkeypatch.setattr(
            "main.execution_log.get_recent_orders",
            lambda limit=50: (_ for _ in ()).throw(RuntimeError("db locked"))
        )
        # Should not raise
        main._check_startup_orders()


# ===========================================================================
# Task 14 — File-based cron lock
# ===========================================================================

class TestCronLock:
    def test_lock_acquired_when_no_file(self, tmp_path, monkeypatch):
        """_acquire_cron_lock() returns True and writes the lock file when none exists."""
        main = _import_main()
        lock = tmp_path / ".cron.lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock)

        result = main._acquire_cron_lock()

        assert result is True, "lock should be acquired"
        assert lock.exists(), "lock file must be written"
        pid_text = lock.read_text().strip()
        assert pid_text.isdigit(), "lock file should contain the process PID"

    def test_lock_denied_when_fresh_file_exists(self, tmp_path, monkeypatch):
        """_acquire_cron_lock() returns False when lock file is <600 s old."""
        main = _import_main()
        lock = tmp_path / ".cron.lock"
        lock.write_text("99999")  # mtime ≈ now, age ≈ 0 s
        monkeypatch.setattr(main, "LOCK_PATH", lock)

        result = main._acquire_cron_lock()

        assert result is False, "fresh lock must be denied"

    def test_stale_lock_overridden(self, tmp_path, monkeypatch):
        """_acquire_cron_lock() returns True and overwrites a lock file older than 600 s."""
        main = _import_main()
        lock = tmp_path / ".cron.lock"
        lock.write_text("99999")
        stale_mtime = time.time() - 700
        os.utime(lock, (stale_mtime, stale_mtime))
        monkeypatch.setattr(main, "LOCK_PATH", lock)

        result = main._acquire_cron_lock()

        assert result is True, "stale lock (>600s) should be overridden"
        new_pid = lock.read_text().strip()
        assert new_pid == str(os.getpid()), "lock file should contain current PID after override"

    def test_release_lock_removes_file(self, tmp_path, monkeypatch):
        """_release_cron_lock() deletes the lock file."""
        main = _import_main()
        lock = tmp_path / ".cron.lock"
        lock.write_text(str(os.getpid()))
        monkeypatch.setattr(main, "LOCK_PATH", lock)

        main._release_cron_lock()

        assert not lock.exists(), "lock file should be removed after release"

    def test_release_missing_lock_is_noop(self, tmp_path, monkeypatch):
        """_release_cron_lock() must not raise when lock file does not exist."""
        main = _import_main()
        lock = tmp_path / ".cron.lock"
        assert not lock.exists()
        monkeypatch.setattr(main, "LOCK_PATH", lock)

        main._release_cron_lock()  # must not raise

    def test_cmd_cron_exits_early_when_lock_denied(self, tmp_path, monkeypatch, caplog):
        """cmd_cron must call sys.exit(1) when _acquire_cron_lock() returns False."""
        import sys

        main = _import_main()
        monkeypatch.setattr(main, "_acquire_cron_lock", lambda: False)

        with pytest.raises(SystemExit) as exc_info:
            with caplog.at_level(logging.WARNING, logger="main"):
                # Pass a MagicMock as client; it should never be used
                main.cmd_cron(MagicMock())

        assert exc_info.value.code == 1, "exit code must be 1 when lock is denied"
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("lock" in m.lower() for m in warning_msgs), (
            "a WARNING about the lock must be logged before exit"
        )

    def test_lock_released_in_finally(self, tmp_path, monkeypatch):
        """_release_cron_lock() is called even when cmd_cron raises mid-run."""
        main = _import_main()
        lock = tmp_path / ".cron.lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock)

        release_calls: list[int] = []
        monkeypatch.setattr(main, "_acquire_cron_lock", lambda: True)
        monkeypatch.setattr(main, "_write_cron_running_flag", lambda: None)
        monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
        monkeypatch.setattr(main, "_clear_cron_running_flag", lambda: None)
        original_release = main._release_cron_lock
        monkeypatch.setattr(
            main, "_release_cron_lock",
            lambda: release_calls.append(1) or original_release()
        )

        # Force cmd_cron to explode immediately after the lock-and-flag setup
        monkeypatch.setattr(main, "get_weather_markets", lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
        # Stub other guards so we get past them
        monkeypatch.setattr("paper.get_state_snapshot", lambda: {"balance": 0.0, "open_trades_count": 0, "peak_balance": 0.0})

        with pytest.raises(SystemExit):
            main.cmd_cron(MagicMock())

        assert release_calls, "_release_cron_lock must be called even when cmd_cron raises"
```

### 12.5 Verify Task 12

- [x] Run:

```
cd "C:\Users\thesa\claude kalshi"
python -m pytest tests/test_execution_stability.py::TestWriteCronRunningFlag -v
```

Expected output (all green):

```
PASSED tests/test_execution_stability.py::TestWriteCronRunningFlag::test_flag_written_at_start
PASSED tests/test_execution_stability.py::TestWriteCronRunningFlag::test_flag_cleared_at_end
PASSED tests/test_execution_stability.py::TestWriteCronRunningFlag::test_stale_flag_no_warning
PASSED tests/test_execution_stability.py::TestWriteCronRunningFlag::test_fresh_flag_triggers_warning
PASSED tests/test_execution_stability.py::TestWriteCronRunningFlag::test_clear_missing_flag_is_noop
5 passed
```

### 12.6 Commit Task 12

```
git add main.py tests/test_execution_stability.py
git commit -m "feat(p3.1): add graceful shutdown flag to cmd_cron"
```

---

## Task 13 (P3.2) — Startup double-execution detection

### 13.1 Add module-level constant (none required — uses execution_log directly)

### 13.2 Add `_check_startup_orders()` helper

- [x] In `main.py`, after `_clear_cron_running_flag`, add:

```python
def _check_startup_orders() -> None:
    """Warn if any orders were placed in the last 5 minutes (double-execution guard)."""
    import time as _time

    try:
        recent = execution_log.get_recent_orders(limit=50)
        cutoff = _time.time() - 300  # 5 minutes
        for order in recent:
            placed_at_str = order.get("placed_at", "")
            if not placed_at_str:
                continue
            try:
                from datetime import datetime as _dt, timezone as _tz
                placed_ts = _dt.fromisoformat(placed_at_str).timestamp()
            except ValueError:
                continue
            if placed_ts >= cutoff:
                _log.warning(
                    "cmd_cron: recent order detected at startup — "
                    "possible double-execution (ticker=%s side=%s placed_at=%s)",
                    order.get("ticker", "?"),
                    order.get("side", "?"),
                    placed_at_str,
                )
    except Exception as _e:
        _log.warning("cmd_cron: _check_startup_orders failed: %s", _e)
```

### 13.3 Wire into cmd_cron

- [x] In `cmd_cron`, immediately after the `_write_cron_running_flag()` call (added in Task 12), insert:

```python
    _check_startup_orders()
```

### 13.4 Verify Task 13

- [x] Run:

```
cd "C:\Users\thesa\claude kalshi"
python -m pytest tests/test_execution_stability.py::TestCheckStartupOrders -v
```

Expected output:

```
PASSED tests/test_execution_stability.py::TestCheckStartupOrders::test_recent_order_triggers_warning
PASSED tests/test_execution_stability.py::TestCheckStartupOrders::test_old_order_no_warning
PASSED tests/test_execution_stability.py::TestCheckStartupOrders::test_no_orders_no_warning
PASSED tests/test_execution_stability.py::TestCheckStartupOrders::test_get_recent_orders_failure_does_not_raise
4 passed
```

### 13.5 Commit Task 13

```
git add main.py tests/test_execution_stability.py
git commit -m "feat(p3.2): add startup double-execution detection to cmd_cron"
```

---

## Task 14 (P3.4) — File-based cron lock

### 14.1 Add module-level constant

- [x] In `main.py`, next to `RUNNING_FLAG_PATH`, add:

```python
# P3.4 — file-based cron lock (prevents concurrent cron instances)
LOCK_PATH: Path = Path(__file__).parent / "data" / ".cron.lock"
```

### 14.2 Add `_acquire_cron_lock()` and `_release_cron_lock()`

- [x] In `main.py`, after `_check_startup_orders`, add:

```python
def _acquire_cron_lock() -> bool:
    """
    Try to acquire the cron file lock.

    Returns True if the lock was acquired (caller may proceed).
    Returns False if a fresh lock file exists (another instance is running).
    A stale lock (>600 s) is overridden and True is returned.
    """
    import os as _os
    import time as _time

    try:
        if LOCK_PATH.exists():
            age = _time.time() - LOCK_PATH.stat().st_mtime
            if age < 600:
                _log.warning(
                    "cmd_cron: lock file exists and is fresh (age=%.0fs) — "
                    "another instance may be running; skipping this run",
                    age,
                )
                return False
            # Stale — fall through to overwrite
            _log.warning(
                "cmd_cron: overriding stale lock file (age=%.0fs)", age
            )
        LOCK_PATH.parent.mkdir(exist_ok=True)
        LOCK_PATH.write_text(str(_os.getpid()))
        return True
    except Exception as _e:
        _log.warning("cmd_cron: could not acquire lock: %s — proceeding anyway", _e)
        return True  # fail-open: don't block cron on unexpected I/O errors


def _release_cron_lock() -> None:
    """Delete the cron lock file."""
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not release lock: %s", _e)
```

### 14.3 Wire into cmd_cron

The call order inside `cmd_cron` must be:

1. Acquire lock (exit 1 if denied)
2. Write running flag
3. Check startup orders
4. ... existing body ...
5. Clear running flag (before sys.exit)
6. Release lock (in `finally`)

- [x] Replace the top of `cmd_cron` so it reads:

```python
def cmd_cron(client: KalshiClient, min_edge: float = MIN_EDGE) -> None:
    """Silent background scan — writes to data/cron.log, auto-places strong paper trades."""
    import sys as _sys

    # P3.4 — acquire file lock; exit immediately if another instance is running
    if not _acquire_cron_lock():
        _sys.exit(1)

    try:
        # P3.1 — graceful shutdown flag
        _write_cron_running_flag()
        # P3.2 — detect orders placed in the last 5 minutes at startup
        _check_startup_orders()

        log_path = Path(__file__).parent / "data" / "cron.log"
        log_path.parent.mkdir(exist_ok=True)
        # ... rest of existing body unchanged ...
```

- [x] Wrap the tail of `cmd_cron` in a `finally` block that calls `_release_cron_lock()`. The final lines should look like:

```python
        _clear_cron_running_flag()
        _sys.exit(0)
    finally:
        _release_cron_lock()
```

Note: `sys.exit(0)` raises `SystemExit`, which is caught by `finally` — the lock will still be released.

### 14.4 Verify Task 14

- [x] Run:

```
cd "C:\Users\thesa\claude kalshi"
python -m pytest tests/test_execution_stability.py::TestCronLock -v
```

Expected output:

```
PASSED tests/test_execution_stability.py::TestCronLock::test_lock_acquired_when_no_file
PASSED tests/test_execution_stability.py::TestCronLock::test_lock_denied_when_fresh_file_exists
PASSED tests/test_execution_stability.py::TestCronLock::test_stale_lock_overridden
PASSED tests/test_execution_stability.py::TestCronLock::test_release_lock_removes_file
PASSED tests/test_execution_stability.py::TestCronLock::test_release_missing_lock_is_noop
PASSED tests/test_execution_stability.py::TestCronLock::test_cmd_cron_exits_early_when_lock_denied
PASSED tests/test_execution_stability.py::TestCronLock::test_lock_released_in_finally
7 passed
```

### 14.5 Run full test file

- [x] Run:

```
cd "C:\Users\thesa\claude kalshi"
python -m pytest tests/test_execution_stability.py -v
```

Expected: 16 passed, 0 failed, 0 errors.

### 14.6 Run full test suite (regression check)

- [x] Run:

```
cd "C:\Users\thesa\claude kalshi"
python -m pytest --tb=short -q
```

Expected: all pre-existing tests still pass; no new failures.

### 14.7 Commit Task 14

```
git add main.py tests/test_execution_stability.py
git commit -m "feat(p3.4): add file-based cron lock to prevent concurrent cron instances"
```

---

## Summary of changes (Tasks 12–14)

| File | What changes |
|------|-------------|
| `main.py` | +2 module-level Path constants (`RUNNING_FLAG_PATH`, `LOCK_PATH`); +4 helpers (`_write_cron_running_flag`, `_clear_cron_running_flag`, `_check_startup_orders`, `_acquire_cron_lock`, `_release_cron_lock`); `cmd_cron` body wrapped in lock/flag calls |
| `tests/test_execution_stability.py` | New file — 16 tests across 3 test classes |

No new dependencies. No schema migrations. No changes to `execution_log.py`.

---

## Task 44 (P3.2) — API Retry Logic with Exponential Backoff

- [ ] **Add** `_api_call_with_retry(fn, *args, max_retries=3, base_delay=1.0, **kwargs)` to `kalshi_client.py`.
- [ ] **Wrap** `get_markets()` and `get_market_order_book()` calls inside `_api_call_with_retry`.
- [ ] **Append** tests to `tests/test_execution_stability.py`.
- [ ] **Verify** by running the Task 44 tests.
- [ ] **Commit** with message `feat(p3.2): add exponential backoff retry for Kalshi API calls`.

### What is being added

Transient Kalshi API errors (HTTP 429 rate-limit, 503 unavailable) currently propagate and abort the cron run. `_api_call_with_retry` retries up to `max_retries` times with exponential backoff (`base_delay * 2^attempt`), re-raising only after all retries are exhausted.

### Production code — kalshi_client.py

```python
# kalshi_client.py — add near top of file (after imports)

import time as _time

_RETRYABLE_STATUS_CODES = {429, 503}


def _api_call_with_retry(fn, *args, max_retries: int = 3,
                         base_delay: float = 1.0, **kwargs):
    """
    Call *fn(*args, **kwargs)* with exponential backoff retry.

    Retries on HTTP errors with status codes in _RETRYABLE_STATUS_CODES.
    Raises the last exception after *max_retries* failed attempts.

    Args:
        fn: callable — the API function to invoke.
        *args: positional arguments forwarded to fn.
        max_retries: int — maximum number of retry attempts (default 3).
        base_delay: float — base sleep duration in seconds; doubles each attempt.
        **kwargs: keyword arguments forwarded to fn.

    Returns:
        Whatever fn returns on success.

    Raises:
        The last exception raised by fn after all retries are exhausted.
    """
    import logging as _logging
    _rlog = _logging.getLogger(__name__)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            # Check if retryable (status code attribute varies by HTTP lib)
            status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            is_retryable = (status in _RETRYABLE_STATUS_CODES) if status else True
            last_exc = exc
            if attempt < max_retries and is_retryable:
                delay = base_delay * (2 ** attempt)
                _rlog.warning(
                    "API call %s failed (attempt %d/%d, status=%s): %s — retrying in %.1fs",
                    getattr(fn, "__name__", str(fn)),
                    attempt + 1, max_retries + 1,
                    status, exc, delay,
                )
                _time.sleep(delay)
            else:
                break
    raise last_exc
```

### Test code — Task 44

```python
# ── Task 44 (P3.2): API retry logic ──────────────────────────────────────────

class TestApiCallWithRetry:
    """_api_call_with_retry retries on transient errors and raises after exhaustion."""

    def test_success_on_first_call_no_retry(self):
        from kalshi_client import _api_call_with_retry
        calls = []

        def _fn():
            calls.append(1)
            return "ok"

        result = _api_call_with_retry(_fn, max_retries=3, base_delay=0)
        assert result == "ok"
        assert len(calls) == 1, "Should succeed on first attempt with no retries"

    def test_retries_on_failure_then_succeeds(self):
        from kalshi_client import _api_call_with_retry
        attempts = []

        def _fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("transient")
            return "recovered"

        result = _api_call_with_retry(_fn, max_retries=3, base_delay=0)
        assert result == "recovered"
        assert len(attempts) == 3

    def test_raises_after_max_retries_exhausted(self):
        from kalshi_client import _api_call_with_retry
        import pytest

        def _fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            _api_call_with_retry(_fn, max_retries=2, base_delay=0)

    def test_call_count_equals_max_retries_plus_one(self):
        from kalshi_client import _api_call_with_retry
        import pytest

        calls = []

        def _fn():
            calls.append(1)
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            _api_call_with_retry(_fn, max_retries=2, base_delay=0)

        assert len(calls) == 3, "Should call fn max_retries+1 times total"
```

### Run command — Task 44

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_execution_stability.py::TestApiCallWithRetry -v
```

### Expected output — Task 44

```
tests/test_execution_stability.py::TestApiCallWithRetry::test_success_on_first_call_no_retry PASSED
tests/test_execution_stability.py::TestApiCallWithRetry::test_retries_on_failure_then_succeeds PASSED
tests/test_execution_stability.py::TestApiCallWithRetry::test_raises_after_max_retries_exhausted PASSED
tests/test_execution_stability.py::TestApiCallWithRetry::test_call_count_equals_max_retries_plus_one PASSED
4 passed in 0.XXs
```

---

## Task 45 (P3.3) — System Health Monitoring

- [ ] **Add** `get_system_health()` to `utils.py` using `psutil`.
- [ ] **Add** startup health check in `cmd_cron` after `_check_startup_orders()`.
- [ ] **Append** tests to `tests/test_execution_stability.py`.
- [ ] **Verify** by running the Task 45 tests.
- [ ] **Commit** with message `feat(p3.3): add CPU/memory system health monitoring to cmd_cron`.

### What is being added

If the host machine is under extreme resource pressure (CPU > 90%, memory > 90%), trading decisions may be delayed or produce stale data. `get_system_health()` snapshots CPU, memory, and disk usage; `cmd_cron` logs a WARNING but does not halt (non-blocking check).

### Production code — utils.py

```python
# utils.py — add near bottom

def get_system_health(
    cpu_threshold: float = 90.0,
    mem_threshold: float = 90.0,
) -> dict:
    """
    Return a snapshot of system resource utilisation.

    Uses psutil if available; returns a degraded dict with healthy=None if psutil
    is not installed (graceful degradation — never raises).

    Returns:
        dict with keys:
            cpu_pct (float | None): CPU usage 0-100.
            mem_pct (float | None): Memory usage 0-100.
            disk_pct (float | None): Root-partition disk usage 0-100.
            healthy (bool | None): True if all metrics are below their thresholds.
            error (str | None): Set when psutil is unavailable or raises.
    """
    try:
        import psutil  # type: ignore[import]
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        healthy = cpu < cpu_threshold and mem < mem_threshold
        return {
            "cpu_pct": cpu,
            "mem_pct": mem,
            "disk_pct": disk,
            "healthy": healthy,
            "error": None,
        }
    except ImportError:
        return {"cpu_pct": None, "mem_pct": None, "disk_pct": None,
                "healthy": None, "error": "psutil not installed"}
    except Exception as exc:
        return {"cpu_pct": None, "mem_pct": None, "disk_pct": None,
                "healthy": None, "error": str(exc)}
```

### Wiring in `cmd_cron` (main.py)

After `_check_startup_orders()`, add:

```python
# P3.3 — system health check
from utils import get_system_health as _get_system_health
_health = _get_system_health()
if _health.get("healthy") is False:
    _log.warning(
        "cmd_cron: system resources elevated — cpu=%.1f%% mem=%.1f%% — proceeding with caution",
        _health.get("cpu_pct", 0.0),
        _health.get("mem_pct", 0.0),
    )
```

### Test code — Task 45

```python
# ── Task 45 (P3.3): System health monitoring ─────────────────────────────────

class TestSystemHealthMonitoring:
    """get_system_health returns a well-formed dict and never raises."""

    def test_returns_required_keys(self, monkeypatch):
        import types
        from utils import get_system_health

        # Stub psutil so the test doesn't require the real library
        fake_psutil = types.SimpleNamespace(
            cpu_percent=lambda interval=None: 30.0,
            virtual_memory=lambda: types.SimpleNamespace(percent=50.0),
            disk_usage=lambda path: types.SimpleNamespace(percent=40.0),
        )
        monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

        result = get_system_health()
        for key in ("cpu_pct", "mem_pct", "disk_pct", "healthy", "error"):
            assert key in result, f"Missing key: {key}"

    def test_healthy_true_when_below_thresholds(self, monkeypatch):
        import types
        from utils import get_system_health

        fake_psutil = types.SimpleNamespace(
            cpu_percent=lambda interval=None: 20.0,
            virtual_memory=lambda: types.SimpleNamespace(percent=40.0),
            disk_usage=lambda path: types.SimpleNamespace(percent=30.0),
        )
        monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

        result = get_system_health(cpu_threshold=90.0, mem_threshold=90.0)
        assert result["healthy"] is True
        assert result["error"] is None

    def test_healthy_false_when_cpu_above_threshold(self, monkeypatch):
        import types
        from utils import get_system_health

        fake_psutil = types.SimpleNamespace(
            cpu_percent=lambda interval=None: 95.0,
            virtual_memory=lambda: types.SimpleNamespace(percent=40.0),
            disk_usage=lambda path: types.SimpleNamespace(percent=30.0),
        )
        monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

        result = get_system_health(cpu_threshold=90.0)
        assert result["healthy"] is False

    def test_graceful_when_psutil_missing(self, monkeypatch):
        from utils import get_system_health
        monkeypatch.setitem(__import__("sys").modules, "psutil", None)

        # Should not raise
        result = get_system_health()
        assert result["healthy"] is None
        assert result["error"] is not None
```

### Run command — Task 45

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_execution_stability.py::TestSystemHealthMonitoring -v
```

### Expected output — Task 45

```
tests/test_execution_stability.py::TestSystemHealthMonitoring::test_returns_required_keys PASSED
tests/test_execution_stability.py::TestSystemHealthMonitoring::test_healthy_true_when_below_thresholds PASSED
tests/test_execution_stability.py::TestSystemHealthMonitoring::test_healthy_false_when_cpu_above_threshold PASSED
tests/test_execution_stability.py::TestSystemHealthMonitoring::test_graceful_when_psutil_missing PASSED
4 passed in 0.XXs
```

---

## Task 46 (P3.5) — Queue Management / Backlog Overflow Prevention

- [ ] **Add** `MAX_OPPORTUNITIES_PER_RUN` env-var constant to `main.py`.
- [ ] **Add** `_truncate_opportunity_queue(opps, cap)` helper to `main.py`.
- [ ] **Apply** truncation at the start of `_auto_place_trades`.
- [ ] **Append** tests to `tests/test_execution_stability.py`.
- [ ] **Verify** by running the Task 46 tests.
- [ ] **Commit** with message `feat(p3.5): add opportunity queue cap to prevent backlog overflow`.

### What is being added

If weather markets produce a large backlog of opportunities (e.g., after a missed cron run), `_auto_place_trades` could attempt to process hundreds of candidates in a single run, burning the entire daily spend budget on a single cron cycle. `MAX_OPPORTUNITIES_PER_RUN` caps the queue; truncation is logged so operators can see when it occurs.

### Production code — main.py

```python
# main.py — add near other env-var constants

MAX_OPPORTUNITIES_PER_RUN: int = int(os.getenv("MAX_OPPORTUNITIES_PER_RUN", "20"))


def _truncate_opportunity_queue(
    opps: list[dict], cap: int = MAX_OPPORTUNITIES_PER_RUN
) -> list[dict]:
    """
    Return at most *cap* opportunities from *opps* (already ranked best-first).

    If truncation occurs, logs a WARNING with the dropped count so operators
    can detect backlog overflow and tune the cap or cron frequency.

    Args:
        opps: ranked list of opportunity dicts (best first).
        cap: maximum number to retain.

    Returns:
        The first *cap* items of *opps* (or all items if len <= cap).
    """
    if len(opps) <= cap:
        return opps
    dropped = len(opps) - cap
    _log.warning(
        "P3.5 queue overflow: %d opportunities received, capping at %d "
        "(dropping %d lowest-ranked); increase MAX_OPPORTUNITIES_PER_RUN if needed",
        len(opps), cap, dropped,
    )
    return opps[:cap]
```

### Wiring in `_auto_place_trades` (main.py)

At the very top of the `_auto_place_trades` function body, after the guard checks and before the per-opportunity loop:

```python
# P3.5 — cap opportunity queue to prevent backlog overflow
opportunities = _truncate_opportunity_queue(opportunities)
```

### Test code — Task 46

```python
# ── Task 46 (P3.5): Queue management ─────────────────────────────────────────

class TestOpportunityQueueCap:
    """_truncate_opportunity_queue enforces MAX_OPPORTUNITIES_PER_RUN."""

    def _make_opps(self, n: int) -> list[dict]:
        return [{"ticker": f"KXTEST-{i}", "net_edge": 0.10} for i in range(n)]

    def test_no_truncation_when_under_cap(self):
        from main import _truncate_opportunity_queue
        opps = self._make_opps(5)
        result = _truncate_opportunity_queue(opps, cap=20)
        assert result == opps
        assert len(result) == 5

    def test_truncates_to_cap(self):
        from main import _truncate_opportunity_queue
        opps = self._make_opps(30)
        result = _truncate_opportunity_queue(opps, cap=20)
        assert len(result) == 20

    def test_preserves_order_keeps_first_n(self):
        from main import _truncate_opportunity_queue
        opps = self._make_opps(10)
        result = _truncate_opportunity_queue(opps, cap=3)
        assert result == opps[:3], "Should keep the first (highest-ranked) items"

    def test_logs_warning_on_overflow(self, caplog):
        import logging
        from main import _truncate_opportunity_queue

        opps = self._make_opps(25)
        with caplog.at_level(logging.WARNING, logger="main"):
            _truncate_opportunity_queue(opps, cap=20)

        assert any("queue overflow" in r.message.lower() for r in caplog.records), \
            "Should log a WARNING when truncation occurs"

    def test_no_warning_at_exact_cap(self, caplog):
        import logging
        from main import _truncate_opportunity_queue

        opps = self._make_opps(20)
        with caplog.at_level(logging.WARNING, logger="main"):
            _truncate_opportunity_queue(opps, cap=20)

        assert not any("queue overflow" in r.message.lower() for r in caplog.records), \
            "Should NOT log WARNING when count equals cap exactly"

    def test_empty_list_returns_empty(self):
        from main import _truncate_opportunity_queue
        assert _truncate_opportunity_queue([], cap=20) == []
```

### Run command — Task 46

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_execution_stability.py::TestOpportunityQueueCap -v
```

### Expected output — Task 46

```
tests/test_execution_stability.py::TestOpportunityQueueCap::test_no_truncation_when_under_cap PASSED
tests/test_execution_stability.py::TestOpportunityQueueCap::test_truncates_to_cap PASSED
tests/test_execution_stability.py::TestOpportunityQueueCap::test_preserves_order_keeps_first_n PASSED
tests/test_execution_stability.py::TestOpportunityQueueCap::test_logs_warning_on_overflow PASSED
tests/test_execution_stability.py::TestOpportunityQueueCap::test_no_warning_at_exact_cap PASSED
tests/test_execution_stability.py::TestOpportunityQueueCap::test_empty_list_returns_empty PASSED
6 passed in 0.XXs
```

---

## Full test suite (Tasks 12–14 + 44–46)

```
cd "C:\Users\thesa\claude kalshi" && python -m pytest tests/test_execution_stability.py -v
```

Expected: **30 passed**, 0 failed, 0 errors.

---

## Updated summary of changes

| File | What changes |
|------|-------------|
| `main.py` | +2 Path constants (`RUNNING_FLAG_PATH`, `LOCK_PATH`); +1 int constant (`MAX_OPPORTUNITIES_PER_RUN`); +6 helpers (`_write_cron_running_flag`, `_clear_cron_running_flag`, `_check_startup_orders`, `_acquire_cron_lock`, `_release_cron_lock`, `_truncate_opportunity_queue`); `cmd_cron` wrapped in lock/flag/health calls; `_auto_place_trades` queue-capped |
| `kalshi_client.py` | +1 constant (`_RETRYABLE_STATUS_CODES`); +1 helper (`_api_call_with_retry`); wrapped on `get_markets` / `get_market_order_book` |
| `utils.py` | +1 function (`get_system_health`) using psutil with graceful fallback |
| `tests/test_execution_stability.py` | +20 tests across 3 new classes (`TestApiCallWithRetry`, `TestSystemHealthMonitoring`, `TestOpportunityQueueCap`) |

No schema migrations. `psutil` added as an optional dependency (graceful fallback when absent).
