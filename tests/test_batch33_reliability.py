"""Tests for batch-33: cron, alerting & backup reliability.

- M-1: alerts.rollback_halt_transition + notify.send_system_alert's return
  value (cron.py/order_executor.py wiring is covered in
  tests/test_cron_integration.py, which has the cron_env fixture).
- M-3: cron._acquire_cron_lock's started_at fail-open default (release-side
  ownership-check fix is covered in tests/test_cron_lock.py, which already
  owns that fixture setup).
- M-6: trade_cycle.py's --sameday-only shadow-observation skip.
- M-21: cloud_backup.py's prune UTC-vs-local mismatch, rmtree isolation,
  and restore_data's nested pre-restore snapshot exclusion.
- M-28: notify.py's Discord webhook URL redaction.
- L-4: notify.py's NOTIFY_CHANNELS strip/lower + unknown-channel warning.
"""

from __future__ import annotations

import json
from unittest.mock import patch

_NOW = 1_800_000_000.0


# ── M-1: alerts.rollback_halt_transition ────────────────────────────────────


class TestRollbackHaltTransition:
    def _path(self, tmp_path):
        return tmp_path / "halt_transitions.json"

    def test_rollback_resets_flag_and_next_check_reports_fresh_edge(
        self, tmp_path, monkeypatch
    ):
        """Mutation-relevant: the whole point of rollback is that the NEXT
        cycle's observation is treated as a fresh transition again -- prove
        it end to end, not just that the file's value changed."""
        import alerts

        path = self._path(tmp_path)
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        assert alerts.check_halt_transition("anomaly", True) is True
        assert alerts.check_halt_transition("anomaly", True) is False, (
            "sanity: same-cycle-style repeat observation is not a fresh edge"
        )

        alerts.rollback_halt_transition("anomaly")

        assert alerts.check_halt_transition("anomaly", True) is True, (
            "after rollback, the still-active halt must report a fresh "
            "edge again on the next observation"
        )

    def test_rollback_does_not_clobber_other_halt_types(self, tmp_path, monkeypatch):
        """Positive control pairing test_rollback_resets_flag...: rolling
        back "anomaly" must not blank-overwrite "drawdown"'s own
        independently-persisted True flag -- same clobber hazard
        check_halt_transition's own read-failure branch already guards
        against."""
        import alerts

        path = self._path(tmp_path)
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        alerts.check_halt_transition("drawdown", True)
        alerts.check_halt_transition("anomaly", True)

        alerts.rollback_halt_transition("anomaly")

        state = json.loads(path.read_text())
        assert state["drawdown"] is True, (
            "rolling back one halt_type's flag must not touch another's"
        )
        assert state["anomaly"] is False

    def test_rollback_is_silent_noop_on_unreadable_state(self, tmp_path, monkeypatch):
        """Best-effort: an unreadable state file must not raise, and must
        not be blindly overwritten with a blank dict (same clobber
        reasoning as above)."""
        import alerts

        path = self._path(tmp_path)
        path.write_text("not valid json {{{{")
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        alerts.rollback_halt_transition("anomaly")  # must not raise

        assert path.read_text() == "not valid json {{{{", (
            "an unreadable file must be left untouched, not overwritten"
        )


# ── M-1: notify.send_system_alert's return value ────────────────────────────


class TestSendSystemAlertReturnValue:
    def _path(self, tmp_path):
        return tmp_path / "notify_cooldowns.json"

    def test_returns_true_on_successful_delivery(self, tmp_path, monkeypatch):
        import notify

        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", self._path(tmp_path))
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        monkeypatch.setattr(notify, "_send_discord", lambda *a, **k: True)

        assert notify.send_system_alert("t", "m", cooldown_key="k") is True

    def test_returns_false_on_total_delivery_failure(self, tmp_path, monkeypatch):
        import notify

        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", self._path(tmp_path))
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        monkeypatch.setattr(notify, "_send_discord", lambda *a, **k: False)

        assert notify.send_system_alert("t", "m", cooldown_key="k") is False

    def test_returns_true_when_cooldown_suppresses_delivery_attempt(
        self, tmp_path, monkeypatch
    ):
        """A second call within the cooldown window doesn't attempt
        delivery at all -- must report True (nothing was left undelivered
        BY THIS CALL), not False, or a halt-transition caller using this
        return to gate a rollback would wrongly roll back an already-
        successfully-delivered engagement just because a later, routine
        cooldown-suppressed call happened to observe the same key."""
        import notify

        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", self._path(tmp_path))
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        monkeypatch.setattr(notify, "_send_discord", lambda *a, **k: True)

        assert notify.send_system_alert("t1", "m1", cooldown_key="k") is True
        assert notify.send_system_alert("t2", "m2", cooldown_key="k") is True


