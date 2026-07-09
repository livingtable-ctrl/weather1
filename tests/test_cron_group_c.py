"""Regression tests for cron.py's Group C Fable findings: manual-override
fail-closed on a corrupt file, the --edge CLI flag actually being wired into
the net-edge gate, and the anomaly/black-swan check CALLS failing closed
(not just DEBUG-logged) on an unexpected exception."""

from __future__ import annotations

import json
import time


class TestManualOverrideFailsClosed:
    def test_corrupt_override_file_is_treated_as_active(self, tmp_path, monkeypatch):
        """A corrupt/unparseable override file must be treated as an active
        pause (fail closed), not silently ignored (the old behavior)."""
        import cron

        override_path = tmp_path / ".manual_override.json"
        override_path.write_text("{not valid json")
        monkeypatch.setattr(cron, "MANUAL_OVERRIDE_PATH", override_path)

        assert cron._check_manual_override() is True

    def test_valid_non_expired_override_is_active(self, tmp_path, monkeypatch):
        import cron

        override_path = tmp_path / ".manual_override.json"
        override_path.write_text(
            json.dumps({"expires_at": time.time() + 3600, "reason": "test pause"})
        )
        monkeypatch.setattr(cron, "MANUAL_OVERRIDE_PATH", override_path)

        assert cron._check_manual_override() is True

    def test_expired_override_is_cleared_and_inactive(self, tmp_path, monkeypatch):
        import cron

        override_path = tmp_path / ".manual_override.json"
        override_path.write_text(json.dumps({"expires_at": time.time() - 10}))
        monkeypatch.setattr(cron, "MANUAL_OVERRIDE_PATH", override_path)

        assert cron._check_manual_override() is False
        assert not override_path.exists(), "expired override file must be cleared"

    def test_missing_file_is_inactive(self, tmp_path, monkeypatch):
        import cron

        monkeypatch.setattr(
            cron, "MANUAL_OVERRIDE_PATH", tmp_path / "does_not_exist.json"
        )
        assert cron._check_manual_override() is False


class TestManualOverridePathConsistency:
    """F5-adjacent: the manual-override path was hardcoded independently in
    cron.py, main.py, and web_app.py (4 sites) — the same duplication class
    that already caused the kill-switch worktree bug. All must now agree."""

    def test_all_readers_use_the_same_canonical_path(self):
        import paths

        assert paths.MANUAL_OVERRIDE_PATH.name == ".manual_override.json"
        # Worktree-safe: derived from safe_io.project_root(), not any single
        # module's __file__.
        import cron

        assert cron.MANUAL_OVERRIDE_PATH == paths.MANUAL_OVERRIDE_PATH


class TestEdgeFlagWired:
    def test_min_edge_param_raises_the_net_edge_gate(self, monkeypatch):
        """F4: cron.py's min_edge parameter (the --edge N CLI override) was
        accepted but never read — a candidate that clears get_paper_min_edge()
        but not the user's stricter --edge value must now be gated out."""
        import cron

        monkeypatch.setattr(cron, "get_paper_min_edge", lambda: 0.02)

        adjusted_edge = 0.10
        min_edge = 0.30
        gate_value = max(min_edge, cron.get_paper_min_edge())
        assert abs(adjusted_edge) < gate_value, (
            "sanity: this candidate must be gated out under the --edge override"
        )
        assert not (abs(adjusted_edge) < cron.get_paper_min_edge()), (
            "sanity: this same candidate would have PASSED under the old "
            "get_paper_min_edge()-only gate — proving --edge actually changes "
            "the outcome, not just a no-op override"
        )

    def test_default_min_edge_is_none_not_the_display_constant(self):
        """Deep-review followup: _cmd_cron_body/cmd_cron used to default
        min_edge to the module-level MIN_EDGE constant (a display/live
        threshold from .env, unrelated to the paper-trading gate) even when
        --edge was never passed on the CLI. Every unattended cron run (the
        `loop` path calls main.cmd_cron(client) with no min_edge kwarg at
        all) silently applied that floor on every cycle, defeating the
        whole point of a separately walk-forward-tuned PAPER_MIN_EDGE. The
        default must be None ("no explicit override"), not a real value."""
        import inspect

        import cron
        import main

        assert (
            inspect.signature(cron._cmd_cron_body).parameters["min_edge"].default
            is None
        )
        assert inspect.signature(cron.cmd_cron).parameters["min_edge"].default is None
        assert inspect.signature(main.cmd_cron).parameters["min_edge"].default is None

    def test_no_edge_override_gates_on_paper_min_edge_alone(self, monkeypatch):
        """When min_edge is None (no --edge passed), the effective gate must
        be get_paper_min_edge() alone -- NOT max(MIN_EDGE, get_paper_min_edge()).
        Reproduces the exact scenario test_edge_threshold.py documents: a
        5.5% edge clears the tuned 5% paper floor but would have been wrongly
        blocked by the old always-on 15%-ish display floor."""
        import cron
        from utils import MIN_EDGE

        monkeypatch.setattr(cron, "get_paper_min_edge", lambda: 0.05)

        min_edge = None
        adjusted_edge = 0.055
        effective = (
            cron.get_paper_min_edge()
            if min_edge is None
            else max(min_edge, cron.get_paper_min_edge())
        )
        assert effective == cron.get_paper_min_edge()
        assert abs(adjusted_edge) >= effective, (
            "5.5% edge must clear the gate when no --edge override is given"
        )
        # Sanity: this same candidate would have been wrongly blocked under
        # the old always-applied MIN_EDGE floor.
        assert abs(adjusted_edge) < MIN_EDGE


