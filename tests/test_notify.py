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
import sys
import threading
import time

import pytest

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


# ─────────────────────────────────────────────────────────────────────────────
# batch-80 item 2 -- backlog.txt "A SYSTEM ALERT LONGER THAN 256 CHARACTERS
# CRASHES THE DESKTOP-TOAST BACKEND"
# ─────────────────────────────────────────────────────────────────────────────


class _FakeNotif:
    """Records the kwargs plyer's notify() would have been called with.

    A recording double, not a MagicMock: these tests assert on the LENGTH of
    what was passed, and MagicMock would happily accept and auto-vivify
    anything, so a call site that stopped passing `message` at all would not
    fail here.
    """

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def notify(self, **kwargs) -> None:
        self.kwargs.update(kwargs)


def _install_desktop_only(monkeypatch) -> _FakeNotif:
    fake = _FakeNotif()
    monkeypatch.setattr(notify, "_notif", fake)
    monkeypatch.setattr(notify, "_ENABLED", True)
    monkeypatch.setattr(notify, "_CHANNELS", {"desktop"})
    # batch-84 item 1: _desktop_notify only routes through the plyer FACADE
    # (and therefore through this double) when the Windows balloon_tip is
    # absent. Without pinning it to None these tests would silently stop
    # observing anything on a Windows machine -- fake.kwargs would stay
    # empty while the real backend popped real toasts -- and would keep
    # passing on Linux CI. TestDesktopDeliveryConfirmation below covers the
    # Windows path's own truncation separately.
    monkeypatch.setattr(notify, "_WIN_BALLOON_TIP", None)
    return fake


