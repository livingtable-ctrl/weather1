"""Tests for batch-24: alerting & notification reliability.

- item 2: notify.py's empty-successes-list warning-guard bug (ntfy
  configured without NTFY_TOPIC), and activate_black_swan_halt's channel
  routing (alerts.py).
- item 3: notify.send_system_alert's cooldown must not be consumed until
  delivery is attempted -- a total-failure alert must roll the cooldown
  reservation back.
- item 4: alerts.check_halt_transition's false->true edge tracking.
- item 5: utils.balance_dollars, and its 3 call sites.

Kill-switch alerting + dead-man's-switch ordering (item 1) and the
daily-loss/drawdown pre-cycle observation (item 4, cron.py) are covered in
tests/test_cron_integration.py instead, since they need the full cron_env
integration fixture.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

_NOW = 1_800_000_000.0
_SIX_HOURS = 21_600


# ── item 5: utils.balance_dollars ───────────────────────────────────────────


class TestBalanceDollars:
    def test_int_cents(self):
        from utils import balance_dollars

        assert balance_dollars({"balance": 123456}) == pytest.approx(1234.56)

    def test_float_cents(self):
        from utils import balance_dollars

        assert balance_dollars({"balance": 100.0}) == pytest.approx(1.00)

    def test_numeric_string(self):
        from utils import balance_dollars

        assert balance_dollars({"balance": "50000"}) == pytest.approx(500.00)

    def test_zero_balance(self):
        from utils import balance_dollars

        assert balance_dollars({"balance": 0}) == pytest.approx(0.0)

    def test_missing_balance_key_raises(self):
        """The exact output_formatters.cmd_balance bug this consolidates:
        `data.get("balance", data)` used to fall back to the WHOLE payload
        dict when the key was absent, which float()'d into a TypeError.
        The shared helper raises a clean, catchable ValueError instead."""
        from utils import balance_dollars

        with pytest.raises(ValueError, match="missing 'balance' key"):
            balance_dollars({"some_other_field": 1})

    def test_dict_shaped_balance_raises_value_error_not_type_error(self):
        """Mutation-relevant: a naive `float(balance)` on a dict-shaped
        value raises TypeError, not ValueError -- callers written to catch
        ValueError specifically (or generic Exception) must see a
        ValueError here, proving the fix isn't just "the same TypeError
        renamed in a docstring"."""
        from utils import balance_dollars

        with pytest.raises(ValueError):
            balance_dollars({"balance": {"nested": "dict"}})

    def test_bool_balance_raises(self):
        """bool is a subclass of int in Python -- must be explicitly
        rejected, not silently accepted as 0 or 1 cents."""
        from utils import balance_dollars

        with pytest.raises(ValueError):
            balance_dollars({"balance": True})

    def test_non_numeric_string_raises(self):
        from utils import balance_dollars

        with pytest.raises(ValueError, match="not numeric"):
            balance_dollars({"balance": "not-a-number"})

    def test_none_balance_raises(self):
        from utils import balance_dollars

        with pytest.raises(ValueError):
            balance_dollars({"balance": None})

    @pytest.mark.parametrize(
        "bad_value", ["nan", "inf", "-inf", float("nan"), float("inf")]
    )
    def test_non_finite_balance_raises(self, bad_value):
        """opus-review-caught (2nd round, LOW-6): float("nan")/float("inf")
        do NOT raise ValueError, so a payload of {"balance": "nan"} (or a
        literal float nan/inf) used to silently return nan/inf dollars,
        which then flows into live Kelly sizing where a `<= 0` fallback
        check wouldn't catch it either (nan/inf are both `> 0` under
        Python's comparison semantics)."""
        from utils import balance_dollars

        with pytest.raises(ValueError, match="not finite"):
            balance_dollars({"balance": bad_value})

    @pytest.mark.parametrize("payload", [None, 123, ["balance"], "balance", []])
    def test_non_dict_payload_raises_value_error_not_type_error(self, payload):
        """opus-review-caught (F2): the ORIGINAL fix still did
        `"balance" not in payload` unguarded, which raises TypeError (not
        ValueError) for a non-dict payload -- exactly the exception type
        the docstring promises this function never raises, and exactly the
        type cmd_balance's `except ValueError` wouldn't catch."""
        from utils import balance_dollars

        with pytest.raises(ValueError):
            balance_dollars(payload)