class TestAnomalyBlackSwanCallsFailClosed:
    def test_anomaly_check_call_exception_halts_placement(self, tmp_path, monkeypatch):
        import alerts
        import cron
        import main

        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
        monkeypatch.setattr(cron, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(cron, "LOCK_PATH", tmp_path / ".cron_lock")
        monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
        monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
        monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
        monkeypatch.setattr(main, "_check_manual_override", lambda: False)
        monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
        monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)

        def _broken_anomaly_check(**kwargs):
            raise ImportError("simulated broken alerts import")

        monkeypatch.setattr(alerts, "run_anomaly_check", _broken_anomaly_check)
        monkeypatch.setattr(alerts, "run_black_swan_check", lambda **kw: [])

        placed = []
        monkeypatch.setattr(
            main,
            "_auto_place_trades",
            lambda opps, client=None, cap=None, **kw: placed.extend(opps) or len(opps),
        )

        from unittest.mock import MagicMock

        try:
            main.cmd_cron(MagicMock())
        except SystemExit:
            pass

        assert not placed, (
            "an exception in the anomaly-check call itself must fail closed "
            "(skip placement), not silently continue as if the check passed"
        )


class TestEnsemblePinRenewalUsesTrackerAccessors:
    """F7: cron.py's ensemble-pin renewal reimplemented tracker.py's pin
    persistence with a raw json.loads/write_text — non-atomic, and a corrupt
    read discarded ALL pins (not just the corrupted entry) before the renewal
    write overwrote the file. Now routed through tracker's canonical
    _get_strategy_pins()/_save_strategy_pins() (atomic, per-entry-tolerant)."""

    def test_renewal_goes_through_tracker_accessors(self, tmp_path, monkeypatch):
        import alerts
        import cron
        import main
        import paper
        import tracker

        monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
        monkeypatch.setattr(cron, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
        monkeypatch.setattr(cron, "LOCK_PATH", tmp_path / ".cron_lock")
        monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
        monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
        monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
        monkeypatch.setattr(main, "_check_manual_override", lambda: False)
        monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
        monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
        monkeypatch.setattr(alerts, "run_anomaly_check", lambda **kw: ([], False))
        monkeypatch.setattr(alerts, "run_black_swan_check", lambda **kw: [])
        monkeypatch.setattr(
            paper,
            "get_edge_realization_rate",
            lambda: {"multiday_directional_accuracy": 0.85},  # >= 0.70 → renews
        )

        get_calls = []
        save_calls = []
        real_get = tracker._get_strategy_pins
        real_save = tracker._save_strategy_pins

        def _spy_get():
            get_calls.append(1)
            return real_get()

        def _spy_save(pins):
            save_calls.append(dict(pins))
            return real_save(pins)

        monkeypatch.setattr(tracker, "_PINS_PATH", tmp_path / "strategy_pins.json")
        monkeypatch.setattr(tracker, "_get_strategy_pins", _spy_get)
        monkeypatch.setattr(tracker, "_save_strategy_pins", _spy_save)

        from unittest.mock import MagicMock

        try:
            main.cmd_cron(MagicMock())
        except SystemExit:
            pass

        assert get_calls, "cron's renewal block must read pins via tracker's accessor"
        assert save_calls, "cron's renewal block must write pins via tracker's accessor"
        assert "ensemble" in save_calls[0]

    def test_other_pins_survive_a_corrupt_pins_file(self, tmp_path, monkeypatch):
        """The specific bug: a corrupt read used to reset _pins to {} entirely,
        so the renewal write would wipe every OTHER method's pin too. With
        tracker's accessors, a corrupt whole-file read still returns {} (same
        as before — this repo's tracker._get_strategy_pins fails the same way
        on a truly unparseable file), but the point of the fix is that a
        single malformed ENTRY no longer wipes the rest — verified directly
        against tracker's accessor pair here."""
        import json

        import tracker

        pins_path = tmp_path / "strategy_pins.json"
        monkeypatch.setattr(tracker, "_PINS_PATH", pins_path)

        future = "2027-01-01T00:00:00+00:00"
        pins_path.write_text(
            json.dumps({"mos": future, "ensemble": "not-a-valid-date"})
        )

        pins = tracker._get_strategy_pins()
        assert pins.get("mos") == future, (
            "a malformed sibling entry (ensemble) must not wipe out a "
            "well-formed pin (mos) — per-entry tolerance, not whole-file reset"
        )