# ── M-3: cron._acquire_cron_lock's started_at fail-open default ─────────────


class TestAcquireCronLockStartedAtDefault:
    def test_missing_started_at_treated_as_fresh_not_epoch(self, tmp_path, monkeypatch):
        """batch-33 L-6b: a valid-JSON lock missing the started_at key used
        to default to 0 (the epoch, ~56 years old), which the no-psutil
        fallback's age check compared against _STALE_LOCK_AGE_SECS (1800s)
        -- always "ancient", always overridden, even for a lock some OTHER
        process wrote moments ago. Defaulting to the lock FILE's own mtime
        means a lock just written moments ago (mtime ~= now) fails closed
        toward NOT overriding.

        Mutation-relevant: reverting the `lp.stat().st_mtime` default back
        to `existing.get("started_at", 0)` makes this fail (the lock gets
        overridden instead of blocked).
        """
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        # Valid JSON, no "started_at" key at all -- e.g. a hand-edited file.
        lock_path.write_text(json.dumps({"pid": 424242}))

        with patch.object(cron, "_PSUTIL_AVAILABLE", False):
            result = cron._acquire_cron_lock()

        assert result is False, (
            "an unknown-age lock must be treated as fresh (mtime ~= now) "
            "and block acquisition, not be treated as ancient and overridden"
        )

    def test_is_cron_running_missing_started_at_treated_as_fresh(
        self, tmp_path, monkeypatch
    ):
        """Same fix, _is_cron_running's own no-psutil branch (the pairing
        this function's docstring documents with _acquire_cron_lock's)."""
        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        lock_path.write_text(json.dumps({"pid": 424242}))

        with patch.object(cron, "_PSUTIL_AVAILABLE", False):
            result = cron._is_cron_running()

        assert result is True, (
            "an unknown-age lock must read as currently running (fresh), "
            "not as stale/not-running"
        )

    def test_old_lock_missing_started_at_still_self_heals(self, tmp_path, monkeypatch):
        """Opus-review-caught regression: an EARLIER version of this fix
        defaulted started_at to a fresh `_time.time()` call, recomputed on
        EVERY read -- so a lock file permanently missing the key reported
        age ~0 forever, and the 24h self-heal backstop
        (_STUCK_RUNNING_BACKSTOP_SECS) could never fire for it. Reproduced
        live: "lock held by live PID N (started 0s ago) -- skipping" on
        every single acquire attempt, permanent lockout with no escape --
        exactly the failure mode this whole self-heal exists to prevent.

        Using the lock FILE's own mtime as the default instead means a
        GENUINELY old, abandoned lock (mtime far in the past) still ages
        normally and the backstop can still fire. This test simulates that
        exact scenario: a live, not-reused PID (so the age check is
        actually reached) with no started_at key and an old mtime.

        Mutation-relevant: reverting to `_time.time()` (recomputed every
        read) instead of `lp.stat().st_mtime` makes this fail -- the lock
        would never be overridden no matter how old the file actually is.
        """
        import os as _os
        import time as _time

        import cron

        lock_path = tmp_path / ".cron_lock"
        monkeypatch.setattr(cron, "LOCK_PATH", lock_path)
        # Valid JSON, live PID, no started_at/create_time -- old-format,
        # hand-edited-looking lock.
        lock_path.write_text(json.dumps({"pid": _os.getpid()}))
        old_mtime = _time.time() - cron._STUCK_RUNNING_BACKSTOP_SECS - 3600
        _os.utime(lock_path, (old_mtime, old_mtime))

        with (
            patch.object(cron, "_PSUTIL_AVAILABLE", True),
            patch.object(cron, "_psutil") as mock_psutil,
        ):
            mock_psutil.pid_exists.return_value = True
            # No create_time recorded -> _cron_lock_pid_reused can't
            # positively confirm reuse either way -> falls through to the
            # age-based backstop, the exact branch under test.
            result = cron._acquire_cron_lock()

        assert result is True, (
            "a genuinely old lock (file mtime far past the self-heal "
            "backstop) missing started_at must still be overridable -- "
            "the backstop must not be permanently disabled just because "
            "the field is absent"
        )


