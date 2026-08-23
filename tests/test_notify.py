"""Tests for notify.py's system-alert cooldown persistence.

backlog.txt "NOTIFY.SEND_SYSTEM_ALERT()'S COOLDOWN IS IN-PROCESS MEMORY
ONLY, DOESN'T SURVIVE A FRESH CRON PROCESS" -- _system_cooldown_reserve()
persists cooldown timestamps to disk (paths.NOTIFY_COOLDOWN_STATE_PATH) so
send_system_alert() actually suppresses repeat alerts across separate
process invocations, not just within one long-lived process. Deliberately
scoped to send_system_alert()'s cooldown only -- alert_strong_signal()'s
per-ticker cooldown stays in-process (see notify.py's own comment on
_last_notified for why).

batch-24 item 3 (2026-08-22): _system_cooldown_elapsed() was split into
_system_cooldown_reserve() (read + reserve, returns (reserved, previous))
and _system_cooldown_rollback() (undo a reservation after total delivery
failure) so send_system_alert() no longer burns the cooldown on a call
where every channel failed. TestSystemCooldownElapsed below was updated to
call _system_cooldown_reserve() and unpack its tuple; its assertions and
intent are otherwise unchanged. See tests/test_batch24_alerting.py for the
new rollback-specific tests.
"""

from __future__ import annotations

import json
import threading

import notify

# A realistic Unix epoch value (2026-ish), not a small offset like 1000.0 --
# the cooldown check is `now - last < cooldown_secs` with `last` defaulting
# to 0.0 for an unseen key, so a small `now` would itself look like "still
# within cooldown of a fictional alert at epoch zero" and produce a
# misleading false-suppression. Real `time.time()` is always ~1.7-1.8
# billion, which never collides with this failure mode in production.
_NOW = 1_800_000_000.0
_SIX_HOURS = 21_600


