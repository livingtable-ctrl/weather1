"""P0-5: _acquire_cron_lock must fail closed and use PID-aware stale detection."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time
from unittest.mock import MagicMock, patch

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
        """Written lock must be valid JSON with pid, started_at.

        batch-33 L-6a: no longer asserts a "heartbeat" field -- it was
        written once at acquire time and never refreshed again, so it was
        a redundant duplicate of started_at rather than a real liveness
        signal; removed rather than kept as misleading dead weight.
        """
        acquired, lock_path = _acquire(monkeypatch, tmp_path)
        assert acquired is True
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()
        assert "started_at" in data
        assert "heartbeat" not in data


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


class _FakeNoSuchProcess(Exception):
    """Two distinct fake exception types (this + _FakeAccessDenied below) so
    the two tests using them each exercise a genuinely different real-world
    psutil failure shape, rather than both instances of the SAME class
    (opus-review-caught: an earlier version of these tests set both
    mock_psutil.NoSuchProcess and mock_psutil.AccessDenied to the identical
    bare `Exception`, which was moot anyway once _cron_lock_pid_reused's own
    except clause was broadened to `except Exception` -- see that function's
    L1 fix -- but using two distinct classes here still proves the broad
    catch genuinely covers more than one exception shape, not just whichever
    one happened to be configured)."""


class _FakeAccessDenied(Exception):
    pass


class TestCronLockPidReused:
    """Unit tests for _cron_lock_pid_reused -- the AUD (batch-30 item 1)
    create_time verification that distinguishes a genuinely live holder
    from an unrelated process that got the same PID reassigned to it."""

    def test_no_create_time_recorded_is_not_positively_reused(self):
        """An old-format lock (written before this fix shipped) has no
        create_time field -- can't positively confirm reuse, so this must
        return False (not "reused"), leaving the caller's own pid_exists()
        check as the sole signal, same as pre-fix behavior."""
        import cron

        assert cron._cron_lock_pid_reused(12345, None) is False

    def test_matching_create_time_is_not_reused(self):
        """Real process's create_time matches the lock's recorded value
        (within clock-rounding slack) -- genuinely the same process."""
        import cron

        with patch("cron._psutil") as mock_psutil:
            mock_psutil.Process.return_value = MagicMock(create_time=lambda: 1000.3)
            assert cron._cron_lock_pid_reused(os.getpid(), 1000.0) is False

    def test_mismatched_create_time_is_reused(self):
        """Real process's create_time is hours later than the lock's
        recorded value -- the PID was reassigned to an unrelated process
        after the original cron holder exited. Mutation-tested: reverting
        the `>= 2.0` comparison in _cron_lock_pid_reused to always return
        False makes this fail."""
        import cron

        with patch("cron._psutil") as mock_psutil:
            mock_psutil.Process.return_value = MagicMock(
                create_time=lambda: 1000.0 + 3600
            )
            assert cron._cron_lock_pid_reused(os.getpid(), 1000.0) is True

    def test_vanished_process_is_not_positively_reused(self):
        """Process() raises a NoSuchProcess-shaped exception (vanished
        between the caller's own pid_exists() check and this call) -- can't
        positively confirm reuse either way, must return False so the
        caller falls back to its own pid_exists()-based policy rather than
        treating this as proof of reuse."""
        import cron

        with patch("cron._psutil") as mock_psutil:
            mock_psutil.Process.side_effect = _FakeNoSuchProcess("gone")
            assert cron._cron_lock_pid_reused(os.getpid(), 1000.0) is False

    def test_access_denied_is_not_positively_reused(self):
        """Process() raises an AccessDenied-shaped exception -- e.g. the PID
        was reassigned to a protected/other-user process this session can't
        query. Same "can't positively confirm" contract as NoSuchProcess
        above, exercised with a genuinely different exception type (not the
        same class reused) so the broad `except Exception` (L1: this
        function has no try/except of its own at either web_app.py call
        site, so an unguarded psutil.Error would otherwise become an
        unhandled 500) is proven against more than one real-world shape.
        Mutation-tested: narrowing the except clause to
        `except _FakeNoSuchProcess` only makes this fail with an unhandled
        _FakeAccessDenied instead of returning False."""
        import cron

        with patch("cron._psutil") as mock_psutil:
            mock_psutil.Process.side_effect = _FakeAccessDenied("denied")
            assert cron._cron_lock_pid_reused(os.getpid(), 1000.0) is False

    def test_non_numeric_create_time_in_lock_does_not_raise(self):
        """F1 (opus-review-caught, round 2): a hand-edited or corrupted
        data/cron.lock could have a non-numeric "create_time" field. The
        subtraction that compares it against the real process's create_time
        must not raise an unhandled TypeError -- this function's two
        web_app.py callers (via _is_cron_running) have no try/except of
        their own, so an escaping exception here becomes a Flask 500,
        exactly what the broad `except Exception` already exists to
        prevent for every OTHER failure shape. Mutation-tested: moving the
        `return abs(...)` line back OUTSIDE the try block makes this raise
        instead of returning False."""
        import cron

        with patch("cron._psutil") as mock_psutil:
            mock_psutil.Process.return_value = MagicMock(create_time=lambda: 1000.0)
            assert cron._cron_lock_pid_reused(os.getpid(), "not-a-number") is False


class TestAcquireCronLockPidReuse:
    """AUD (batch-30 item 1): a lock recording a since-exited cron process's
    PID must not block forever just because Windows reassigned that PID to
    an unrelated live process."""

    def test_overrides_when_pid_reused_by_different_process(
        self, tmp_path, monkeypatch
    ):
        """Live PID (matches our own, guaranteed to pass pid_exists()), but
        its actual create_time doesn't match the lock's recorded
        create_time -- must override, not block. Mutation-tested: removing
        the `and not _cron_lock_pid_reused(...)` clause from
        _acquire_cron_lock makes this fail (falls back to blocking on
        pid_exists() alone)."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time(),
                    "heartbeat": time.time(),
                    "create_time": 1000.0,
                }
            )
        )

        with (
            patch("cron._PSUTIL_AVAILABLE", True),
            patch("cron._psutil") as mock_psutil,
        ):
            mock_psutil.pid_exists.return_value = True
            mock_psutil.Process.return_value = MagicMock(
                create_time=lambda: 1000.0 + 3600
            )
            result = cron._acquire_cron_lock()

        assert result is True
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()

    def test_blocks_when_pid_live_and_create_time_matches(self, tmp_path, monkeypatch):
        """Live PID with a matching create_time -- must block (the
        genuinely-running case, not a regression from adding the
        create_time check). Deliberately uses an old `started_at` (well
        past the former _STALE_LOCK_AGE_SECS age threshold) to prove the
        psutil-available branch no longer has any age-based override --
        opus-review-caught: an earlier version of this fix DID add one,
        reasoning it was safe because cron's own internal watchdog bounds
        how old a genuine cron lock can get -- but `cmd_watch` (main.py,
        `watch --auto --live`) acquires this same lock across
        run_trade_cycle() with NO watchdog, so that override could have
        stolen the lock from a still-running, still-placing-real-orders
        watch session and let a second cron cycle start concurrently. That
        override was removed before ship; this test guards against it (or
        anything like it) coming back."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time() - 7200,
                    "heartbeat": time.time() - 7200,
                    "create_time": 1000.0,
                }
            )
        )

        with (
            patch("cron._PSUTIL_AVAILABLE", True),
            patch("cron._psutil") as mock_psutil,
        ):
            mock_psutil.pid_exists.return_value = True
            mock_psutil.Process.return_value = MagicMock(create_time=lambda: 1000.0)
            result = cron._acquire_cron_lock()

        assert result is False

    def test_overrides_when_unconfirmable_reuse_exceeds_stuck_running_backstop(
        self, tmp_path, monkeypatch
    ):
        """F2 (opus-review-caught, round 2): pid_exists()=True but reuse
        can never be positively confirmed (e.g. persistent AccessDenied
        querying the holding PID) must not block cron FOREVER -- that's the
        exact permanent-lock-out failure mode this batch exists to
        eliminate, just reachable via a different path than the original
        finding. _STUCK_RUNNING_BACKSTOP_SECS (24h) is safe here because
        neither cmd_cron (watchdog-bounded, 720s) nor a single cmd_watch
        cycle can plausibly reach that age -- unlike the removed 1800s
        override, which cmd_watch's overall session length COULD plausibly
        reach. Mutation-tested: removing the
        `if age < _STUCK_RUNNING_BACKSTOP_SECS` guard (unconditional block
        on live+unconfirmed) makes this fail."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time() - cron._STUCK_RUNNING_BACKSTOP_SECS - 1,
                    "heartbeat": time.time() - cron._STUCK_RUNNING_BACKSTOP_SECS - 1,
                    "create_time": 1000.0,
                }
            )
        )

        with (
            patch("cron._PSUTIL_AVAILABLE", True),
            patch("cron._psutil") as mock_psutil,
        ):
            mock_psutil.pid_exists.return_value = True

            class _FakeAccessDenied2(Exception):
                pass

            mock_psutil.Process.side_effect = _FakeAccessDenied2("denied")
            result = cron._acquire_cron_lock()

        assert result is True

    def test_written_lock_includes_create_time_when_psutil_available(
        self, tmp_path, monkeypatch
    ):
        """A freshly-acquired lock must record its own process's create_time
        so a FUTURE acquirer can run this same reuse check against it --
        without this, every lock written stays in the unverifiable
        "old-format" bucket forever. Skips (rather than erroring) when
        psutil genuinely isn't installed -- opus-review-caught: this test
        exercises the REAL cron._psutil, not a mock, so without the skip a
        missing psutil would surface as a confusing KeyError on
        data["create_time"] instead of an honest skip."""
        import cron

        if not cron._PSUTIL_AVAILABLE:
            pytest.skip("psutil not installed in this environment")

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)

        acquired = cron._acquire_cron_lock()

        assert acquired is True
        data = json.loads(lock_path.read_text())
        assert "create_time" in data
        assert isinstance(data["create_time"], float)


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
        # pid=os.getpid() (not an arbitrary dead PID): _release_cron_lock's
        # H2 ownership check (opus-review-caught) makes release a no-op for
        # a lock it doesn't own, so this test's release worker must
        # legitimately own the lock it's exercising -- pid_exists is mocked
        # False below regardless of which real PID is recorded, so this is
        # still the "dead PID, overridable" scenario from the acquiring
        # thread's perspective.
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "started_at": 0, "heartbeat": 0})
        )  # dead PID (per the mock below) -- overridable, so a correct run returns True

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