# M-6 (trade_cycle.py's --sameday-only shadow-observation skip) is covered
# in tests/test_trade_cycle_engine.py instead, which already owns the
# engine_env fixture run_trade_cycle() needs for a real (non-mocked-away)
# ctx.


# ── M-21: cloud_backup.py ────────────────────────────────────────────────────


class TestBackupPruneUsesUtc:
    def test_prune_compares_utc_to_utc(self, tmp_path, monkeypatch):
        """batch-33 M-21 LOW(a): directory names are stamped with
        datetime.now(UTC) but pruning used to compare them against
        date.today() (LOCAL time). Simulate the exact divergent-timezone
        case: a directory dated "today" in UTC that would read as
        yesterday (i.e. within the 30-day window either way) under a
        local time far behind UTC -- must not be pruned regardless of the
        local clock, since UTC-to-UTC puts it at 0 days old.
        """
        from datetime import UTC, datetime

        import cloud_backup

        sync_root = tmp_path / "sync"
        backup_root = sync_root / "KalshiBot" / "data"
        today_utc_str = datetime.now(UTC).strftime("%Y-%m-%d")
        old_dir = backup_root / today_utc_str
        old_dir.mkdir(parents=True)
        (old_dir / "marker.json").write_text("{}")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "sample.json").write_text("{}")

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            with patch("safe_io.backup_sqlite_db", return_value=True):
                result = cloud_backup.backup_data(data_dir=data_dir)

        assert result is True
        assert old_dir.exists(), (
            "a directory dated with today's UTC date must never be pruned "
            "by this same backup_data() call, regardless of local clock"
        )


class TestBackupPruneIsolatesRmtreeFailure:
    def test_rmtree_failure_does_not_flip_a_good_backup_to_false(
        self, tmp_path, monkeypatch
    ):
        """batch-33 M-21 LOW(a): an rmtree failure while pruning an old
        backup dir used to be uncaught, propagating to the outer
        `except Exception: return False` -- turning a backup run that
        copied every file successfully into a reported FAILURE over an
        unrelated old directory. Mutation-relevant: removing the inner
        try/except around shutil.rmtree makes this fail (result becomes
        False instead of True).
        """
        import shutil
        from datetime import UTC, datetime, timedelta

        import cloud_backup

        sync_root = tmp_path / "sync"
        backup_root = sync_root / "KalshiBot" / "data"
        old_date = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%d")
        old_dir = backup_root / old_date
        old_dir.mkdir(parents=True)
        (old_dir / "marker.json").write_text("{}")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "sample.json").write_text("{}")

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            with patch.object(
                shutil, "rmtree", side_effect=OSError("simulated permission error")
            ):
                result = cloud_backup.backup_data(data_dir=data_dir)

        assert result is True, (
            "a real, successful backup must not be reported as failed just "
            "because pruning an unrelated old directory hit an OSError"
        )
        assert old_dir.exists(), "the directory that failed to prune is still there"


class TestRestoreSnapshotExcludesRecoveryDirs:
    def test_snapshot_excludes_prior_pre_restore_dirs(self, tmp_path):
        """batch-33 M-21 LOW(b): snapshot_dir lives INSIDE data_dir, so a
        naive copytree also copies every PRIOR .pre_restore_* snapshot
        into the new one -- nesting without bound across repeated
        restores. Also excludes safe_io's own .history/.emergency
        directories, which are recovery copies in their own right, not
        live data worth re-snapshotting inside another snapshot.
        """
        import cloud_backup

        sync_root = tmp_path / "sync"
        backup_root = sync_root / "KalshiBot" / "data" / "2026-01-01"
        backup_root.mkdir(parents=True)
        (backup_root / "sample.json").write_text("{}")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "live.json").write_text("{}")
        prior_snapshot = data_dir / ".pre_restore_20260101T000000"
        prior_snapshot.mkdir()
        (prior_snapshot / "leftover.json").write_text("{}")
        history_dir = data_dir / ".history"
        history_dir.mkdir()
        (history_dir / "live_20260101T000000.json").write_text("{}")

        with patch.object(cloud_backup, "_find_sync_folder", return_value=sync_root):
            cloud_backup.restore_data(data_dir=data_dir, confirm=True)

        new_snapshots = [
            d for d in data_dir.glob(".pre_restore_*") if d != prior_snapshot
        ]
        assert len(new_snapshots) == 1, (
            f"expected exactly one new snapshot dir, found {new_snapshots}"
        )
        new_snapshot = new_snapshots[0]
        assert not (new_snapshot / ".pre_restore_20260101T000000").exists(), (
            "the new snapshot must not nest the prior .pre_restore_* dir"
        )
        assert not (new_snapshot / ".history").exists(), (
            "the new snapshot must not include safe_io's .history dir"
        )
        assert (new_snapshot / "live.json").exists(), (
            "positive control: real live data files must still be snapshotted"
        )