class TestBalanceDollarsCallSites:
    def test_resolve_live_balance_falls_back_on_malformed_payload(self):
        """order_executor._resolve_live_balance already wraps the whole
        fetch+convert in try/except Exception -- the new ValueError from
        balance_dollars() must be caught by that existing handler and fall
        back to 0.0, not propagate and crash a live sizing call."""
        from unittest.mock import MagicMock

        import order_executor

        client = MagicMock()
        client.get_balance.return_value = {"balance": {"unexpected": "shape"}}
        assert order_executor._resolve_live_balance(client) == 0.0

    def test_resolve_live_balance_converts_valid_payload(self):
        from unittest.mock import MagicMock

        import order_executor

        client = MagicMock()
        client.get_balance.return_value = {"balance": 250000}
        assert order_executor._resolve_live_balance(client) == pytest.approx(2500.00)

    def test_run_black_swan_check_does_not_crash_on_malformed_balance(self):
        """alerts.run_black_swan_check's balance-fetch is already wrapped
        in its own try/except -- must degrade to the ORIGINAL paper-state
        balance argument, not raise, when the live payload is malformed.

        opus-review-caught (T1): an earlier version of this test only
        asserted the mocked check_black_swan_conditions return value came
        back unchanged, which proves nothing about what balance value was
        actually used internally -- it would pass identically even if the
        malformed payload's garbage value silently propagated into the
        real check. Spies on check_black_swan_conditions's call args
        instead to verify the ACTUAL degrade-to-paper-balance behavior."""
        from unittest.mock import MagicMock

        import alerts

        client = MagicMock()
        client.get_balance.return_value = {"balance": "not-a-number"}
        with patch.object(
            alerts, "check_black_swan_conditions", return_value=[]
        ) as mock_check:
            alerts.run_black_swan_check(
                trades=[], balance=1000.0, peak_balance=1000.0, client=client
            )
        assert mock_check.call_count == 1
        called_balance = mock_check.call_args[0][1]
        assert called_balance == 1000.0, (
            f"expected the malformed live balance to be discarded and the "
            f"original paper balance (1000.0) used instead, got: {called_balance!r}"
        )

    def test_run_black_swan_check_uses_real_live_balance_when_valid(self):
        """Positive control: with a well-formed live balance, the REAL
        converted value (not the paper fallback) is what reaches the
        check -- proves the test above isn't just checking that SOME
        number gets through."""
        from unittest.mock import MagicMock

        import alerts

        client = MagicMock()
        client.get_balance.return_value = {"balance": 250000}  # $2500.00
        with patch.object(
            alerts, "check_black_swan_conditions", return_value=[]
        ) as mock_check:
            alerts.run_black_swan_check(
                trades=[], balance=1000.0, peak_balance=1000.0, client=client
            )
        called_balance = mock_check.call_args[0][1]
        assert called_balance == pytest.approx(2500.00)

    def test_cmd_balance_prints_error_instead_of_crashing_on_malformed_payload(
        self, capsys
    ):
        """output_formatters.cmd_balance had NO try/except around the
        balance fetch/convert at all -- a malformed payload's TypeError
        used to propagate uncaught and crash the CLI command. Must now
        print an error and return cleanly."""
        from unittest.mock import MagicMock

        import output_formatters

        client = MagicMock()
        client.get_balance.return_value = {"unexpected_shape": True}
        with patch("main.validate_api_key", return_value=True):
            output_formatters.cmd_balance(client)

        out = capsys.readouterr().out
        assert "malformed" in out.lower()

    def test_cmd_balance_displays_valid_balance(self, capsys):
        from unittest.mock import MagicMock

        import output_formatters

        client = MagicMock()
        client.get_balance.return_value = {"balance": 100000}
        with patch("main.validate_api_key", return_value=True):
            with patch("paper.get_balance", return_value=500.0):
                output_formatters.cmd_balance(client)

        out = capsys.readouterr().out
        assert "1000.00" in out

    def test_cmd_balance_survives_get_balance_network_error(self, capsys):
        """opus-review-caught (F2): client.get_balance() itself used to sit
        OUTSIDE the try/except -- a network error from the fetch (not just
        a malformed response) still crashed the CLI command uncaught."""
        from unittest.mock import MagicMock

        import output_formatters

        client = MagicMock()
        client.get_balance.side_effect = ConnectionError("network unreachable")
        with patch("main.validate_api_key", return_value=True):
            output_formatters.cmd_balance(client)  # must not raise

        out = capsys.readouterr().out
        assert "unavailable" in out.lower() or "malformed" in out.lower()

    def test_cmd_balance_survives_non_dict_response(self, capsys):
        """opus-review-caught (F2): a non-dict get_balance() response (e.g.
        the raw API returning a list or None on a degraded endpoint) used
        to raise TypeError, which cmd_balance's `except ValueError` did not
        catch."""
        from unittest.mock import MagicMock

        import output_formatters

        client = MagicMock()
        client.get_balance.return_value = None
        with patch("main.validate_api_key", return_value=True):
            output_formatters.cmd_balance(client)  # must not raise

        out = capsys.readouterr().out
        assert "unavailable" in out.lower() or "malformed" in out.lower()


# ── item 3: notify.py cooldown consumed before delivery ─────────────────────


