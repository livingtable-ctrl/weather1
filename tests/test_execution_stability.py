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
        import cron

        flag = tmp_path / ".cron_running"
        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", flag)

        cron._write_cron_running_flag()

        assert flag.exists(), "flag file should be created"
        content = flag.read_text().strip()
        # Must be a valid ISO datetime
        dt = datetime.fromisoformat(content)
        assert dt.tzinfo is not None, "timestamp must be timezone-aware"

    def test_flag_cleared_at_end(self, tmp_path, monkeypatch):
        """_clear_cron_running_flag() removes the flag file."""
        import cron

        flag = tmp_path / ".cron_running"
        flag.write_text("2026-04-14T00:00:00+00:00")
        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", flag)

        cron._clear_cron_running_flag()

        assert not flag.exists(), "flag file should be deleted"

    def test_stale_flag_no_warning(self, tmp_path, monkeypatch, caplog):
        """A flag older than 600 s must NOT trigger a warning."""
        import cron

        flag = tmp_path / ".cron_running"
        flag.write_text("2026-04-14T00:00:00+00:00")
        # Back-date mtime by 700 s
        stale_mtime = time.time() - 700
        os.utime(flag, (stale_mtime, stale_mtime))
        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", flag)

        with caplog.at_level(logging.WARNING, logger="main"):
            cron._write_cron_running_flag()

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert not any("may not have completed cleanly" in m for m in warning_msgs), (
            "stale flag (>600s) should not produce a warning"
        )

    def test_fresh_flag_triggers_warning(self, tmp_path, monkeypatch, caplog):
        """A flag younger than 600 s must trigger a WARNING."""
        import cron

        flag = tmp_path / ".cron_running"
        flag.write_text("2026-04-14T00:00:00+00:00")
        # mtime is implicitly 'now', so age ≈ 0 s
        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", flag)

        with caplog.at_level(logging.WARNING, logger="main"):
            cron._write_cron_running_flag()

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("may not have completed cleanly" in m for m in warning_msgs), (
            "fresh flag (<600s) must emit a WARNING"
        )

    def test_clear_missing_flag_is_noop(self, tmp_path, monkeypatch):
        """_clear_cron_running_flag() must not raise when flag does not exist."""
        import cron

        flag = tmp_path / ".cron_running"
        assert not flag.exists()
        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", flag)

        cron._clear_cron_running_flag()  # must not raise


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
            "cron.execution_log.get_recent_orders", lambda limit=50: fake_orders
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
            "cron.execution_log.get_recent_orders", lambda limit=50: fake_orders
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
        monkeypatch.setattr("cron.execution_log.get_recent_orders", lambda limit=50: [])

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
            "cron.execution_log.get_recent_orders",
            lambda limit=50: (_ for _ in ()).throw(RuntimeError("db locked")),
        )
        # Should not raise
        main._check_startup_orders()


# ===========================================================================
# Task 14 — File-based cron lock
# ===========================================================================