# ── M-28: notify.py's Discord webhook URL redaction ─────────────────────────


class TestDiscordWebhookRedaction:
    def test_redact_webhook_url_strips_token(self):
        import notify

        url = "https://discord.com/api/webhooks/123456789/supersecrettoken"
        redacted = notify._redact_webhook_url(url)

        assert "supersecrettoken" not in redacted
        assert "123456789"[:8] in redacted or "12345678" in redacted
        assert redacted.startswith("https://discord.com/")

    def test_redact_webhook_url_handles_empty_string(self):
        """opus-review-caught: an empty url must short-circuit to a fixed
        marker rather than reach the urlsplit/f-string path -- guards a
        caller (any future one, not _send_discord's own current filtered
        list) from `str(exc).replace("", redacted)`, which would insert
        the marker between every character of the exception message
        (str.replace's documented behavior for an empty `old` argument)."""
        import notify

        assert notify._redact_webhook_url("") == "<redacted>"

    def test_send_discord_failure_never_logs_raw_url_or_token(
        self, tmp_path, monkeypatch, caplog
    ):
        """Mutation-relevant: reverting the log call back to `%s, url, exc`
        (no redaction) makes this fail -- the secret token would appear in
        caplog's captured text."""
        import logging

        import notify

        secret_token = "sekrit_bearer_token_xyz"
        url = f"https://discord.com/api/webhooks/999999/{secret_token}"
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", url)
        monkeypatch.setattr(notify, "_DISCORD_AVAILABLE", True)

        class _FakeRequests:
            @staticmethod
            def post(u, json=None, timeout=None):
                # Simulate requests' own exception text embedding the url.
                raise ConnectionError(f"failed to connect to {u}")

        monkeypatch.setattr(notify, "_requests", _FakeRequests)

        with caplog.at_level(logging.WARNING, logger="notify"):
            result = notify._send_discord("t", "m")

        assert result is False
        assert secret_token not in caplog.text, (
            f"the raw bearer token must never reach the log: {caplog.text!r}"
        )
        assert url not in caplog.text


# ── L-4: notify.py's NOTIFY_CHANNELS parsing ────────────────────────────────


class TestNotifyChannelsParsing:
    def test_strips_whitespace_and_lowercases_tokens(self, monkeypatch):
        """Mutation-relevant: reverting to a bare `.split(",")` with no
        strip/lower makes this fail -- ' Email' (leading space, mixed
        case) would survive as its own literal member instead of
        normalizing to 'email', so `"email" in _CHANNELS` would be False.
        """
        import importlib

        import notify

        monkeypatch.setenv("NOTIFY_CHANNELS", "Discord, Email , NTFY")
        importlib.reload(notify)
        try:
            assert notify._CHANNELS == {"discord", "email", "ntfy"}
        finally:
            monkeypatch.delenv("NOTIFY_CHANNELS", raising=False)
            importlib.reload(notify)

    def test_unknown_channel_name_is_logged(self, monkeypatch, caplog):
        import importlib
        import logging

        import notify

        monkeypatch.setenv("NOTIFY_CHANNELS", "discord,carrier_pigeon")
        with caplog.at_level(logging.WARNING, logger="notify"):
            importlib.reload(notify)
        try:
            assert "carrier_pigeon" in caplog.text
        finally:
            monkeypatch.delenv("NOTIFY_CHANNELS", raising=False)
            importlib.reload(notify)
