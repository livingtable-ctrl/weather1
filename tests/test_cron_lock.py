"""P0-5: _acquire_cron_lock must fail closed and use PID-aware stale detection."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch


def _acquire(monkeypatch, tmp_path):
    """Helper: point LOCK_PATH at tmp_path and call _acquire_cron_lock."""
    import main

    lock_path = tmp_path / ".cron_lock"
    monkeypatch.setattr(main, "LOCK_PATH", lock_path)
    import cron

    return cron._acquire_cron_lock(), lock_path


class TestAcquireCronLockFreshInstall:
    def test_acquires_when_no_lock_exists(self, tmp_path, monkeypatch):
        """No existing lock → returns True and writes lock file."""
        acquired, lock_path = _acquire(monkeypatch, tmp_path)
        assert acquired is True
        assert lock_path.exists()

    def test_lock_file_contains_pid_and_timestamps(self, tmp_path, monkeypatch):
        """Written lock must be valid JSON with pid, started_at, heartbeat."""
        acquired, lock_path = _acquire(monkeypatch, tmp_path)
        assert acquired is True
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()
        assert "started_at" in data
        assert "heartbeat" in data


class TestAcquireCronLockLivePid:
    def test_blocks_when_live_pid_holds_lock(self, tmp_path, monkeypatch):
        """Lock held by a live PID → returns False (fail closed)."""
        import main

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time(),
                    "heartbeat": time.time(),
                }
            )
        )

        import cron

        with (
            patch("cron._psutil") as mock_psutil,
            patch("cron._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.pid_exists.return_value = True
            result = cron._acquire_cron_lock()

        assert result is False

    def test_overrides_dead_pid_lock(self, tmp_path, monkeypatch):
        """Lock held by a dead PID → returns True and overwrites lock."""
        import main

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 99999999,
                    "started_at": time.time() - 100,
                    "heartbeat": time.time() - 100,
                }
            )
        )

        import cron

        with (
            patch("cron._psutil") as mock_psutil,
            patch("cron._PSUTIL_AVAILABLE", True),
        ):
            mock_psutil.pid_exists.return_value = False
            result = cron._acquire_cron_lock()

        assert result is True
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()


class TestAcquireCronLockNoPsutil:
    def test_blocks_when_lock_is_fresh_without_psutil(self, tmp_path, monkeypatch):
        """Without psutil, a lock < 1800s old must block."""
        import main

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 12345,
                    "started_at": time.time() - 60,
                    "heartbeat": time.time() - 60,
                }
            )
        )

        import cron

        with patch("cron._PSUTIL_AVAILABLE", False):
            result = cron._acquire_cron_lock()

        assert result is False

    def test_overrides_stale_lock_without_psutil(self, tmp_path, monkeypatch):
        """Without psutil, a lock > 1800s old must be overridden."""
        import main

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 12345,
                    "started_at": time.time() - 3600,
                    "heartbeat": time.time() - 3600,
                }
            )
        )

        import cron

        with patch("cron._PSUTIL_AVAILABLE", False):
            result = cron._acquire_cron_lock()

        assert result is True


class TestAcquireCronLockFailClosed:
    def test_fails_closed_on_corrupt_lock_file(self, tmp_path, monkeypatch):
        """Corrupt / unreadable lock → returns False, never True."""
        import main

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock_path)
        lock_path.write_text("not valid json {{{{")

        import cron

        result = cron._acquire_cron_lock()
        assert result is False

    def test_fails_closed_on_io_error(self, tmp_path, monkeypatch):
        """I/O error writing lock → returns False, never True (old code returned True)."""
        import main

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(main, "LOCK_PATH", lock_path)

        import cron

        with patch.object(
            lock_path.parent.__class__, "mkdir", side_effect=OSError("disk full")
        ):
            # Patch Path.write_text to raise
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = cron._acquire_cron_lock()

        assert result is False