class TestCronLock:
    def test_lock_acquired_when_no_file(self, tmp_path, monkeypatch):
        """_acquire_cron_lock() returns True and writes JSON lock when none exists."""
        import json

        import cron

        main = _import_main()
        lock = tmp_path / ".cron.lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock)

        result = main._acquire_cron_lock()

        assert result is True, "lock should be acquired"
        assert lock.exists(), "lock file must be written"
        data = json.loads(lock.read_text())
        assert data["pid"] == os.getpid(), "lock file should contain the process PID"
        assert "started_at" in data
        assert "heartbeat" in data

    def test_lock_denied_when_fresh_file_exists(self, tmp_path, monkeypatch):
        """_acquire_cron_lock() returns False when a live PID holds the lock."""
        import json
        from unittest.mock import patch

        import cron

        main = _import_main()
        lock = tmp_path / ".cron.lock"
        lock.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time(),
                    "heartbeat": time.time(),
                }
            )
        )
        monkeypatch.setattr(cron, "LOCK_PATH", lock)

        with (
            patch("cron._psutil") as mock_psutil,
            patch("cron._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.pid_exists.return_value = True
            result = main._acquire_cron_lock()

        assert result is False, "live-PID lock must be denied"

    def test_stale_lock_overridden(self, tmp_path, monkeypatch):
        """_acquire_cron_lock() returns True when the locking PID is dead."""
        import json
        from unittest.mock import patch

        import cron

        main = _import_main()
        lock = tmp_path / ".cron.lock"
        lock.write_text(
            json.dumps(
                {
                    "pid": 99999999,
                    "started_at": time.time() - 700,
                    "heartbeat": time.time() - 700,
                }
            )
        )
        monkeypatch.setattr(cron, "LOCK_PATH", lock)

        with (
            patch("cron._psutil") as mock_psutil,
            patch("cron._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.pid_exists.return_value = False
            result = main._acquire_cron_lock()

        assert result is True, "dead-PID lock should be overridden"
        data = json.loads(lock.read_text())
        assert data["pid"] == os.getpid(), (
            "lock file should contain current PID after override"
        )

    def test_release_lock_removes_file(self, tmp_path, monkeypatch):
        """_release_cron_lock() deletes the lock file."""
        import cron

        main = _import_main()
        lock = tmp_path / ".cron.lock"
        lock.write_text(str(os.getpid()))
        monkeypatch.setattr(cron, "LOCK_PATH", lock)

        main._release_cron_lock()

        assert not lock.exists(), "lock file should be removed after release"

    def test_release_missing_lock_is_noop(self, tmp_path, monkeypatch):
        """_release_cron_lock() must not raise when lock file does not exist."""
        import cron

        main = _import_main()
        lock = tmp_path / ".cron.lock"
        assert not lock.exists()
        monkeypatch.setattr(cron, "LOCK_PATH", lock)

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
        import cron as _cron_mod

        monkeypatch.setattr(_cron_mod, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
        monkeypatch.setattr(_cron_mod, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr("alerts.run_black_swan_check", lambda: [])
        monkeypatch.setattr(
            "alerts.run_anomaly_check", lambda log_results=False: ([], False)
        )

        with pytest.raises(SystemExit):
            main.cmd_cron(MagicMock())

        assert release_calls, (
            "_release_cron_lock must be called even when cmd_cron raises"
        )


# ===========================================================================
# Task B7 — Overnight GFS Gap Protection
# ===========================================================================


class TestGfsUpdateWindow:
    def test_gfs_update_window_blocks_new_trades(self):
        """_in_gfs_update_window returns True within 90 min of GFS init, False otherwise."""
        from order_executor import _in_gfs_update_window

        # 00:30 UTC — within 90 min of 00Z → should be blocked
        t_blocked = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
        assert _in_gfs_update_window(now_utc=t_blocked) is True

        # 02:00 UTC — 90+ minutes after 00Z → clear
        t_clear = datetime(2026, 7, 1, 2, 0, tzinfo=UTC)
        assert _in_gfs_update_window(now_utc=t_clear) is False

        # 12:45 UTC — within 90 min of 12Z → blocked
        t_blocked2 = datetime(2026, 7, 1, 12, 45, tzinfo=UTC)
        assert _in_gfs_update_window(now_utc=t_blocked2) is True

    def test_gfs_update_all_four_init_hours(self):
        """GFS update windows should be True for all four initialization hours."""
        from order_executor import _in_gfs_update_window

        # Test 00Z, 06Z, 12Z, 18Z
        for init_hour in [0, 6, 12, 18]:
            t = datetime(2026, 7, 1, init_hour, 30, tzinfo=UTC)
            assert _in_gfs_update_window(now_utc=t) is True, (
                f"should be in window at {init_hour}:30"
            )

    def test_gfs_window_disabled_with_zero_lockout(self, monkeypatch):
        """When GFS_LOCKOUT_MINS=0, _in_gfs_update_window should always return False.

        Patches the derived module constant directly (matching this test
        suite's own dominant convention, e.g. test_live_execution.py's
        `monkeypatch.setattr(order_executor, "MIN_EDGE", ...)`) instead of
        reloading order_executor -- a prior version of this test did
        `importlib.reload(order_executor)` to pick up the env var, which
        rebinds every function in the module to a NEW function object.
        main.py imports _prediction_kwargs_from_analysis from order_executor
        once at process start; a reload anywhere later leaves main.py
        holding a stale reference that no longer `is` the live one,
        breaking tests/test_prediction_kwargs.py's identity check whenever
        this test happened to run first in the same session."""
        import order_executor
        from order_executor import _in_gfs_update_window

        monkeypatch.setattr(order_executor, "_GFS_UPDATE_LOCKOUT_MINS", 0)
        t_blocked = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
        assert _in_gfs_update_window(now_utc=t_blocked) is False

    def test_gfs_window_uses_current_time_when_none_provided(self):
        """_in_gfs_update_window should use datetime.now(UTC) when now_utc=None."""
        from order_executor import _in_gfs_update_window

        # Just verify it doesn't crash and returns a bool
        result = _in_gfs_update_window(now_utc=None)
        assert isinstance(result, bool)