class TestReleaseCronLockOwnership:
    """H2 (opus-review-caught): _release_cron_lock() used to unconditionally
    unlink() whatever's currently in the lock file. If process A's own lock
    got overridden as stale by process B (e.g. the no-psutil >1800s
    fallback), A's delayed `finally: ctx.release_cron_lock()` would delete
    B's fresh lock -- leaving B running completely unprotected and letting
    a THIRD acquirer start concurrently. _release_cron_lock now checks the
    lock file's own recorded pid against os.getpid() before unlinking.

    batch-33 M-3: the ownership check itself had a fail-OPEN gap in
    exactly the case it exists to protect -- an unreadable read (torn
    write, PermissionError, corrupt JSON) defaulted owner_pid=None, and
    the old `owner_pid is not None and owner_pid != os.getpid()` guard
    treated None as "nothing to protect" and fell through to unlink()
    anyway. Fixed to skip the unlink whenever ownership can't be
    positively confirmed -- see test_skips_unlink_on_unreadable_lock.
    """

    def test_does_not_delete_a_lock_owned_by_a_different_pid(
        self, tmp_path, monkeypatch
    ):
        """Mutation-tested: removing the ownership check (back to a bare
        `lp.unlink(missing_ok=True)`) makes this fail -- the lock disappears
        even though this process never wrote it."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        other_pid_lock = {
            "pid": 424242,
            "started_at": time.time(),
            "heartbeat": time.time(),
        }
        lock_path.write_text(json.dumps(other_pid_lock))

        cron._release_cron_lock()

        assert lock_path.exists(), (
            "release must not delete a lock file recording a DIFFERENT "
            "process's pid than its own os.getpid()"
        )
        assert json.loads(lock_path.read_text()) == other_pid_lock

    def test_deletes_a_lock_owned_by_this_process(self, tmp_path, monkeypatch):
        """The common/happy path must be unaffected: releasing this
        process's own lock still deletes it."""
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

        cron._release_cron_lock()

        assert not lock_path.exists()

    def test_missing_lock_file_is_a_silent_no_op(self, tmp_path, monkeypatch):
        """No lock file at all (already released, or never created) --
        release must not raise."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)

        cron._release_cron_lock()  # must not raise

        assert not lock_path.exists()

    def test_skips_unlink_on_unreadable_lock(self, tmp_path, monkeypatch):
        """batch-33 M-3: a lock file that fails to parse (corrupt /
        truncated / a torn concurrent write / PermissionError) must NOT be
        deleted by release -- the old behavior here (delete it, reasoning
        "no readable pid to protect") was exactly the H2 hazard this
        class's own module docstring describes, one layer deeper: release
        can't tell an unreadable lock apart from one a DIFFERENT process
        just wrote a fraction of a second ago (e.g. this same process's
        own lock got overridden as stale, and the new owner's write is
        mid-flight) -- unlinking on "can't verify" fails OPEN toward
        deleting a possibly-live lock, backwards from this whole
        function's fail-closed intent. The acquire side already has its
        own explicit self-heal for a genuinely, persistently corrupt lock
        (_acquire_cron_lock's own `except: lp.unlink(); return False`), so
        an unreadable lock left behind by release isn't stuck forever --
        it's cleaned up on the very next acquire attempt instead.

        Mutation-tested: reverting to the old `except Exception: owner_pid
        = None` + `if owner_pid is not None and owner_pid != os.getpid()`
        shape makes this fail (the corrupt lock gets deleted again).
        """
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text("not valid json {{{{")

        cron._release_cron_lock()  # must not raise

        assert lock_path.exists(), (
            "an unreadable lock must be left in place (fail closed) -- "
            "release can't positively confirm it isn't a different "
            "process's fresh lock"
        )
        assert lock_path.read_text() == "not valid json {{{{", (
            "the unreadable file itself must be untouched, not just present"
        )

    def test_skips_unlink_when_pid_field_is_missing(self, tmp_path, monkeypatch):
        """batch-33 M-3, positive control distinguishing 'valid JSON with
        no pid key' from 'unreadable' -- both must skip the unlink (same
        `owner_pid != os.getpid()` comparison handles both, since a
        missing key reads as None), but this path exercises the JSON
        successfully parsing rather than raising."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text(json.dumps({"started_at": time.time()}))

        cron._release_cron_lock()

        assert lock_path.exists()
