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

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
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

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
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

        placed_at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
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
        monkeypatch.setattr(
            "main.execution_log.get_recent_orders", lambda limit=50: fake_orders
        )

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_startup_orders()

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any(
            "KXTEST" in m or "recent order" in m.lower() for m in warning_msgs
        ), "recent order within 5 min must emit a WARNING"

    def test_old_order_no_warning(self, monkeypatch, caplog):
        """Orders older than 5 minutes must not trigger a warning."""
        main = _import_main()
        fake_orders = [self._recent_order(minutes_ago=10)]
        monkeypatch.setattr(
            "main.execution_log.get_recent_orders", lambda limit=50: fake_orders
        )

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_startup_orders()

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert not any("recent order" in m.lower() for m in warning_msgs), (
            "order older than 5 min must not emit a WARNING"
        )

    def test_no_orders_no_warning(self, monkeypatch, caplog):
        """Empty order list must not trigger any warning."""
        main = _import_main()
        monkeypatch.setattr("main.execution_log.get_recent_orders", lambda limit=50: [])

        with caplog.at_level(logging.WARNING, logger="main"):
            main._check_startup_orders()

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert not warning_msgs

    def test_get_recent_orders_failure_does_not_raise(self, monkeypatch):
        """If execution_log.get_recent_orders raises, _check_startup_orders must not propagate."""
        main = _import_main()
        monkeypatch.setattr(
            "main.execution_log.get_recent_orders",
            lambda limit=50: (_ for _ in ()).throw(RuntimeError("db locked")),
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
        assert new_pid == str(os.getpid()), (
            "lock file should contain current PID after override"
        )

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
        main = _import_main()
        monkeypatch.setattr(main, "_acquire_cron_lock", lambda: False)

        with pytest.raises(SystemExit) as exc_info:
            with caplog.at_level(logging.WARNING, logger="main"):
                # Pass a MagicMock as client; it should never be used
                main.cmd_cron(MagicMock())

        assert exc_info.value.code == 1, "exit code must be 1 when lock is denied"
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
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
            main,
            "_release_cron_lock",
            lambda: release_calls.append(1) or original_release(),
        )

        # Force cmd_cron to explode immediately after the lock-and-flag setup
        monkeypatch.setattr(
            main,
            "get_weather_markets",
            lambda c: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        # Stub other guards so we get past them
        monkeypatch.setattr(
            "paper.get_state_snapshot",
            lambda: {"balance": 0.0, "open_trades_count": 0, "peak_balance": 0.0},
        )
        # Isolate from real data/ files — kill switch and black swan checks
        monkeypatch.setattr(main, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr("alerts.run_black_swan_check", lambda: [])
        monkeypatch.setattr("alerts.run_anomaly_check", lambda log_results=False: None)

        with pytest.raises(SystemExit):
            main.cmd_cron(MagicMock())

        assert release_calls, (
            "_release_cron_lock must be called even when cmd_cron raises"
        )
