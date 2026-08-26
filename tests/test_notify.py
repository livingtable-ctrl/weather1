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
    return fake


class TestDesktopFieldTruncation:
    """The desktop toast's fixed-width struct fields must never be overrun.

    plyer's Windows backend runs balloon_tip on a thread it spawns itself
    (WindowsNotification._notify is `thread(target=balloon_tip, ...).start()`),
    so a ValueError raised in there cannot be caught by notify.py -- it
    escapes uncaught and the desktop half of the alert is lost with no
    record. Not handing plyer an over-long string is the only control this
    module has, which is why these tests assert on the ARGUMENTS passed to
    plyer rather than on an exception being handled.
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
