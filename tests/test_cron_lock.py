"""P0-5: _acquire_cron_lock must fail closed and use PID-aware stale detection."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time
from unittest.mock import patch

import pytest


def _acquire(monkeypatch, tmp_path):
    """Helper: point LOCK_PATH at tmp_path and call _acquire_cron_lock."""
    import cron

    lock_path = tmp_path / ".cron_lock"
    monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
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
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
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
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
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
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
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
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
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
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text("not valid json {{{{")

        import cron

        result = cron._acquire_cron_lock()
        assert result is False

    def test_fails_closed_on_io_error(self, tmp_path, monkeypatch):
        """I/O error writing lock → returns False, never True (old code returned True)."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)

        with patch.object(
            lock_path.parent.__class__, "mkdir", side_effect=OSError("disk full")
        ):
            # Patch Path.write_text to raise
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = cron._acquire_cron_lock()

        assert result is False


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="the mutex closing this race uses msvcrt (Windows-only)",
)
class TestAcquireCronLockClosesRace:
    """AUD-0006 regression: _acquire_cron_lock's check-then-write sequence
    had no OS-level mutual exclusion -- two callers racing when no lock
    exists (or both independently judging a stale lock overridable) could
    both observe the same pre-write state and both return True. Reproduces
    the audit's own repro technique (audit/reproductions/
    cron_lock_race_repro.py): a Barrier inside a patched Path.exists forces
    both threads to the exact check-then-act instant the bug needed."""

    def test_concurrent_acquisition_has_exactly_one_winner(self, tmp_path, monkeypatch):
        """Mutation-tested: reverting the mutex wrap in cron._acquire_cron_lock
        (removing the CrossProcessLock acquire/release around the check+write
        body) makes this fail with results.count(True) == 2 -- against the
        fix, the second thread can't even reach Path.exists() while the
        first is still inside the critical section, so the barrier's own
        timeout (not a real 2-arrival rendezvous) is what lets it proceed,
        and it then correctly sees the first thread's freshly-written,
        still-live-PID lock and returns False."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)

        barrier = threading.Barrier(2, timeout=2.0)
        _orig_exists = pathlib.Path.exists

        def _patched_exists(self):
            result = _orig_exists(self)
            if self == lock_path:
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass
            return result

        monkeypatch.setattr(pathlib.Path, "exists", _patched_exists)

        results: list[bool] = []
        results_lock = threading.Lock()

        def _worker():
            r = cron._acquire_cron_lock()
            with results_lock:
                results.append(r)

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert len(results) == 2, f"a worker thread did not complete: {results}"
        assert results.count(True) == 1, (
            f"expected exactly one winner (the mutex must serialize the "
            f"check-then-write critical section), got {results}"
        )

    def test_mutex_contention_fails_closed(self, tmp_path, monkeypatch):
        """If the guarding mutex itself can't be acquired (held elsewhere,
        contended past its own deadline), _acquire_cron_lock must return
        False -- never fall through and proceed unprotected through the
        check-then-write body it exists to guard."""
        import cron
        from safe_io import CrossProcessLock

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)

        with patch.object(CrossProcessLock, "acquire", return_value=False):
            result = cron._acquire_cron_lock()

        assert result is False
        assert not lock_path.exists(), (
            "must not write the lock file when the guarding mutex was never acquired"
        )

    def test_release_serialized_against_concurrent_acquire_no_spurious_skip(
        self, tmp_path, monkeypatch, caplog
    ):
        """Opus review followup: _release_cron_lock() used to unlink the
        lock file without taking the same guarding mutex, so a concurrent
        _acquire_cron_lock() could see exists()==True (stale, from just
        before release's unlink) and then hit FileNotFoundError on its own
        read_text() a moment later -- landing in the "unreadable lock file"
        fail-closed branch and spuriously skipping an entire cron cycle
        that should have proceeded cleanly. Mutation-tested: reverting the
        mutex wrap in _release_cron_lock (back to a bare
        LOCK_PATH.unlink(missing_ok=True)) makes this fail -- the corrupt-
        lock log line appears and the acquiring thread returns False
        instead of correctly overriding the dead-PID lock."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps({"pid": 999999999, "started_at": 0, "heartbeat": 0})
        )  # dead PID -- overridable, so a correct run returns True

        # Two-event handshake so the interleaving is forced by ORDER, not by
        # incidental thread scheduling (a plain "release runs concurrently"
        # setup is non-deterministic -- release's unlink is fast enough to
        # sometimes complete before the acquire thread even calls exists(),
        # which "passes" for the wrong reason and doesn't exercise the race
        # at all): acquire's exists() must be seen returning True BEFORE
        # release is allowed to unlink, and release's unlink must complete
        # BEFORE acquire's exists() call returns that (now stale) True.
        acquire_checked_exists = threading.Event()
        released = threading.Event()
        _orig_exists = pathlib.Path.exists
        _orig_unlink = pathlib.Path.unlink

        def _patched_exists(self):
            result = _orig_exists(self)
            if self == lock_path and result:
                acquire_checked_exists.set()
                released.wait(timeout=3.0)
            return result

        def _patched_unlink(self, *a, **kw):
            if self == lock_path:
                acquire_checked_exists.wait(timeout=3.0)
            r = _orig_unlink(self, *a, **kw)
            if self == lock_path:
                released.set()
            return r

        monkeypatch.setattr(pathlib.Path, "exists", _patched_exists)
        monkeypatch.setattr(pathlib.Path, "unlink", _patched_unlink)

        results: list[bool] = []
        results_lock = threading.Lock()

        def _acquire_worker():
            with (
                patch("cron._PSUTIL_AVAILABLE", True),
                patch("cron._psutil") as mock_psutil,
            ):
                mock_psutil.pid_exists.return_value = False
                r = cron._acquire_cron_lock()
            with results_lock:
                results.append(r)

        def _release_worker():
            cron._release_cron_lock()

        t_acquire = threading.Thread(target=_acquire_worker)
        t_release = threading.Thread(target=_release_worker)
        with caplog.at_level("WARNING"):
            t_acquire.start()
            t_release.start()
            t_acquire.join(timeout=10)
            t_release.join(timeout=10)

        assert results == [True], (
            f"the dead-PID lock must be cleanly overridden, got {results}"
        )
        corrupt_records = [
            r for r in caplog.records if "unreadable lock file" in r.message
        ]
        assert not corrupt_records, (
            f"acquire must never see a torn/mid-delete lock file as "
            f"'corrupt' -- release must be serialized against it, got "
            f"{[r.message for r in corrupt_records]}"
        )