class TestDesktopFieldTruncation:
    """The desktop toast's fixed-width struct fields must never be overrun.

    plyer's Windows backend runs balloon_tip on a thread it spawns itself
    (WindowsNotification._notify is `thread(target=balloon_tip, ...).start()`),
    so a ValueError raised in there cannot be caught by a wrapper around
    plyer's facade -- it escapes uncaught and the desktop half of the alert
    is lost with no record. Not handing plyer an over-long string is what
    actually keeps the toast deliverable, which is why these tests assert on
    the ARGUMENTS passed to plyer rather than on an exception being handled.

    batch-84 item 1 narrowed the claim this docstring used to make ("the only
    control this module has"): notify._desktop_notify now runs balloon_tip on
    a thread notify.py owns, so a backend exception IS caught and reported.
    That changes whether a failure is RECORDED, not whether it happens --
    truncation is still the only thing that stops it happening. See
    TestDesktopDeliveryConfirmation below.
    """

    def test_struct_limits_match_the_real_ctypes_arrays(self):
        """The constants are the actual Windows struct widths, minus the NUL.

        This is the load-bearing test. DESKTOP_MESSAGE_MAX/TITLE_MAX are
        transcribed by hand from plyer's NOTIFYICONDATAW definition, and a
        wrong transcription reintroduces the exact bug while every
        double-based test below still passes. This builds the real ctypes
        arrays and checks the boundary from both sides, so it fails if the
        constants are edited or if plyer ever changes the widths.
        """
        import ctypes

        for limit, width, field in (
            (notify.DESKTOP_MESSAGE_MAX, 256, "szInfo"),
            (notify.DESKTOP_TITLE_MAX, 64, "szInfoTitle"),
        ):
            assert limit == width - 1, (
                f"{field}: limit {limit} must sit one below the {width}-wide "
                f"array so the NUL terminator has somewhere to go"
            )
            arr = ctypes.c_wchar * width
            buf = arr()
            buf.value = "x" * limit
            assert len(buf.value) == limit
            # POSITIVE CONTROL: prove this array really does reject overlong
            # input, so the assignment above passing means something.
            with pytest.raises(ValueError):
                arr().value = "y" * (width + 1)

    def test_over_long_message_is_truncated_before_reaching_plyer(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        fake = _install_desktop_only(monkeypatch)

        # 333 is the length from the original crash report in backlog.txt.
        notify.send_system_alert("t" * 200, "m" * 333, cooldown_key="trunc_msg")

        assert len(fake.kwargs["message"]) == notify.DESKTOP_MESSAGE_MAX
        assert len(fake.kwargs["title"]) == notify.DESKTOP_TITLE_MAX
        assert fake.kwargs["message"].endswith("…")
        assert fake.kwargs["title"].endswith("…")
        # POSITIVE CONTROL (step 28). The assertions above describe what did
        # NOT reach plyer, so prove the desktop branch was actually entered
        # and that these are the real strings rather than some unrelated
        # short value. app_name is passed only inside that branch.
        assert fake.kwargs["app_name"] == "Kalshi Weather"
        assert fake.kwargs["message"].startswith("mmm")
        assert fake.kwargs["title"].startswith("ttt")

    def test_text_that_already_fits_is_passed_through_untouched(
        self, tmp_path, monkeypatch
    ):
        """The at-limit boundary must NOT be truncated.

        Mutating _truncate_for_desktop's `len(text) <= limit` to `<` makes
        this fail; without it an off-by-one would silently clip a message
        that fits.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        fake = _install_desktop_only(monkeypatch)

        msg = "m" * notify.DESKTOP_MESSAGE_MAX
        title = "t" * notify.DESKTOP_TITLE_MAX
        notify.send_system_alert(title, msg, cooldown_key="trunc_exact")

        assert fake.kwargs["message"] == msg, "at-limit message must pass through"
        assert fake.kwargs["title"] == title, "at-limit title must pass through"
        assert "…" not in fake.kwargs["message"]

    def test_other_channels_still_receive_the_full_untruncated_text(
        self, tmp_path, monkeypatch
    ):
        """Truncation is desktop-only -- Discord must still get everything.

        This is the half that makes the fix a repair rather than a new loss:
        the entry is only LOW because Discord still delivers in full, so a
        fix that shortened the Discord copy too would be a regression.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        fake = _install_desktop_only(monkeypatch)
        discord_args: list[tuple] = []
        monkeypatch.setattr(
            notify,
            "_send_discord",
            lambda t, m, **k: discord_args.append((t, m)) or True,
        )
        monkeypatch.setattr(notify, "_CHANNELS", {"desktop", "discord"})

        # 1499 is simply a comfortably-over-cap length. It was previously
        # annotated as tracker.audit_settlement's Miami alert body; that
        # attribution came from the backlog entry and is wrong -- evaluating
        # that f-string with realistic values renders ~377 characters, still
        # ~1.5x over the 256 cap but nowhere near 1499 (opus review M-2).
        long_message = "m" * 1499
        long_title = "t" * 200
        notify.send_system_alert(long_title, long_message, cooldown_key="trunc_both")

        assert len(discord_args) == 1, "discord must still be attempted"
        got_title, got_message = discord_args[0]
        assert got_message == long_message, "discord must receive the FULL message"
        assert got_title == long_title, "discord must receive the FULL title"
        # And the desktop copy really was the clipped one, in the same call.
        assert len(fake.kwargs["message"]) == notify.DESKTOP_MESSAGE_MAX

    def test_truncation_is_logged(self, tmp_path, monkeypatch, caplog):
        """Losing part of an alert must leave a record.

        "It silently drops the desktop half" is the entry's actual complaint;
        truncating without logging would swap a silent crash for a silent
        clip.
        """
        import logging

        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_desktop_only(monkeypatch)

        with caplog.at_level(logging.WARNING, logger="notify"):
            notify.send_system_alert("short", "m" * 333, cooldown_key="trunc_log")

        warnings = [r.getMessage() for r in caplog.records]
        assert any("truncated from 333 to 255" in w for w in warnings), warnings
        # POSITIVE CONTROL: the short title in the same call must NOT have
        # logged, so this proves the log is driven by the actual overflow and
        # not emitted unconditionally.
        assert not any("title truncated" in w for w in warnings), warnings

    def test_strong_signal_desktop_path_is_truncated_too(self, monkeypatch):
        """alert_strong_signal has its own _notif.notify() call site.

        Its title and body come from operator-editable templates
        (notify_templates.json), so they are unbounded too. A fix applied
        only to send_system_alert would leave this one armed.
        """
        fake = _install_desktop_only(monkeypatch)
        monkeypatch.setattr(notify, "_last_notified", {})
        monkeypatch.setattr(
            notify,
            "_TEMPLATES",
            {"strong_signal_title": "T" * 200, "strong_signal_body": "B" * 900},
        )

        notify.alert_strong_signal(
            ticker="KXHIGH-NYC-1",
            city="NYC",
            side="yes",
            net_edge=0.20,
            kelly=0.10,
        )

        assert fake.kwargs, "the desktop branch must have been reached"
        assert len(fake.kwargs["message"]) == notify.DESKTOP_MESSAGE_MAX
        assert len(fake.kwargs["title"]) == notify.DESKTOP_TITLE_MAX

    def test_budget_is_utf16_units_not_python_characters(self, tmp_path, monkeypatch):
        """A WCHAR array counts UTF-16 units; astral characters cost two.

        opus review M-1. A code-point budget lets a string of 129 emoji --
        len() 129, but 258 UTF-16 units -- straight through to plyer, where it
        raises the ORIGINAL ValueError on the thread notify.py cannot reach.
        Latent today (no source file here has a character above U+FFFF) but
        notify_templates.json is operator-editable and both templates format()
        in external `city` and `ticker` strings.
        """
        import ctypes

        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        fake = _install_desktop_only(monkeypatch)

        siren = "🚨"  # non-BMP: 1 char, 2 UTF-16 units
        assert len(siren) == 1 and notify._utf16_units(siren) == 2, (
            "positive control: this fixture must actually be astral, or the "
            "test proves nothing about the units-vs-characters distinction"
        )

        notify.send_system_alert("t", siren * 200, cooldown_key="trunc_astral")

        msg = fake.kwargs["message"]
        # The budget that matters is units, and it must be respected...
        assert notify._utf16_units(msg) <= notify.DESKTOP_MESSAGE_MAX
        # ...which for astral text means FEWER characters than the limit.
        assert len(msg) < notify.DESKTOP_MESSAGE_MAX
        # Never split a surrogate pair.
        assert msg.rstrip("…").count(siren) * 2 + 1 == notify._utf16_units(msg)
        # THE load-bearing assertion: the real struct accepts it. A
        # code-point budget fails here with "string too long (401, ...)".
        buf = (ctypes.c_wchar * 256)()
        buf.value = msg

    def test_a_limit_of_one_or_zero_cannot_lengthen_the_text(self):
        """opus review L-7: hygiene on the degenerate bound.

        Unreachable with the 255/63 constants, but the slice at limit 0
        returned a LONGER string than it was handed.
        """
        assert notify._truncate_for_desktop("abc", 0, "message") == ""
        assert notify._truncate_for_desktop("abc", 1, "message") == "a"
        # round-2 opus review L2: at limit 1 an ASTRAL first character is one
        # code point but two units, so a bare text[:1] here would itself
        # exceed the budget the guard exists to respect.
        assert notify._truncate_for_desktop(chr(0x1F6A8) + "bc", 1, "message") == ""
        # Positive control: the normal path still truncates rather than
        # returning a prefix, so the guard above is scoped to the degenerate
        # case and has not swallowed the real behaviour.
        assert notify._truncate_for_desktop("abc", 2, "message") == "a…"

    def test_an_unpaired_surrogate_does_not_raise(self):
        """round-2 opus review L1: ctypes accepts a lone surrogate; a bare
        utf-16-le encode does not.

        notify_templates.json is operator-editable and JSON permits an
        escaped lone surrogate, which json.loads turns into a real one. A
        plain encode would raise UnicodeEncodeError on text the toast field
        would have accepted -- a NEW failure mode the len()-based version did
        not have, so the units fix had to not introduce one.
        """
        lone = chr(0xD800)
        assert notify._utf16_units(lone) == 1
        assert (
            notify._truncate_for_desktop(lone + "abc", 255, "message") == lone + "abc"
        )
        # Positive control: ctypes really does take it, so tolerating it here
        # is matching the field's behaviour rather than papering over a crash.
        import ctypes

        (ctypes.c_wchar * 256)().value = lone

    def test_non_string_input_is_coerced_not_crashed(self):
        """round-2 opus review L3: the isinstance guard was untested.

        Mutating it away left all 21 notify tests green, which by this repo's
        own heuristic means the branch is either dead or unpinned. It is not
        dead -- both call sites format templates whose values come from
        callers -- so it gets a test rather than a deletion.
        """
        assert notify._truncate_for_desktop(None, 10, "message") == "None"
        assert notify._truncate_for_desktop(12345, 10, "message") == "12345"
        # Positive control: a non-str that is TOO LONG still truncates, so
        # the coercion feeds the real path rather than short-circuiting it.
        out = notify._truncate_for_desktop(10**400, 20, "message")
        assert len(out) == 20 and out.endswith("…")


# ─────────────────────────────────────────────────────────────────────────────
# batch-84 item 1 -- backlog.txt "NOTIFY.PY RECORDS THE DESKTOP CHANNEL AS
# DELIVERED WHENEVER PLYER'S notify() RETURNS, BUT ON WINDOWS THAT ONLY
# MEANS 'A THREAD WAS STARTED'"
# ─────────────────────────────────────────────────────────────────────────────


class _RecordingTip:
    """Stands in for plyer's Windows balloon_tip on the thread notify.py owns.

    A recording double rather than a raising Mock of ``notify._notif``, and
    the distinction is the whole point of this item: a raising ``_notif``
    mock is caught by the very ``except Exception`` this defect is about, so
    it can only ever demonstrate the path that already worked. The real
    failure happens on the worker thread, which is where this raises.

    ``delay`` models a backend that is slow rather than broken; ``exc``
    models RegisterClassExW/CreateWindowExW/Shell_NotifyIconW/ctypes failing.
    """

    def __init__(self, exc: BaseException | None = None, delay: float = 0.0) -> None:
        self.calls: list[dict] = []
        self._exc = exc
        self._delay = delay

    def __call__(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self._delay:
            time.sleep(self._delay)
        if self._exc is not None:
            raise self._exc


class _HardFailure(BaseException):
    """A backend failure that `except Exception` would NOT catch."""


class _FacadeReached(BaseException):
    """Raised if the Windows path ever routes through plyer's facade.

    BaseException, not Exception -- the same trick conftest.py uses for
    BlockedNetworkCall. An AssertionError here would be caught by the very
    `except Exception` at each call site and quietly turned into
    successes.append(False), so a mis-route would satisfy every "reports
    False" assertion in this class instead of failing loudly (opus review
    L-6).
    """


class _ForbiddenNotif:
    """A plyer facade that must never be reached on the Windows path."""

    def notify(self, **kwargs) -> None:
        raise _FacadeReached(
            "the Windows path must call balloon_tip on notify.py's own "
            "thread, never plyer's fire-and-forget facade"
        )


def _install_windows_desktop(
    monkeypatch, tip: _RecordingTip, *, confirm_secs: float = 2.0
) -> _RecordingTip:
    """desktop-only channels, Windows backend, with `tip` as balloon_tip.

    The default window is GENEROUS, not tight (opus review L-5). Thread.join
    returns the instant the worker exits, so a long window costs a
    fast-failing double nothing and removes all timing sensitivity from the
    tests that expect False. Only the two tests that are ABOUT the window
    pass a small value, and each says why.
    """
    monkeypatch.setattr(notify, "_notif", _ForbiddenNotif())
    monkeypatch.setattr(notify, "_ENABLED", True)
    monkeypatch.setattr(notify, "_CHANNELS", {"desktop"})
    monkeypatch.setattr(notify, "_WIN_BALLOON_TIP", tip)
    # The real 0.5s is pinned by its own test below.
    monkeypatch.setattr(notify, "DESKTOP_CONFIRM_SECS", confirm_secs)
    return tip


class TestDesktopDeliveryConfirmation:
    """A desktop toast that never appeared must not be recorded as delivered.

    plyer's WindowsNotification._notify is exactly
    ``thread(target=balloon_tip, kwargs=kwargs).start()``, so before this
    change ``successes.append(True)`` ran unconditionally: every failure mode
    of the real backend raises on plyer's own thread, where notify.py could
    not see it. send_system_alert() returns ``status != "failed"`` and
    alerts.rollback_halt_transition keys off a False return, so the phantom
    True disabled the retry that exists for exactly this case.

    Why the honest-failure direction alone was not the fix: measured against
    this deployment's .env on 2026-08-26, NTFY_TOPIC, PUSHOVER_*, DISCORD_*
    and SMTP_* are all unset, so desktop is the only channel that can
    succeed. Recording it as False unconditionally would have made every
    system alert "failed" and re-fired it every cron cycle forever.
    """

    def test_a_failing_windows_toast_is_reported_as_not_delivered(
        self, tmp_path, monkeypatch
    ):
        """The defect, stated directly."""
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        tip = _install_windows_desktop(
            monkeypatch, _RecordingTip(exc=RuntimeError("Shell_NotifyIconW failed."))
        )

        status, n_ok, n_attempted = notify.send_system_alert_detailed(
            "Halt", "drawdown halt engaged", cooldown_key="b84_fail"
        )

        assert status == "failed"
        assert n_ok == 0
        # POSITIVE CONTROL (step 28): the assertions above are about a
        # channel NOT succeeding, which a skipped channel would satisfy just
        # as well. These prove the desktop branch was entered, that the
        # attempt was counted, and that the backend really was invoked with
        # the alert's own text -- so "failed" came from the failure and not
        # from an empty `successes` list.
        assert n_attempted == 1
        assert len(tip.calls) == 1
        assert tip.calls[0]["app_name"] == "Kalshi Weather"
        assert tip.calls[0]["title"] == "Halt"

    def test_a_working_windows_toast_is_still_reported_as_delivered(
        self, tmp_path, monkeypatch
    ):
        """The half that keeps this a repair rather than a new outage.

        The rejected alternative -- never appending True for desktop -- would
        also pass the test above, while turning every alert in a desktop-only
        deployment into a "failed" that re-fires every cycle.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        tip = _install_windows_desktop(monkeypatch, _RecordingTip())

        status, n_ok, n_attempted = notify.send_system_alert_detailed(
            "Halt", "drawdown halt engaged", cooldown_key="b84_ok"
        )

        assert status == "delivered"
        assert (n_ok, n_attempted) == (1, 1)
        assert len(tip.calls) == 1

    def test_send_system_alert_returns_false_only_when_the_toast_failed(
        self, tmp_path, monkeypatch
    ):
        """The bool contract alerts.rollback_halt_transition actually reads."""
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(monkeypatch, _RecordingTip(exc=RuntimeError("boom")))
        assert notify.send_system_alert("t", "m", cooldown_key="b84_bool_bad") is False

        # Positive control, distinct cooldown key: a working backend must
        # still return True, so the False above is about the failure and not
        # about desktop having stopped counting at all.
        _install_windows_desktop(monkeypatch, _RecordingTip())
        assert notify.send_system_alert("t", "m", cooldown_key="b84_bool_ok") is True

    def test_a_desktop_failure_rolls_the_cooldown_back_so_the_next_cycle_retries(
        self, tmp_path, monkeypatch
    ):
        """A lost alert must not burn its own 6h suppression window.

        This is the operator-visible consequence of the phantom True: the
        alert was recorded delivered, the cooldown stayed reserved, and the
        next cron cycle said nothing.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        failing = _install_windows_desktop(
            monkeypatch, _RecordingTip(exc=RuntimeError("boom"))
        )

        notify.send_system_alert("t", "m", cooldown_key="b84_retry")
        notify.send_system_alert("t", "m", cooldown_key="b84_retry")
        assert len(failing.calls) == 2, "a failed alert must be retried immediately"

        # POSITIVE CONTROL: the same two back-to-back calls with a WORKING
        # backend must be suppressed the second time. Without this, the
        # assertion above would pass just as happily if the cooldown had
        # stopped working entirely rather than being rolled back on failure.
        working = _install_windows_desktop(monkeypatch, _RecordingTip())
        first = notify.send_system_alert_detailed("t", "m", cooldown_key="b84_retry_ok")
        second = notify.send_system_alert_detailed(
            "t", "m", cooldown_key="b84_retry_ok"
        )
        assert first[0] == "delivered"
        assert second[0] == "suppressed"
        assert len(working.calls) == 1

    def test_the_all_channels_failed_warning_can_now_fire_on_a_desktop_failure(
        self, tmp_path, monkeypatch, caplog
    ):
        """The G7 warning was unreachable for a desktop-only deployment."""
        import logging

        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(monkeypatch, _RecordingTip(exc=RuntimeError("boom")))

        with caplog.at_level(logging.WARNING, logger="notify"):
            notify.send_system_alert("t", "m", cooldown_key="b84_warn")
        warnings = [r.getMessage() for r in caplog.records]
        assert any("all 1 channel(s) failed" in w for w in warnings), warnings
        # The failure itself is also named, so bot.log records WHY.
        assert any("Windows toast backend failed" in w for w in warnings), warnings

        # POSITIVE CONTROL: a working backend must log neither, so the
        # assertions above are driven by the failure rather than by a warning
        # this path emits unconditionally.
        caplog.clear()
        _install_windows_desktop(monkeypatch, _RecordingTip())
        with caplog.at_level(logging.WARNING, logger="notify"):
            notify.send_system_alert("t", "m", cooldown_key="b84_warn_ok")
        ok_warnings = [r.getMessage() for r in caplog.records]
        assert not any("channel(s) failed" in w for w in ok_warnings), ok_warnings
        assert not any("toast backend failed" in w for w in ok_warnings), ok_warnings

    @pytest.mark.parametrize(
        "exc",
        [RuntimeError("boom"), _HardFailure("boom")],
        ids=["Exception", "BaseException"],
    )
    def test_even_a_baseexception_is_caught_and_reported(
        self, tmp_path, monkeypatch, exc
    ):
        """`except BaseException` in _run is load-bearing, not defensive.

        opus review L-2: narrowing it to `except Exception` left all 36 tests
        green, because every double raised RuntimeError. A BaseException
        escaping the worker is precisely the pre-batch-84 failure mode --
        invisible except as a pytest warning or a crash-log block -- so the
        broad catch needs a case that only it can satisfy.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        tip = _install_windows_desktop(monkeypatch, _RecordingTip(exc=exc))
        unhandled: list = []
        monkeypatch.setattr(
            threading, "excepthook", lambda args: unhandled.append(args)
        )

        assert notify.send_system_alert("t", "m", cooldown_key="b84_base") is False
        assert unhandled == [], unhandled
        # Positive control: the branch was entered and the backend invoked,
        # so the False is about the raise rather than a skipped channel.
        assert len(tip.calls) == 1

    def test_the_worker_thread_inherits_the_callers_daemon_flag(
        self, tmp_path, monkeypatch
    ):
        """Matching plyer's own bare `thread(...)` is an explicit claim.

        opus review L-1: nothing pinned it, and `daemon=True` -- a very
        natural future "don't let a toast hold the process open" edit -- left
        all 36 tests green while making the interpreter able to kill the
        worker mid-Shell_NotifyIconW at shutdown.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(monkeypatch, _RecordingTip())

        created: list = []
        real_thread = threading.Thread

        def _recording_thread(*args, **kwargs):
            worker = real_thread(*args, **kwargs)
            created.append(worker)
            return worker

        monkeypatch.setattr(notify.threading, "Thread", _recording_thread)
        notify.send_system_alert("t", "m", cooldown_key="b84_daemon")

        assert len(created) == 1, "the desktop path must spawn exactly one thread"
        assert created[0].daemon == threading.current_thread().daemon, (
            "the worker must inherit the caller's daemon flag, as plyer's own "
            "bare thread(...) does"
        )
        # Positive control: this is the toast worker and not some unrelated
        # thread the recording wrapper happened to catch.
        assert created[0].name == "kalshi-desktop-toast"

    def test_a_failure_after_the_window_is_still_logged(
        self, tmp_path, monkeypatch, caplog
    ):
        """A late failure must not vanish (opus review M-1).

        The join ALWAYS times out on the success path by construction, so a
        backend that raises after the confirm window returns True -- fine, it
        is the documented degrade. What is not fine is losing the record:
        before this item, an escaping thread exception at least reached
        main.py's threading.excepthook and `data/crash.log`. Catching it and
        appending to a list nobody re-reads would be strictly worse, so the
        warning is emitted at the catch rather than after the join.
        """
        import logging

        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(
            monkeypatch,
            _RecordingTip(exc=RuntimeError("late boom"), delay=0.1),
            confirm_secs=0.01,
        )

        with caplog.at_level(logging.WARNING, logger="notify"):
            # Reported delivered, because the window expired first...
            assert notify.send_system_alert("t", "m", cooldown_key="b84_late") is True
            # ...and yet the failure still lands in bot.log once it happens.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if any(
                    "Windows toast backend failed" in r.getMessage()
                    for r in caplog.records
                ):
                    break
                time.sleep(0.01)

        warnings = [r.getMessage() for r in caplog.records]
        assert any("Windows toast backend failed" in w for w in warnings), warnings
        assert any("late boom" in w for w in warnings), warnings
        # POSITIVE CONTROL: the "all N channel(s) failed" line must NOT be
        # here -- the call genuinely reported delivered, and this test is
        # about the log record surviving that, not about the return value
        # changing.
        assert not any("channel(s) failed" in w for w in warnings), warnings

    def test_the_backend_exception_never_escapes_the_worker_thread(
        self, tmp_path, monkeypatch
    ):
        """Reporting the failure must not merely relocate it.

        The pre-fix symptom was an exception surfacing only as pytest's
        PytestUnhandledThreadExceptionWarning (or, in production, as nothing
        at all). threading.excepthook is what that warning is built on, so
        watching it directly is watching the actual failure mode.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(monkeypatch, _RecordingTip(exc=RuntimeError("boom")))

        unhandled: list = []
        monkeypatch.setattr(
            threading, "excepthook", lambda args: unhandled.append(args)
        )

        assert notify.send_system_alert("t", "m", cooldown_key="b84_thread") is False
        assert unhandled == [], (
            f"the toast exception escaped its thread uncaught: {unhandled}"
        )

        # POSITIVE CONTROL, in two halves. First: the False above proves the
        # exception was not merely swallowed -- it was seen and reported.
        # Second: the hook really does fire for an unhandled worker
        # exception, so the empty list is evidence rather than a hook that
        # never had a chance to run.
        def _boom() -> None:
            raise RuntimeError("control")

        probe = threading.Thread(target=_boom)
        probe.start()
        probe.join()
        assert len(unhandled) == 1, "the excepthook probe itself did not work"

    def test_the_windows_path_still_truncates_for_the_struct_limits(
        self, tmp_path, monkeypatch
    ):
        """batch-80's truncation must survive moving into _desktop_notify.

        The truncation tests above all run through the plyer facade double.
        This is the same guarantee asserted on the path production actually
        takes on Windows -- without it, dropping _truncate_for_desktop from
        the balloon_tip call would leave every one of them green.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        tip = _install_windows_desktop(monkeypatch, _RecordingTip())

        notify.send_system_alert("t" * 200, "m" * 333, cooldown_key="b84_trunc")

        sent = tip.calls[0]
        assert len(sent["message"]) == notify.DESKTOP_MESSAGE_MAX
        assert len(sent["title"]) == notify.DESKTOP_TITLE_MAX
        assert sent["message"].endswith("…") and sent["title"].endswith("…")
        # Positive control: these are the real strings, clipped, not some
        # unrelated short value that happens to fit.
        assert sent["message"].startswith("mmm") and sent["title"].startswith("ttt")
        # opus review L-3: the rest of the payload was unasserted, so
        # `"timeout": 0` left all 291 alerting tests green. It is not
        # cosmetic -- WindowsBalloonTip.__init__ skips its `if timeout:
        # time.sleep(timeout)`, the instance goes unreferenced, __del__ runs
        # remove_notify(), and the toast is torn down before it can be read.
        assert sent["timeout"] == 10

    def test_alert_strong_signal_uses_the_same_confirmed_path(
        self, tmp_path, monkeypatch, caplog
    ):
        """The second _notif.notify() call site had the identical defect."""
        import logging

        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        tip = _install_windows_desktop(
            monkeypatch, _RecordingTip(exc=RuntimeError("boom"))
        )
        monkeypatch.setattr(notify, "_last_notified", {})

        with caplog.at_level(logging.WARNING, logger="notify"):
            notify.alert_strong_signal(
                ticker="KXHIGH-NYC-1", city="NYC", side="yes", net_edge=0.2, kelly=0.1
            )

        warnings = [r.getMessage() for r in caplog.records]
        assert any("all 1 channel(s) failed for KXHIGH-NYC-1" in w for w in warnings), (
            warnings
        )
        # POSITIVE CONTROL: the desktop branch was actually entered with this
        # signal's own text, so the warning is about a real failed attempt.
        assert len(tip.calls) == 1
        assert "KXHIGH-NYC-1" in tip.calls[0]["title"]

    def test_a_non_windows_backend_still_goes_through_the_plyer_facade(
        self, tmp_path, monkeypatch
    ):
        """macOS and Linux need none of this -- their _notify is synchronous.

        OSXNotification._notify and all three Linux implementations call
        their backend inline, so plyer's own exception already reaches the
        caller's except. _WIN_BALLOON_TIP is None there and behaviour is
        unchanged from before this item.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        fake = _install_desktop_only(monkeypatch)

        status, n_ok, _ = notify.send_system_alert_detailed(
            "t", "m" * 333, cooldown_key="b84_facade"
        )
        assert (status, n_ok) == ("delivered", 1)
        # Positive control: the facade really was the thing called, with the
        # truncated payload.
        assert len(fake.kwargs["message"]) == notify.DESKTOP_MESSAGE_MAX

        # And a synchronous backend that raises is still reported as failed,
        # by the caller's own except -- the path that always worked.
        class _RaisingNotif:
            def notify(self, **kwargs) -> None:
                raise RuntimeError("dbus is not running")

        monkeypatch.setattr(notify, "_notif", _RaisingNotif())
        failed = notify.send_system_alert_detailed(
            "t", "m", cooldown_key="b84_facade_bad"
        )
        assert failed[0] == "failed"

    def test_resolve_win_balloon_tip_matches_the_installed_plyer(self):
        """The load-bearing test: the injection point is the real backend.

        Every test above hands _WIN_BALLOON_TIP a double. If
        _resolve_win_balloon_tip() ever stopped returning plyer's real
        balloon_tip on Windows -- a renamed private module after an upgrade,
        a platform token that no longer matches -- production would silently
        fall back to the fire-and-forget facade and reinstate the phantom
        True, with every double-based test still green.

        Asserted from both sides so it is meaningful on the ubuntu CI job as
        well as on the Windows one and this project's Windows dev machine.
        """
        from plyer.utils import platform as plyer_platform

        resolved = notify._resolve_win_balloon_tip()
        if str(plyer_platform) == "win":
            from plyer.platforms.win.libs.balloontip import balloon_tip

            assert resolved is balloon_tip
            assert notify._WIN_BALLOON_TIP is balloon_tip, (
                "the module-level resolution must agree with the function"
            )
        else:
            assert resolved is None
            assert notify._WIN_BALLOON_TIP is None

    def test_a_non_windows_platform_resolves_to_none_without_warning(
        self, monkeypatch, caplog
    ):
        """The `!= "win"` guard is about log hygiene, and is now pinned.

        opus review I-4: deleting the guard leaves Windows unchanged and, on
        a non-Windows host, turns a clean None into None PLUS a spurious
        import-time WARNING about a backend that host was never going to
        use. Nothing tested it, and the ubuntu CI job cannot -- it only ever
        runs the `else` branch of the test above, which a broken resolver
        satisfies too. Faking the platform token exercises the guard from a
        Windows machine.
        """
        import logging

        import plyer.utils

        monkeypatch.setattr(plyer.utils, "platform", "linux")
        with caplog.at_level(logging.WARNING, logger="notify"):
            assert notify._resolve_win_balloon_tip() is None
        assert not any("balloon_tip" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records
        ]

        # POSITIVE CONTROL: the WARNING path is reachable, so its absence
        # above is the guard's doing and not a logger that never fires.
        # "win" gets past the guard, then the import itself fails.
        monkeypatch.setattr(plyer.utils, "platform", "win")
        monkeypatch.setitem(sys.modules, "plyer.platforms.win.libs.balloontip", None)
        with caplog.at_level(logging.WARNING, logger="notify"):
            assert notify._resolve_win_balloon_tip() is None
        assert any("balloon_tip" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records
        ]

    def test_a_slow_but_working_toast_is_not_reported_as_a_failure(
        self, tmp_path, monkeypatch
    ):
        """DESKTOP_CONFIRM_SECS is a failure-detection window, not a deadline.

        WindowsBalloonTip.__init__ sleeps `timeout` (10s here) AFTER its Win32
        work succeeds, so a successful call is still running when the join
        expires, by construction. Not-finished must therefore mean delivered
        -- and a backend slow enough to push a genuine failure past the
        window degrades to the pre-fix behaviour, never to spam.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(
            monkeypatch, _RecordingTip(delay=0.4), confirm_secs=0.01
        )
        assert notify.send_system_alert("t", "m", cooldown_key="b84_slow") is True

        # POSITIVE CONTROL: with the SAME tiny window, a backend that fails
        # immediately is still caught -- so the True above is about the thread
        # still running rather than about the window being too short to
        # observe anything at all.
        _install_windows_desktop(
            monkeypatch, _RecordingTip(exc=RuntimeError("boom")), confirm_secs=0.01
        )
        assert notify.send_system_alert("t", "m", cooldown_key="b84_slow_bad") is False

    def test_the_confirm_window_is_what_makes_a_failure_observable(
        self, tmp_path, monkeypatch
    ):
        """The join duration is load-bearing, not decoration.

        Mutating ``worker.join(DESKTOP_CONFIRM_SECS)`` to ``worker.join(0)``
        left every other test in this class green: their doubles raise so
        fast that Thread.start()'s own handshake is usually enough for the
        exception to already be recorded. That is a race, not a proof. This
        double raises only after a delay no zero-length window can span, so
        it fails the moment the wait is removed or shortened to nothing.
        """
        monkeypatch.setattr(
            notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "notify_cooldowns.json"
        )
        _install_windows_desktop(
            monkeypatch,
            _RecordingTip(exc=RuntimeError("boom"), delay=0.15),
            confirm_secs=2.0,
        )
        assert notify.send_system_alert("t", "m", cooldown_key="b84_window") is False

        # POSITIVE CONTROL: the SAME double with no window at all is reported
        # as delivered, so the False above is produced by the wait rather
        # than by a failure that was observable regardless.
        _install_windows_desktop(
            monkeypatch,
            _RecordingTip(exc=RuntimeError("boom"), delay=0.15),
            confirm_secs=0.0,
        )
        assert notify.send_system_alert("t", "m", cooldown_key="b84_nowindow") is True

    def test_the_confirm_window_is_pinned(self):
        """Reasoned from the backend's own timings; a change should be a
        deliberate one that updates this line.

        Every observable failure raises inside ctypes/Win32 calls that
        complete in well under a millisecond, so 0.5s is orders of magnitude
        of headroom; the upper bound keeps a careless edit from turning each
        alert into a multi-second stall on the cron path.
        """
        assert notify.DESKTOP_CONFIRM_SECS == 0.5
        assert 0 < notify.DESKTOP_CONFIRM_SECS <= 2.0