class TestSystemCooldownElapsed:
    """Direct tests of the disk-persisted cooldown reservation check (now
    _system_cooldown_reserve(), see module docstring). Each test
    redirects notify.NOTIFY_COOLDOWN_STATE_PATH to an isolated tmp_path file
    so no test ever touches the real data/.notify_cooldowns.json."""

    def _cooldown_path(self, tmp_path):
        return tmp_path / "notify_cooldowns.json"

    def test_first_call_for_new_key_fires_and_persists(self, tmp_path, monkeypatch):
        path = self._cooldown_path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        fired, previous = notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )

        assert fired is True
        assert previous == 0.0
        assert path.exists()
        assert json.loads(path.read_text()) == {"emergency_copy": _NOW}

    def test_second_call_within_cooldown_is_suppressed(self, tmp_path, monkeypatch):
        path = self._cooldown_path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        assert notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )[0]
        # 1 hour later, well inside the 6h cooldown.
        fired_again, previous = notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW + 3600, cooldown_secs=_SIX_HOURS
        )

        assert fired_again is False
        assert previous == _NOW
        # Suppressed call must NOT have updated the persisted timestamp.
        assert json.loads(path.read_text()) == {"emergency_copy": _NOW}

    def test_this_is_the_actual_regression_this_entry_is_about(
        self, tmp_path, monkeypatch
    ):
        """The whole point of this fix: a second, independent lookup against
        the SAME persisted file (simulating a fresh `py main.py cron`
        process reading the cooldown state cold, with no in-memory state
        carried over) must still see the cooldown as active. Unlike the old
        `_last_notified` in-process dict, this function never reads any
        Python-process-local cache -- every call re-reads the file from
        disk, which is exactly what makes this safe across process
        boundaries."""
        path = self._cooldown_path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )

        # Simulate a fresh process: a brand new call with no shared Python
        # state other than the same file path.
        fired_from_fresh_process, _ = notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW + 60, cooldown_secs=_SIX_HOURS
        )

        assert fired_from_fresh_process is False

    def test_cooldown_elapses_after_the_full_window(self, tmp_path, monkeypatch):
        path = self._cooldown_path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        fired_after_window, previous = notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW + _SIX_HOURS + 0.1, cooldown_secs=_SIX_HOURS
        )

        assert fired_after_window is True
        assert previous == _NOW
        assert json.loads(path.read_text())["emergency_copy"] == _NOW + _SIX_HOURS + 0.1

    def test_distinct_cooldown_keys_do_not_interfere(self, tmp_path, monkeypatch):
        path = self._cooldown_path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        assert notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )[0]
        # A different key, same instant, must not be suppressed by the first.
        assert notify._system_cooldown_reserve(
            "cron_gap", now=_NOW, cooldown_secs=_SIX_HOURS
        )[0]
        state = json.loads(path.read_text())
        assert state == {"emergency_copy": _NOW, "cron_gap": _NOW}

    def test_missing_cooldown_file_fails_open(self, tmp_path, monkeypatch):
        """No prior cooldown file at all (e.g. first-ever run) must fire,
        not silently swallow the alert."""
        path = tmp_path / "does_not_exist.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        assert notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )[0]

    def test_corrupt_cooldown_file_fails_open(self, tmp_path, monkeypatch):
        """A corrupt/unparseable cooldown file must never block a real
        system alert -- fail open, not closed."""
        path = self._cooldown_path(tmp_path)
        path.write_text("{not valid json")
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        assert notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )[0]

    def test_missing_parent_directory_is_created(self, tmp_path, monkeypatch):
        """End-to-end behavior check -- the parent-directory creation itself
        happens inside atomic_write_json() (safe_io.py), not in notify.py, so
        this proves the full call chain handles a missing parent correctly
        rather than proving notify.py's own code does the mkdir (opus
        review, 2026-07-31: an earlier draft had a redundant, now-removed
        mkdir call in notify.py itself, which made this test pass regardless
        of whether atomic_write_json's own mkdir worked)."""
        path = tmp_path / "nested" / "does_not_exist_yet" / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        fired, _ = notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )

        assert fired is True
        assert path.exists()

    def test_non_dict_json_fails_open(self, tmp_path, monkeypatch):
        """Valid JSON that isn't a dict (e.g. `null` or a bare list) must not
        crash with an AttributeError from state.get() on a non-dict -- fails
        open instead, same as a corrupt/missing file."""
        path = self._cooldown_path(tmp_path)
        path.write_text("null")
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        assert notify._system_cooldown_reserve(
            "emergency_copy", now=_NOW, cooldown_secs=_SIX_HOURS
        )[0]

    def test_read_failure_does_not_clobber_other_keys(self, tmp_path, monkeypatch):
        """A transient read failure (circuit_breaker.py documents a real
        observed Windows PermissionError mid-os.replace for this exact read
        shape) must not silently erase every OTHER already-persisted
        cooldown key -- if this call can't safely see what's already in the
        file, it must not blindly overwrite it with a blank-plus-one-key
        state."""
        path = self._cooldown_path(tmp_path)
        path.write_text(json.dumps({"other_key": _NOW - 100}))
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        real_loads = notify.json.loads

        def _failing_loads(*_a, **_k):
            raise OSError("simulated transient read failure")

        monkeypatch.setattr(notify.json, "loads", _failing_loads)
        fired, _ = notify._system_cooldown_reserve(
            "new_key", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert fired is True, "a read failure must still fail open"

        monkeypatch.setattr(notify.json, "loads", real_loads)
        assert json.loads(path.read_text()) == {"other_key": _NOW - 100}, (
            "the failed read must not have written anything -- 'other_key' "
            "must survive untouched, and 'new_key' must NOT have been added "
            "without a successful read to merge against"
        )

    def test_concurrent_threads_only_one_fires(self, tmp_path, monkeypatch):
        """The lock's actual job (thread-level, not cross-process -- see
        _NOTIFY_COOLDOWN_FILE_LOCK's own comment): N threads racing on the
        same key must result in exactly one firing. Without a lock spanning
        the full read-decide-write, multiple threads could all read "no
        prior record" before any of them writes, and all fire."""
        path = self._cooldown_path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        n = 20
        barrier = threading.Barrier(n)
        results: list[bool] = []
        results_lock = threading.Lock()

        def worker():
            barrier.wait()
            fired, _ = notify._system_cooldown_reserve(
                "race_key", now=_NOW, cooldown_secs=_SIX_HOURS
            )
            with results_lock:
                results.append(fired)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 1, (
            f"expected exactly 1 of {n} concurrent threads to fire, got {sum(results)}"
        )


class TestSendSystemAlertUsesPersistedCooldown:
    """Integration-level: send_system_alert() itself (not just the helper)
    respects the persisted cooldown end to end. External channels are
    monkeypatched to a fake recorder so this never attempts a real
    network/desktop call."""

    def test_second_call_within_cooldown_sends_nothing(self, tmp_path, monkeypatch):
        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        calls: list[int] = []
        monkeypatch.setattr(
            notify, "_send_discord", lambda *a, **k: calls.append(1) or True
        )
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})

        notify.send_system_alert("t1", "m1", cooldown_key="test_key")
        notify.send_system_alert("t2", "m2", cooldown_key="test_key")

        assert len(calls) == 1, "second call inside the 6h cooldown must not re-send"

    def test_distinct_cooldown_keys_both_send(self, tmp_path, monkeypatch):
        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        calls: list[int] = []
        monkeypatch.setattr(
            notify, "_send_discord", lambda *a, **k: calls.append(1) or True
        )
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})

        notify.send_system_alert("t1", "m1", cooldown_key="key_a")
        notify.send_system_alert("t2", "m2", cooldown_key="key_b")

        assert len(calls) == 2, "distinct cooldown keys must not suppress each other"