class TestSystemCooldownReserveRollback:
    def _path(self, tmp_path):
        return tmp_path / "notify_cooldowns.json"

    def test_reserve_elapsed_key_persists_immediately(self, tmp_path, monkeypatch):
        import notify

        path = self._path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        reserved, previous = notify._system_cooldown_reserve(
            "k", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert reserved is True
        assert previous == 0.0
        import json

        assert json.loads(path.read_text()) == {"k": _NOW}

    def test_reserve_within_cooldown_is_not_reserved(self, tmp_path, monkeypatch):
        import notify

        path = self._path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify._system_cooldown_reserve("k", now=_NOW, cooldown_secs=_SIX_HOURS)
        reserved, previous = notify._system_cooldown_reserve(
            "k", now=_NOW + 3600, cooldown_secs=_SIX_HOURS
        )
        assert reserved is False
        assert previous == _NOW

    def test_rollback_restores_previous_value(self, tmp_path, monkeypatch):
        import json

        import notify

        path = self._path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify._system_cooldown_reserve("k", now=_NOW - 100_000, cooldown_secs=1.0)
        reserved, previous = notify._system_cooldown_reserve(
            "k", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert reserved is True

        notify._system_cooldown_rollback(
            "k", reserved_value=_NOW, previous_value=previous
        )
        state = json.loads(path.read_text())
        assert state["k"] == pytest.approx(_NOW - 100_000), (
            "rollback must restore the PRIOR timestamp, not just clear the key"
        )

    def test_rollback_removes_key_when_never_previously_fired(
        self, tmp_path, monkeypatch
    ):
        import json

        import notify

        path = self._path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify._system_cooldown_reserve("k", now=_NOW, cooldown_secs=_SIX_HOURS)
        notify._system_cooldown_rollback("k", reserved_value=_NOW, previous_value=0.0)

        assert "k" not in json.loads(path.read_text())

    def test_rollback_after_immediate_retry_lets_it_fire_again(
        self, tmp_path, monkeypatch
    ):
        """The actual regression this fixes: a total-delivery-failure call
        must NOT burn the cooldown -- an immediately-following call (same
        instant) must still be able to reserve and fire."""
        import notify

        path = self._path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        reserved, previous = notify._system_cooldown_reserve(
            "k", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert reserved is True
        notify._system_cooldown_rollback(
            "k", reserved_value=_NOW, previous_value=previous
        )

        reserved_again, _ = notify._system_cooldown_reserve(
            "k", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert reserved_again is True, (
            "a rolled-back reservation must not block an immediate retry"
        )

    def test_reserve_with_corrupt_non_numeric_value_fails_open(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught (2nd round, MEDIUM-1): a hand-edited or
        otherwise corrupt non-numeric persisted value used to raise
        TypeError out of `now - last`, breaking send_system_alert()'s
        documented "Never raises" contract that 3 of this diff's new
        call sites (cron.py/trade_cycle.py/main.py's kill-switch checks)
        rely on without their own wrapping. Must fail open instead."""
        import json

        import notify

        path = tmp_path / "notify_cooldowns.json"
        path.write_text(json.dumps({"k": "not-a-number"}))
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        reserved, previous = notify._system_cooldown_reserve(
            "k", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert reserved is True
        assert previous == 0.0

    def test_reserve_with_corrupt_bool_value_fails_open(self, tmp_path, monkeypatch):
        """bool is a subclass of int -- must be explicitly rejected too, not
        silently treated as a valid timestamp of 0 or 1."""
        import json

        import notify

        path = tmp_path / "notify_cooldowns.json"
        path.write_text(json.dumps({"k": True}))
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        reserved, previous = notify._system_cooldown_reserve(
            "k", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        assert reserved is True
        assert previous == 0.0

    def test_rollback_is_noop_if_a_newer_reservation_exists(
        self, tmp_path, monkeypatch
    ):
        """Concurrency guard: if some OTHER call has since reserved a newer
        timestamp for the same key (a legitimate later alert), a stale
        rollback must not clobber it."""
        import json

        import notify

        path = self._path(tmp_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify._system_cooldown_reserve("k", now=_NOW, cooldown_secs=1.0)
        # A later, independent reservation supersedes the first (10s later,
        # with the SAME short 1s cooldown, so it's elapsed again by then).
        notify._system_cooldown_reserve("k", now=_NOW + 10, cooldown_secs=1.0)

        # Stale rollback referencing the FIRST reservation's value.
        notify._system_cooldown_rollback("k", reserved_value=_NOW, previous_value=0.0)

        assert json.loads(path.read_text())["k"] == _NOW + 10


class TestSendSystemAlertCooldownNotBurnedOnFailure:
    def test_total_channel_failure_does_not_burn_cooldown(self, tmp_path, monkeypatch):
        """Mutation-relevant: with the old (pre-fix) behavior, a total
        failure still persisted the cooldown timestamp, so an immediate
        retry within the same instant would be suppressed. With the fix,
        a second call right after a total failure must still attempt
        delivery."""
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        calls = []
        monkeypatch.setattr(
            notify, "_send_discord", lambda *a, **k: calls.append(1) or False
        )

        notify.send_system_alert("t1", "m1", cooldown_key="test_key")
        notify.send_system_alert("t2", "m2", cooldown_key="test_key")

        assert len(calls) == 2, (
            "total failure must not burn the cooldown -- the second call "
            f"should have retried delivery too, got {len(calls)} attempt(s)"
        )

    def test_partial_success_does_persist_cooldown(self, tmp_path, monkeypatch):
        """Positive control: when at least one channel succeeds, the
        cooldown IS burned as normal -- proves the rollback is specific to
        total failure, not a general regression of the cooldown."""
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        calls = []
        monkeypatch.setattr(
            notify, "_send_discord", lambda *a, **k: calls.append(1) or True
        )

        notify.send_system_alert("t1", "m1", cooldown_key="test_key")
        notify.send_system_alert("t2", "m2", cooldown_key="test_key")

        assert len(calls) == 1, (
            f"a successful delivery must still suppress the next call within "
            f"cooldown, got {len(calls)} attempt(s)"
        )

    def test_no_channels_configured_does_not_burn_cooldown(self, tmp_path, monkeypatch):
        """opus-review-caught (F8): `successes` stays fully EMPTY (not just
        all-False) when NOTIFY_CHANNELS matches none of the 5 known
        channels -- the rollback must still fire in that case, not just the
        partial-configured-but-failed case."""
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"nonexistent_channel"})

        notify.send_system_alert("t1", "m1", cooldown_key="empty_channels_test")

        import json

        state = json.loads(path.read_text()) if path.exists() else {}
        assert "empty_channels_test" not in state, (
            f"cooldown must be rolled back when zero channels were "
            f"configured, not burned: {state}"
        )


# ── item 2: notify.py empty-successes-list bug ──────────────────────────────


class TestNtfyEmptySuccessesFix:
    def test_send_system_alert_ntfy_without_topic_counts_as_failure(
        self, tmp_path, monkeypatch, caplog
    ):
        """Mutation-relevant: before the fix, `successes` stayed an empty
        list when "ntfy" was the only configured channel and NTFY_TOPIC was
        unset (the ntfy branch never appended anything), so the
        `if successes and not any(successes)` guard silently skipped the
        "all channels failed" warning. After the fix, ntfy always records
        an attempt (False when unconfigured), so total misconfiguration is
        visible and the cooldown is rolled back."""
        import logging

        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"ntfy"})
        monkeypatch.delenv("NTFY_TOPIC", raising=False)

        with caplog.at_level(logging.WARNING):
            notify.send_system_alert("t1", "m1", cooldown_key="ntfy_test")

        assert any("not delivered" in r.getMessage() for r in caplog.records), (
            "expected the all-channels-failed warning to fire"
        )

        # And the cooldown must have been rolled back (not burned) as a
        # consequence -- the key must not be persisted at all (this is its
        # first-ever observation, so a rollback removes rather than
        # restores it -- see _system_cooldown_rollback's own docstring).
        import json

        state = json.loads(path.read_text()) if path.exists() else {}
        assert "ntfy_test" not in state, (
            f"total failure must roll the cooldown back, not burn it: {state}"
        )

    def test_discord_color_defaults_to_orange(self, tmp_path, monkeypatch):
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        colors = []
        monkeypatch.setattr(
            notify,
            "_send_discord",
            lambda title, msg, color=None: colors.append(color) or True,
        )

        notify.send_system_alert("t", "m", cooldown_key="color_default_test")

        assert colors == [0xE3B341]

    def test_discord_color_override_is_passed_through(self, tmp_path, monkeypatch):
        """opus-review-caught (F13): a caller-supplied discord_color must
        actually reach _send_discord, not just be accepted and dropped."""
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        colors = []
        monkeypatch.setattr(
            notify,
            "_send_discord",
            lambda title, msg, color=None: colors.append(color) or True,
        )

        notify.send_system_alert(
            "t", "m", cooldown_key="color_override_test", discord_color=0xF85149
        )

        assert colors == [0xF85149]

    def test_send_system_alert_ntfy_with_topic_configured_succeeds(
        self, tmp_path, monkeypatch
    ):
        """Positive control: with NTFY_TOPIC set and _send_ntfy succeeding,
        no failure warning and the cooldown IS burned normally."""
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)
        monkeypatch.setattr(notify, "_CHANNELS", {"ntfy"})
        monkeypatch.setenv("NTFY_TOPIC", "some-topic")
        monkeypatch.setattr(notify, "_send_ntfy", lambda *a, **k: True)

        notify.send_system_alert("t1", "m1", cooldown_key="ntfy_ok_test")

        import json

        state = json.loads(path.read_text())
        assert "ntfy_ok_test" in state, (
            "a successful ntfy delivery must persist (burn) the cooldown"
        )

    def test_alert_strong_signal_ntfy_without_topic_counts_as_failure(
        self, monkeypatch, caplog
    ):
        """Same fix, alert_strong_signal's independent copy of the bug."""
        import logging

        import notify

        monkeypatch.setattr(notify, "_CHANNELS", {"ntfy"})
        monkeypatch.delenv("NTFY_TOPIC", raising=False)
        monkeypatch.setattr(notify, "_last_notified", {})

        with caplog.at_level(logging.WARNING):
            notify.alert_strong_signal("KXTEST", "NYC", "yes", 0.1, 0.05)

        assert any("not delivered" in r.getMessage() for r in caplog.records)


# ── item 4: alerts.check_halt_transition ────────────────────────────────────


class TestCheckHaltTransition:
    def test_false_to_true_is_a_transition(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        assert alerts.check_halt_transition("anomaly", True) is True

    def test_true_to_true_is_not_a_transition(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        assert alerts.check_halt_transition("anomaly", True) is True
        assert alerts.check_halt_transition("anomaly", True) is False, (
            "a second consecutive active observation must not re-report a "
            "transition -- only the false->true edge does"
        )

    def test_false_observation_is_never_a_transition(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        assert alerts.check_halt_transition("anomaly", False) is False

    def test_clears_and_refires_after_a_false_observation(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        assert alerts.check_halt_transition("anomaly", True) is True
        assert alerts.check_halt_transition("anomaly", False) is False
        assert alerts.check_halt_transition("anomaly", True) is True, (
            "re-engagement after a genuine clear must be treated as a fresh transition"
        )

    def test_distinct_halt_types_do_not_interfere(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        assert alerts.check_halt_transition("anomaly", True) is True
        assert alerts.check_halt_transition("drawdown", True) is True, (
            "a different halt_type's first engagement must not be suppressed "
            "by an unrelated halt_type already being active"
        )

    def test_two_independent_observers_do_not_oscillate_the_same_flag(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught (2nd round, MEDIUM-2): cron.py's paper-only
        pre-cycle observer and order_executor.py's client-aware cycle-level
        observer used to write the SAME halt_type with genuinely different
        inputs. Whenever they disagree (e.g. a live-only condition the
        paper-only observer can't see), the shared flag flip-flopped every
        cycle -- cron writes False, order_executor writes True (a false->
        true edge, alerts), next cycle cron writes False again (clears the
        flag), order_executor writes True again (ANOTHER false->true edge,
        alerts again) -- degrading "fire once per engagement" back to "fire
        every cycle" (rate-limited only by the 6h cooldown, same as
        pre-batch-24-item-4 behavior). Fixed by tracking cron's observer
        under a distinct "<type>_paper" halt_type. Simulates 3 "cycles" of
        this exact disagreement and confirms order_executor's own
        transition edge fires only on the FIRST cycle."""
        import alerts

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")

        order_executor_edges = []
        for _cycle in range(3):
            # cron.py's pre-cycle observer (paper-only) sees "not active".
            alerts.check_halt_transition("drawdown_paper", False)
            # order_executor.py's cycle-level observer (real client) sees
            # "active" every cycle (a persistent live-only condition).
            order_executor_edges.append(alerts.check_halt_transition("drawdown", True))

        assert order_executor_edges == [True, False, False], (
            f"order_executor's own transition must fire once (first cycle) "
            f"then stay suppressed while it remains continuously active, "
            f"unaffected by cron's separate paper-only observer clearing "
            f"its own flag every cycle -- got {order_executor_edges}"
        )

    def test_corrupt_state_file_fails_open_toward_alerting(self, tmp_path, monkeypatch):
        """A corrupt/unparseable state file must be treated as 'previously
        inactive' so a real transition is never silently swallowed."""
        import alerts

        path = tmp_path / "halts.json"
        path.write_text("{not valid json")
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        assert alerts.check_halt_transition("anomaly", True) is True

    def test_corrupt_read_does_not_clobber_sibling_halt_types(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught (2nd round, MEDIUM-3): on a failed read, an
        earlier version still wrote `state[halt_type] = active` into the
        blank {} the failed read produced -- silently WIPING every other
        already-persisted halt_type's flag from the file, not just failing
        to update this one. The exact hazard notify.py's own
        _read_cooldown_state already avoids for the same category of file.
        A corrupt read must skip the write entirely."""
        import json

        import alerts

        path = tmp_path / "halts.json"
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        # Seed two real, healthy halt-type observations.
        alerts.check_halt_transition("anomaly", True)
        alerts.check_halt_transition("daily_loss", True)
        assert json.loads(path.read_text()) == {"anomaly": True, "daily_loss": True}

        # Corrupt the file, then observe a THIRD halt_type.
        path.write_text("{not valid json")
        alerts.check_halt_transition("drawdown", True)

        # A failed read must not have triggered a write at all -- the file
        # content is byte-identical to the corrupt text, proving this call
        # did NOT overwrite it with a blank-plus-one-key
        # {"drawdown": True} state (which would have permanently lost
        # "anomaly"/"daily_loss" even after the corruption is fixed by
        # hand, since the next successful read would see only "drawdown").
        assert path.read_text() == "{not valid json"

    def test_state_persists_across_separate_calls(self, tmp_path, monkeypatch):
        """Disk persistence -- state must survive independent of any
        in-process cache, matching send_system_alert's own cooldown
        persistence model."""
        import json

        import alerts

        path = tmp_path / "halts.json"
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        alerts.check_halt_transition("anomaly", True)
        assert json.loads(path.read_text()) == {"anomaly": True}

    def test_unchanged_active_state_skips_the_write(self, tmp_path, monkeypatch):
        """opus-review-caught (F11): called unconditionally every cron
        cycle for 2-3 halt types -- an unconditional atomic write (temp
        file + fsync + rename) on every call is wasted I/O when nothing
        changed. Verifies the file's mtime doesn't advance on a repeat
        observation of the same value."""
        import alerts

        path = tmp_path / "halts.json"
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        alerts.check_halt_transition("anomaly", True)
        mtime_after_first = path.stat().st_mtime_ns

        import time

        time.sleep(0.01)
        alerts.check_halt_transition("anomaly", True)  # unchanged: still True
        mtime_after_second = path.stat().st_mtime_ns

        assert mtime_after_second == mtime_after_first, (
            "a repeat observation of an unchanged value must not rewrite the file"
        )

    def test_unchanged_inactive_state_does_not_create_the_file(
        self, tmp_path, monkeypatch
    ):
        """Positive control for the skip-write optimization: repeated False
        observations (the common case -- most cron cycles, no halt active)
        must never even create the state file."""
        import alerts

        path = tmp_path / "halts.json"
        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", path)

        for _ in range(3):
            alerts.check_halt_transition("anomaly", False)

        assert not path.exists()


# ── item 2: activate_black_swan_halt notification routing ──────────────────


class TestBlackSwanNotificationRouting:
    def test_routes_through_send_system_alert(self, monkeypatch, tmp_path):
        """Mutation-relevant: previously called _send_pushover/_send_discord/
        _send_email directly (omitting ntfy/desktop, discarding return
        values). Must now go through send_system_alert so all 5
        NOTIFY_CHANNELS are honored."""
        import alerts

        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / "black_swan.json")
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", tmp_path / ".kill_switch")

        import notify

        with patch.object(notify, "send_system_alert") as mock_alert:
            alerts.activate_black_swan_halt("test reason")

        assert mock_alert.call_count == 1
        _, kwargs = mock_alert.call_args
        assert kwargs.get("cooldown_key") == "black_swan_halt"

    def test_uses_red_discord_color(self, monkeypatch, tmp_path):
        """opus-review-caught (F13): routing through send_system_alert's
        old fixed orange lost black-swan's real severity color -- must
        pass discord_color=0xF85149 (red) explicitly."""
        import alerts

        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / "black_swan.json")
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", tmp_path / ".kill_switch")

        import notify

        with patch.object(notify, "send_system_alert") as mock_alert:
            alerts.activate_black_swan_halt("test reason")

        _, kwargs = mock_alert.call_args
        assert kwargs.get("discord_color") == 0xF85149

    def test_kill_switch_file_still_created(self, monkeypatch, tmp_path):
        """Positive control: the routing change must not have disturbed the
        actual halt mechanism (touching the kill switch file)."""
        import alerts

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / "black_swan.json")
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", ks_path)

        import notify

        with patch.object(notify, "send_system_alert"):
            alerts.activate_black_swan_halt("test reason")

        assert ks_path.exists()

    def test_resume_clears_the_alert_cooldown(self, monkeypatch, tmp_path):
        """opus-review-caught (F1): activate_black_swan_halt() now routes
        through send_system_alert(cooldown_key="black_swan_halt"), which
        applies a 6h disk-persisted cooldown. Without clearing that cooldown
        on resume, a SECOND, distinct black-swan halt tripping soon after an
        operator investigates-and-resumes the first would silently NOT
        alert -- the most severe alert in the system going silent. Verifies
        clear_black_swan_state() (called by cmd_resume) clears it."""
        import alerts
        import notify

        cooldown_path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", cooldown_path)
        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / "black_swan.json")
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(notify, "_CHANNELS", {"discord"})
        monkeypatch.setattr(notify, "_send_discord", lambda *a, **k: True)

        # First halt burns the cooldown.
        alerts.activate_black_swan_halt("first reason")
        import json

        assert "black_swan_halt" in json.loads(cooldown_path.read_text())

        # Operator investigates and resumes -- must clear the cooldown.
        alerts.clear_black_swan_state()
        assert "black_swan_halt" not in json.loads(cooldown_path.read_text())

        # A second, distinct halt soon after must alert again, not be
        # silently suppressed by the first one's still-warm cooldown.
        calls = []
        monkeypatch.setattr(
            notify, "_send_discord", lambda *a, **k: calls.append(1) or True
        )
        alerts.activate_black_swan_halt("second reason")
        assert len(calls) == 1, (
            "a second halt after resume must alert, not be cooldown-suppressed"
        )

    def test_clear_without_prior_alert_is_a_noop(self, tmp_path, monkeypatch):
        """Positive control: clearing a cooldown key that was never set must
        not raise or create a spurious entry."""
        import notify

        path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", path)

        notify.clear_system_cooldown("never_fired_key")  # must not raise
        assert not path.exists()


# ── opus-review 2nd round LOW-1/2/3: cmd_resume must clear BOTH ────────────
# cooldown keys unconditionally, not just black_swan_halt gated on state
# file existence.


class TestCmdResumeClearsAlertCooldowns:
    def test_resume_clears_kill_switch_cooldown(self, tmp_path, monkeypatch):
        """opus-review-caught (2nd round, LOW-3): cmd_resume never cleared
        the "kill_switch" cooldown key at all -- a second, genuinely new
        kill-switch engagement soon after a resume would silently not
        alert, still suppressed by the first engagement's still-warm 6h
        cooldown."""
        import main
        import notify

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text("")
        cooldown_path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", cooldown_path)

        # Simulate a prior engagement having burned the cooldown.
        notify._system_cooldown_reserve(
            "kill_switch", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        import json

        assert "kill_switch" in json.loads(cooldown_path.read_text())

        main.cmd_resume()

        assert "kill_switch" not in json.loads(cooldown_path.read_text())

    def test_resume_clears_black_swan_cooldown_even_without_state_file(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught (2nd round, LOW-2): the original fix gated
        the black_swan_halt cooldown clear on _BLACK_SWAN_PATH.exists() --
        if activate_black_swan_halt()'s own state-file write had failed
        (logged, not fatal) while the alert still fired, that gate would
        never open, permanently leaving the cooldown uncleared by resume."""
        import alerts
        import main
        import notify

        ks_path = tmp_path / ".kill_switch"
        bs_path = tmp_path / "black_swan.json"  # deliberately never created
        cooldown_path = tmp_path / "notify_cooldowns.json"
        monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path)
        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", bs_path)
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", cooldown_path)

        notify._system_cooldown_reserve(
            "black_swan_halt", now=_NOW, cooldown_secs=_SIX_HOURS
        )
        import json

        assert "black_swan_halt" in json.loads(cooldown_path.read_text())
        assert not bs_path.exists()  # the scenario: state file was never written

        main.cmd_resume()

        assert "black_swan_halt" not in json.loads(cooldown_path.read_text())


# ── item 4: order_executor.py mid-cycle drawdown breach alert ──────────────


def _make_opp(ticker, date_):
    """Minimal opp shape that survives _auto_place_trades' full gate/scoring
    pipeline through to actual placement -- mirrors
    tests/test_cron_integration.py's _fake_strong_signal()."""
    from utils import STRONG_EDGE

    market = {
        "ticker": ticker,
        "yes_bid": 40,
        "yes_ask": 44,
        "_city": "NYC",
        "_date": date_,
        "_target_date": date_.isoformat(),
    }
    analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.40,
        "days_out": 1,
        "target_date": date_.isoformat(),
        "ci_adjusted_kelly": 0.10,
        "fee_adjusted_kelly": 0.10,
    }
    return (market, analysis)


class TestMidCycleDrawdownBreachAlert:
    def test_fires_alert_on_mid_cycle_breach(self, monkeypatch, tmp_path):
        """A drawdown breach discovered mid-cycle (2nd candidate onward, via
        _is_paused_now inside the per-candidate loop) must fire
        send_system_alert(cooldown_key="halt_drawdown") -- previously this
        was log-only (backlog.txt batch-24 item 4)."""
        import datetime

        import alerts
        import notify
        import order_executor
        import paper

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "cd.json")
        monkeypatch.setattr(order_executor, "is_trading_paused", lambda: False)
        # _make_opp's target_date is a fixed placeholder, unrelated to
        # place_paper_order's target_date-freshness guard (opus-review-
        # caught: this test drives the real _auto_place_trades ->
        # place_paper_order path).
        monkeypatch.setattr(paper, "STALE_TARGET_DATE_GRACE_DAYS", 10_000)

        opp1 = _make_opp("KXHIGHNY-26APR17-B70", datetime.date(2026, 4, 17))
        opp2 = _make_opp("KXHIGHNY-26APR18-B71", datetime.date(2026, 4, 18))

        calls = {"n": 0}

        def _fake_paused(client=None):
            calls["n"] += 1
            return calls["n"] >= 3  # pre-loop=False, candidate1=False, candidate2=True

        monkeypatch.setattr(paper, "is_paused_drawdown", _fake_paused)

        with patch.object(notify, "send_system_alert") as mock_alert:
            placed = order_executor._auto_place_trades(
                opps=[opp1, opp2], client=None, live=False, live_config=None
            )

        assert placed == 1, "the loop must break after the 1st placement"
        dd_calls = [
            c
            for c in mock_alert.call_args_list
            if c.kwargs.get("cooldown_key") == "halt_drawdown"
        ]
        assert len(dd_calls) == 1, (
            f"expected one halt_drawdown alert, got: {mock_alert.call_args_list}"
        )

    def test_no_breach_does_not_alert(self, monkeypatch, tmp_path):
        """Positive control: with is_paused_drawdown always False, no
        halt_drawdown alert fires and both candidates place."""
        import datetime

        import alerts
        import notify
        import order_executor
        import paper

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "cd.json")
        monkeypatch.setattr(order_executor, "is_trading_paused", lambda: False)
        monkeypatch.setattr(paper, "is_paused_drawdown", lambda client=None: False)
        # See test_fires_alert_on_mid_cycle_breach above for rationale.
        monkeypatch.setattr(paper, "STALE_TARGET_DATE_GRACE_DAYS", 10_000)

        opp1 = _make_opp("KXHIGHNY-26APR19-B72", datetime.date(2026, 4, 19))
        opp2 = _make_opp("KXHIGHNY-26APR20-B73", datetime.date(2026, 4, 20))

        with patch.object(notify, "send_system_alert") as mock_alert:
            placed = order_executor._auto_place_trades(
                opps=[opp1, opp2], client=None, live=False, live_config=None
            )

        assert placed == 2
        dd_calls = [
            c
            for c in mock_alert.call_args_list
            if c.kwargs.get("cooldown_key") == "halt_drawdown"
        ]
        assert len(dd_calls) == 0

    def test_cycle_level_check_clears_and_refires_without_cron(
        self, monkeypatch, tmp_path
    ):
        """opus-review-caught (F3), the core regression: in a `watch --auto`
        -only session, _auto_place_trades() is the ONLY place drawdown gets
        observed (cron.py's own pre-cycle observer never runs). Engage,
        clear, then re-engage across 3 separate calls -- the SECOND
        engagement must still alert, proving the flag doesn't get stuck
        True forever after the mid-cycle-only alert (which never wrote
        False) was the sole writer."""
        import datetime

        import alerts
        import notify
        import order_executor
        import paper

        monkeypatch.setattr(alerts, "_HALT_TRANSITION_PATH", tmp_path / "halts.json")
        monkeypatch.setattr(notify, "NOTIFY_COOLDOWN_STATE_PATH", tmp_path / "cd.json")
        monkeypatch.setattr(order_executor, "is_trading_paused", lambda: False)
        # See test_fires_alert_on_mid_cycle_breach above for rationale. This
        # test's own drawdown-halt short-circuits placement before reaching
        # place_paper_order today, so it passes either way -- patched
        # defensively so it doesn't silently start failing if that changes.
        monkeypatch.setattr(paper, "STALE_TARGET_DATE_GRACE_DAYS", 10_000)

        opp = _make_opp("KXHIGHNY-26APR21-B74", datetime.date(2026, 4, 21))

        with patch.object(notify, "send_system_alert") as mock_alert:
            # Cycle 1: drawdown engaged -- no candidates placed, alert fires.
            with patch.object(paper, "is_paused_drawdown", lambda client=None: True):
                order_executor._auto_place_trades(
                    opps=[opp], client=None, live=False, live_config=None
                )
            # Cycle 2: drawdown clears.
            with patch.object(paper, "is_paused_drawdown", lambda client=None: False):
                order_executor._auto_place_trades(
                    opps=[opp], client=None, live=False, live_config=None
                )
            # Cycle 3: drawdown re-engages -- must alert again, not be
            # swallowed by a flag stuck True since cycle 1.
            with patch.object(paper, "is_paused_drawdown", lambda client=None: True):
                order_executor._auto_place_trades(
                    opps=[opp], client=None, live=False, live_config=None
                )

        dd_calls = [
            c
            for c in mock_alert.call_args_list
            if c.kwargs.get("cooldown_key") == "halt_drawdown"
        ]
        assert len(dd_calls) == 2, (
            f"expected 2 alerts (cycle 1 engage, cycle 3 re-engage), got "
            f"{len(dd_calls)}: {mock_alert.call_args_list}"
        )


# ── opus-review F7: /health must not report cron_stale while the kill ──────
# switch is engaged (cron.cmd_cron deliberately stops refreshing
# CRON_LAST_RUN_PATH in that state -- see cron.py's finally block).


class TestHealthEndpointKillSwitchAware:
    def _client(self, monkeypatch):
        import utils

        monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
        from web_app import _build_app

        app = _build_app(object())
        app.config["TESTING"] = True
        return app.test_client()

    def test_stale_cron_without_kill_switch_reports_stale(self, tmp_path, monkeypatch):
        import os
        import time

        import web_app

        last_run = tmp_path / ".cron_last_run"
        last_run.write_text("old")
        old = time.time() - 10 * 3600  # 10h ago, past the 6h default threshold
        os.utime(last_run, (old, old))
        monkeypatch.setattr(web_app, "CRON_LAST_RUN_PATH", last_run)
        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")

        resp = self._client(monkeypatch).get("/health")
        assert resp.json["cron_stale"] is True
        assert resp.json["kill_switch_active"] is False

    def test_stale_cron_with_kill_switch_does_not_report_stale(
        self, tmp_path, monkeypatch
    ):
        """The regression this fixes: a stale CRON_LAST_RUN_PATH during a
        deliberate kill-switch halt must not read as 'bot is down' to an
        external monitor -- it's expected, and kill_switch_active already
        surfaces the real reason."""
        import os
        import time

        import web_app

        last_run = tmp_path / ".cron_last_run"
        last_run.write_text("old")
        old = time.time() - 10 * 3600
        os.utime(last_run, (old, old))
        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason":"test"}')
        monkeypatch.setattr(web_app, "CRON_LAST_RUN_PATH", last_run)
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        resp = self._client(monkeypatch).get("/health")
        assert resp.json["cron_stale"] is False
        assert resp.json["kill_switch_active"] is True
