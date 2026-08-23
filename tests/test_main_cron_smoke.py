"""
Smoke tests for cmd_cron — the main production execution path.
Tests the guards (kill switch, accuracy halt) at the entry point level.
All external I/O is mocked.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def minimal_mocks(tmp_path, monkeypatch):
    """Patch every external call cmd_cron makes so it can run without network."""
    import cron
    import main

    # Redirect lock and kill-switch paths to tmp_path so they don't interfere with production
    lock_path = tmp_path / ".cron.lock"
    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(cron, "LOCK_PATH", lock_path, raising=False)
    monkeypatch.setattr(cron, "KILL_SWITCH_PATH", ks_path, raising=False)

    # No markets returned by default
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])

    # Suppress manual-override file check
    monkeypatch.setattr(main, "_check_manual_override", lambda: False)

    # Suppress startup-orders file check
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)

    # Suppress write of the running flag
    monkeypatch.setattr(main, "_write_cron_running_flag", lambda: None)

    # Suppress circuit-health check (avoids hitting weather APIs)
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)

    return tmp_path


class TestCmdCronGuards:
    def test_kill_switch_blocks_market_scan(self, minimal_mocks, monkeypatch):
        """cmd_cron exits early when the kill switch file is present."""
        import cron
        import main

        ks_path = minimal_mocks / ".kill_switch"
        ks_path.write_text('{"reason": "test"}')
        monkeypatch.setattr(cron, "KILL_SWITCH_PATH", ks_path, raising=False)

        scan_called = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_called.append(1) or []
        )
        client = MagicMock()
        main.cmd_cron(client)
        assert scan_called == [], (
            "market scan should be skipped when kill switch is active"
        )

    def test_accuracy_halt_skips_placement_but_still_scans(
        self, minimal_mocks, monkeypatch
    ):
        """An accuracy halt must still scan/settle — only placement is skipped.

        Settlement is computed from settled trades, so skipping it while halted
        would make the halt self-perpetuating (it could never accumulate the
        settled trades needed to clear). Only kill-switch is a full stop.
        """
        import main
        import paper

        monkeypatch.setattr(paper, "is_accuracy_halted", lambda: True)

        scan_called = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_called.append(1) or []
        )
        client = MagicMock()
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass  # halted cycles still complete the full scan and exit(0) cleanly
        assert scan_called == [1], "market scan must still run during an accuracy halt"

    def test_empty_market_list_runs_cleanly(self, minimal_mocks):
        """cmd_cron with no markets returned completes without error."""
        import main

        # Set _called_from_loop to prevent sys.exit(0) at end of cron
        main.cmd_cron._called_from_loop = True
        try:
            client = MagicMock()
            main.cmd_cron(client)  # should not raise
        finally:
            main.cmd_cron._called_from_loop = False

    @pytest.mark.parametrize(
        "emos_n,emos_var_n,expected_substring",
        [
            (0, 0, "run 'py main.py backfill-emos' to populate history"),
            (25, 3, "run 'py main.py backfill-emos' if new trades settled"),
            (50, 12, "accumulating from live forward-fill trades"),
            # Real go-live bar is 80 (backlog.txt 2026-08-18), not the
            # 40-row Gneiting-2005 floor _emos_var_n<40 alone would suggest
            # -- 40 and 79 must both still read "accumulating", only 80+
            # reads READY. Regression test for the exact bug this fix closes
            # (the original code said READY at var_n=40).
            (50, 40, "accumulating from live forward-fill trades"),
            (50, 79, "accumulating from live forward-fill trades"),
            (50, 80, "READY"),
        ],
    )
    def test_emos_readiness_banner_four_way_branch(
        self, minimal_mocks, monkeypatch, capsys, emos_n, emos_var_n, expected_substring
    ):
        """cron.py's [EMOS] banner has 4 branches keyed off two separate
        counts (ens_mean-only vs ens_var-populated) -- each must print its
        own distinct guidance, not silently fall through to a neighboring
        branch's message."""
        import cron
        import main

        monkeypatch.setattr(
            cron, "EMOS_PARAMS_PATH", minimal_mocks / "emos_params.json"
        )
        monkeypatch.setattr("tracker.count_emos_ready_predictions", lambda: emos_n)
        monkeypatch.setattr(
            "tracker.count_emos_variance_ready_predictions", lambda: emos_var_n
        )

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())
        finally:
            main.cmd_cron._called_from_loop = False

        out = capsys.readouterr().out
        assert expected_substring in out, f"expected {expected_substring!r} in:\n{out}"

    def test_emos_branch2_display_uses_golive_bar_not_train_gate(
        self, minimal_mocks, monkeypatch, capsys
    ):
        """Review-caught gap: the emos_n<40 branch also DISPLAYS
        ens_var-populated's count -- it must show it against the 80-row
        go-live bar, not the unrelated 40-row Gneiting floor, even though
        this branch's own gating condition is still emos_n<40."""
        import cron
        import main

        monkeypatch.setattr(
            cron, "EMOS_PARAMS_PATH", minimal_mocks / "emos_params.json"
        )
        monkeypatch.setattr("tracker.count_emos_ready_predictions", lambda: 25)
        monkeypatch.setattr("tracker.count_emos_variance_ready_predictions", lambda: 45)

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())
        finally:
            main.cmd_cron._called_from_loop = False

        out = capsys.readouterr().out
        assert "45/80" in out, f"expected 'ens_var-populated: 45/80' in:\n{out}"
        assert "45/40" not in out, f"stale 40-row display leaked through:\n{out}"


class TestCmdCronQuarantineScanWiring:
    """cron.py's daily per-member quarantine scan (weather_markets.
    scan_member_quarantine), gated by LAST_QUARANTINE_SCAN_PATH so back-to-
    back cron runs the same day don't re-scan -- same marker-file idiom as
    the existing Monday sweep."""

    def test_scan_runs_when_marker_absent(self, minimal_mocks, monkeypatch):
        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)
        assert not marker.exists()

        called = []
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: called.append(1)
            or {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )

        import main

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())
        finally:
            main.cmd_cron._called_from_loop = False

        assert called == [1], "scan must run when the marker file doesn't exist yet"
        assert marker.exists(), "marker must be written after a successful scan"

    def test_scan_skipped_when_marker_fresh(self, minimal_mocks, monkeypatch):
        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        marker.write_text("")  # freshly touched -- mtime is "now"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)

        called = []
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: called.append(1)
            or {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )

        import main

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())
        finally:
            main.cmd_cron._called_from_loop = False

        assert called == [], "scan must be skipped when the marker is <1 day old"

    def test_scan_runs_again_once_marker_is_stale(self, minimal_mocks, monkeypatch):
        import os
        import time

        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        marker.write_text("")
        # Back-date the marker's mtime by 2 days.
        old = time.time() - 2 * 86400
        os.utime(marker, (old, old))
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)

        called = []
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: called.append(1)
            or {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )

        import main

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())
        finally:
            main.cmd_cron._called_from_loop = False

        assert called == [1], "scan must re-run once the marker is >=1 day old"

    def test_newly_quarantined_member_logged_as_warning(
        self, minimal_mocks, monkeypatch, caplog
    ):
        import logging

        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: {
                "newly_quarantined": ["gfs_seamless"],
                "released": [],
                "blocked_by_floor": [],
            },
        )

        import main

        with caplog.at_level(logging.WARNING):
            main.cmd_cron._called_from_loop = True
            try:
                main.cmd_cron(MagicMock())
            finally:
                main.cmd_cron._called_from_loop = False

        assert any(
            "quarantined ensemble member" in r.message and "gfs_seamless" in r.message
            for r in caplog.records
        ), "a newly-quarantined member must be logged at WARNING, not silently absorbed"

    def test_scan_failure_does_not_crash_cron(self, minimal_mocks, monkeypatch):
        """Mirrors every other cmd_cron sub-check (auto_retire_strategies,
        detect_brier_drift, etc.): a failure here is caught and logged, never
        allowed to abort the rest of the cron cycle."""
        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)

        def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr("weather_markets.scan_member_quarantine", _raise)

        import main

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())  # must not raise
        finally:
            main.cmd_cron._called_from_loop = False

        assert not marker.exists(), (
            "the marker must NOT be stamped on a failed scan -- otherwise a "
            "transient failure suppresses the real scan for a full day "
            "instead of retrying next cycle"
        )

    def test_ewma_z_status_line_logged_every_scan(
        self, minimal_mocks, monkeypatch, caplog
    ):
        """A daily INFO status line reporting every candidate's ewma_z, not
        just quarantine/release events -- so drift toward the trip line is
        visible before it actually trips (user request 2026-08-21)."""
        import logging

        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )
        monkeypatch.setattr(
            "weather_markets.load_member_quarantine_state",
            lambda: {
                "gfs_seamless": {"quarantined": False, "ewma_z": 0.45},
                "icon_seamless": {"quarantined": False, "ewma_z": -0.18},
                "ecmwf_aifs025_ensemble": {"quarantined": False, "ewma_z": 0.05},
            },
        )

        import main

        with caplog.at_level(logging.INFO):
            main.cmd_cron._called_from_loop = True
            try:
                main.cmd_cron(MagicMock())
            finally:
                main.cmd_cron._called_from_loop = False

        status_lines = [
            r.message for r in caplog.records if "ewma_z (trip=" in r.message
        ]
        assert status_lines, "expected a daily ewma_z status line, found none"
        assert "gfs_seamless=0.45" in status_lines[0]
        assert "icon_seamless=-0.18" in status_lines[0]
        assert "ecmwf_aifs025_ensemble=0.05" in status_lines[0]

    def test_approaching_trip_line_logged_as_warning(
        self, minimal_mocks, monkeypatch, caplog
    ):
        """A non-quarantined model whose ewma_z crosses half the trip
        threshold (1.0, since _QUARANTINE_TRIP_Z=2.0) must get a WARNING,
        easy to grep for without reading every day's INFO line."""
        import logging

        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )
        monkeypatch.setattr(
            "weather_markets.load_member_quarantine_state",
            lambda: {
                "gfs_seamless": {"quarantined": False, "ewma_z": 1.3},  # >= 1.0
                "icon_seamless": {"quarantined": False, "ewma_z": 0.2},  # < 1.0
            },
        )

        import main

        with caplog.at_level(logging.WARNING):
            main.cmd_cron._called_from_loop = True
            try:
                main.cmd_cron(MagicMock())
            finally:
                main.cmd_cron._called_from_loop = False

        approach_lines = [
            r.message
            for r in caplog.records
            if "approaching the quarantine" in r.message
        ]
        assert approach_lines, "expected an 'approaching' WARNING, found none"
        assert "gfs_seamless" in approach_lines[0]
        assert "icon_seamless" not in approach_lines[0], (
            "icon_seamless's ewma_z=0.2 is well under the 1.0 half-trip line "
            "and must not be flagged as approaching"
        )

    def test_already_quarantined_model_not_flagged_as_approaching(
        self, minimal_mocks, monkeypatch, caplog
    ):
        """A model that's ALREADY quarantined isn't 'approaching' anything --
        it already tripped. Must not appear in the approaching-WARNING list
        even with a high ewma_z."""
        import logging

        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )
        monkeypatch.setattr(
            "weather_markets.load_member_quarantine_state",
            lambda: {"gfs_seamless": {"quarantined": True, "ewma_z": 3.0}},
        )

        import main

        with caplog.at_level(logging.WARNING):
            main.cmd_cron._called_from_loop = True
            try:
                main.cmd_cron(MagicMock())
            finally:
                main.cmd_cron._called_from_loop = False

        approach_lines = [
            r.message
            for r in caplog.records
            if "approaching the quarantine" in r.message
        ]
        assert not approach_lines, (
            "an already-quarantined model must not be logged as 'approaching' "
            f"the trip line: {approach_lines}"
        )

    def test_status_log_failure_does_not_crash_cron(self, minimal_mocks, monkeypatch):
        """Mirrors test_scan_failure_does_not_crash_cron -- a failure in the
        new status-logging block specifically (not the scan itself) must
        not abort the rest of cron, and the marker must still be written
        since the actual scan succeeded."""
        import cron

        marker = minimal_mocks / ".last_quarantine_scan"
        monkeypatch.setattr(cron, "LAST_QUARANTINE_SCAN_PATH", marker)
        monkeypatch.setattr(
            "weather_markets.scan_member_quarantine",
            lambda: {"newly_quarantined": [], "released": [], "blocked_by_floor": []},
        )

        def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr("weather_markets.load_member_quarantine_state", _raise)

        import main

        main.cmd_cron._called_from_loop = True
        try:
            main.cmd_cron(MagicMock())  # must not raise
        finally:
            main.cmd_cron._called_from_loop = False

        assert marker.exists(), (
            "the scan itself succeeded -- only the status-log convenience "
            "block failed -- so the marker must still be written"
        )


class TestCmdUndo:
    """cmd_undo (main.py) wraps paper.undo_last_trade for the `undo` CLI
    command -- was tested only indirectly via undo_last_trade itself
    (tests/test_paper.py) until now; added when the command was first wired
    up to a CLI entry point (2026-07-12)."""

    def test_nothing_to_undo_prints_message(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("paper.undo_last_trade", lambda max_minutes: None)
        main.cmd_undo(max_minutes=5)

        out = capsys.readouterr().out
        assert "No unsettled trade" in out
        assert "5" in out

    def test_undone_trade_prints_ticker_and_refund(self, monkeypatch, capsys):
        import main

        removed = {"id": 1, "ticker": "KXHIGHNY-26JUL12-T80", "cost": 42.5}
        monkeypatch.setattr("paper.undo_last_trade", lambda max_minutes: removed)
        main.cmd_undo(max_minutes=5)

        out = capsys.readouterr().out
        assert "KXHIGHNY-26JUL12-T80" in out
        assert "42.50" in out


class TestCmdBrief:
    def test_top_opportunities_shows_error_reason(self, monkeypatch, capsys):
        """When market fetch fails, brief prints a visible warning containing the error."""
        import main
        import paper

        monkeypatch.setattr(
            main,
            "get_weather_markets",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("API timeout")),
        )
        monkeypatch.setattr(paper, "get_balance", lambda *a, **kw: 1000.0)
        monkeypatch.setattr(paper, "get_daily_pnl", lambda *a, **kw: 0.0)
        monkeypatch.setattr(paper, "get_current_streak", lambda *a, **kw: ("none", 0))
        monkeypatch.setattr(paper, "get_open_trades", lambda *a, **kw: [])
        monkeypatch.setattr(paper, "check_expiring_trades", lambda *a, **kw: [])
        monkeypatch.setattr(paper, "check_model_exits", lambda *a, **kw: [])
        monkeypatch.setattr(paper, "graduation_check", lambda *a, **kw: None)
        monkeypatch.setattr(paper, "check_aged_positions", lambda *a, **kw: [])

        client = MagicMock()
        main.cmd_brief(client)

        out = capsys.readouterr().out
        assert "API timeout" in out, f"Error reason must appear in output, got:\n{out}"

    def test_single_bad_market_does_not_abort_scan(self, monkeypatch, capsys):
        """One market failing enrich/analyze should not kill the rest of the scan."""
        import main
        import paper

        good_market = {"ticker": "KXHIGH-NYC-26APR30-B70", "yes_bid": 30, "yes_ask": 34}
        bad_market = {"ticker": "KXHIGH-BAD-26APR30-B70", "yes_bid": 0, "yes_ask": 0}

        monkeypatch.setattr(
            main, "get_weather_markets", lambda *a, **kw: [bad_market, good_market]
        )

        def _enrich(m):
            if m.get("ticker", "").startswith("KXHIGH-BAD"):
                raise ValueError("bad market data")
            return {
                **m,
                "_city": "NYC",
                "_date": "2026-04-30",
                "_target_date": "2026-04-30",
            }

        monkeypatch.setattr(main, "enrich_with_forecast", _enrich)
        monkeypatch.setattr(
            main,
            "analyze_trade",
            lambda *a, **kw: {
                "edge": 0.20,
                "net_edge": 0.20,
                "signal": "BUY",
                "recommended_side": "yes",
            },
        )
        monkeypatch.setattr(paper, "get_balance", lambda *a, **kw: 1000.0)
        monkeypatch.setattr(paper, "get_daily_pnl", lambda *a, **kw: 0.0)
        monkeypatch.setattr(paper, "get_current_streak", lambda *a, **kw: ("none", 0))
        monkeypatch.setattr(paper, "get_open_trades", lambda *a, **kw: [])
        monkeypatch.setattr(paper, "check_expiring_trades", lambda *a, **kw: [])
        monkeypatch.setattr(paper, "check_model_exits", lambda *a, **kw: [])
        monkeypatch.setattr(paper, "graduation_check", lambda *a, **kw: None)
        monkeypatch.setattr(paper, "check_aged_positions", lambda *a, **kw: [])

        client = MagicMock()
        main.cmd_brief(client)

        out = capsys.readouterr().out
        assert "KXHIGH-NYC" in out, (
            f"Good market should still appear after bad market is skipped, got:\n{out}"
        )


def test_brier_alert_includes_guidance():
    """format_brier_alert() output should include actionable next steps."""
    from tracker import format_brier_alert

    msg = format_brier_alert(scores=[0.3559, 0.2315])
    assert (
        "backtest" in msg.lower()
        or "calibrat" in msg.lower()
        or "review" in msg.lower()
    ), f"BrierAlert should include actionable guidance, got:\n{msg}"


@pytest.fixture()
def isolated_emos_paths(tmp_path, monkeypatch):
    """Redirect ml_bias's emos_params.json, temperature_scale.json, and
    temperature_scale_pre_emos.json paths to tmp_path -- all are module-level
    constants bound at ml_bias.py import time, so without this a test
    exercising the --activate confirm gate would read/write the real
    production data/ files (same class of gap the accuracy-halt-override
    review found for paper.py's own override paths). Also resets the mtime-
    cache-invalidation globals (_EMOS_CACHE_MTIME/_TEMP_CACHE_MTIME) so a
    stale mtime from an earlier test in the same process can't make a fresh
    tmp_path file look unchanged and skip reloading."""
    import ml_bias

    monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE_MTIME", None)
    monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
    monkeypatch.setattr(ml_bias, "_TEMP_CACHE", None)
    monkeypatch.setattr(ml_bias, "_TEMP_CACHE_MTIME", None)
    monkeypatch.setattr(
        ml_bias,
        "_TEMP_PRE_EMOS_SNAPSHOT_PATH",
        tmp_path / "temperature_scale_pre_emos.json",
    )
    # cron-lock check in _cmd_emos_train/cmd_emos_deactivate must not treat
    # this test process's own real (or absent) lock file as "cron running".
    monkeypatch.setattr("cron._is_cron_running", lambda: False)
    return tmp_path


def _jitter(i: int) -> float:
    """Small deterministic residual (+/-0.3F, alternating) so EMOS test
    fixtures aren't a perfectly noiseless straight line. A perfect line
    gives fit_emos's CRPS objective a flat minimum at the sigma floor,
    which scipy's Nelder-Mead can fail to certify as converged (res.success
    False) at low row counts -- reproduced as a real, row-count-sensitive
    test flake when the thin fixture below dropped from 12 to 15 rows
    (independent-review test finding). Real settled_temp_f data always has
    residual model/measurement error, so this also makes the fixture more
    representative, not just numerically safer."""
    return 0.3 if i % 2 == 0 else -0.3


@pytest.fixture()
def emos_training_rows(monkeypatch):
    """60 rows with real ens_var, closely linear (settled_temp_f =
    ens_mean + 1 +/- a small jitter -- see _jitter's own docstring for why
    exactly linear was fragile) so the fit is both well within the a/b
    bounds check and clearly beats the held-out CRPS baseline.
    _cmd_emos_train holds out the most recent ~20% of the ens_var-bearing
    rows before fitting (audit batch-28 item 3, split independently of any
    mean-only rows per the item's own follow-up fix) -- 60 rows split 48
    train / 12 held-out gives the 40-row activation floor (main.py's
    _EMOS_VAR_FLOOR) an 8-row margin, not the bare zero margin 50 rows
    would leave (independent-review test finding: a fixture with exactly
    the floor count makes every test in this class one row away from
    silently flipping to the refuse path). Tests exercising the
    confirm/decline/EOF paths need to reach the prompt rather than being
    refused for thin data or a failed held-out check."""
    rows = [
        {
            "ens_mean": 60.0 + i,
            "ens_var": 4.0 + i * 0.1,
            "settled_temp_f": 61.0 + i + _jitter(i),
        }
        for i in range(60)
    ]
    monkeypatch.setattr("tracker.get_emos_training_data", lambda: rows)
    return rows


@pytest.fixture()
def emos_training_rows_thin(monkeypatch):
    """15 rows with real ens_var -- below the >=40 activation floor, for
    testing the floor-refusal path itself. 15 (not 12) so the 80/20 holdout
    split still leaves 12 training rows >= the SEPARATE >=10 threshold that
    gates a genuine stage-2 fit vs. the hardcoded c=1.0/d=0.1 defaults
    (independent-review test finding: 12 rows split to 9/3 crossed that
    threshold, silently changing what this fixture actually exercises).
    Jittered per _jitter's own docstring."""
    rows = [
        {
            "ens_mean": 60.0 + i,
            "ens_var": 4.0 + i * 0.1,
            "settled_temp_f": 61.0 + i + _jitter(i),
        }
        for i in range(15)
    ]
    monkeypatch.setattr("tracker.get_emos_training_data", lambda: rows)
    return rows


class TestEmosActivationGate:
    """_cmd_emos_train's dry-run/--activate confirmation gate. Before this,
    running `py main.py emos-train` immediately wrote emos_params.json --
    the ONLY file weather_markets.py checks to switch multi-day
    above/below/between predictions onto EMOS -- with no separate go-live
    step, exactly the incident recorded in backlog.txt's EMOS entry."""

    def test_dry_run_does_not_write_params_file(
        self, isolated_emos_paths, emos_training_rows, capsys
    ):
        import main

        main._cmd_emos_train(activate=False)

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "NOT activated" in out

    def test_dry_run_never_prompts(
        self, isolated_emos_paths, emos_training_rows, monkeypatch
    ):
        """A dry run must not even reach a confirmation prompt -- activation
        requires the --activate flag, not just answering a reachable 'yes'."""
        import main

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("input() must not be called during a dry run")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main._cmd_emos_train(activate=False)  # must not raise
        assert not (isolated_emos_paths / "emos_params.json").exists()

    def test_activate_confirmed_writes_params_and_resets_temperature_scale(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """'between' IS EMOS-covered (weather_markets.py calls
        emos_interval_prob for it) and must be reset alongside
        global/above/below -- only 'sameday' (METAR-derived, never touched
        by EMOS) is preserved untouched."""
        import json

        import main
        import ml_bias

        (isolated_emos_paths / "temperature_scale.json").write_text(
            json.dumps(
                {
                    "global": {"T": 5.2, "n": 40},
                    "between": {"T": 6.8, "n": 23},
                    "sameday": {"T": 2.1, "n": 60},
                }
            )
        )
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main._cmd_emos_train(activate=True)

        assert (isolated_emos_paths / "emos_params.json").exists()
        assert ml_bias._load_emos_params() is not None

        temp = json.loads((isolated_emos_paths / "temperature_scale.json").read_text())
        assert temp["global"]["T"] == 1.0
        assert temp["above"]["T"] == 1.0
        assert temp["below"]["T"] == 1.0
        assert temp["between"]["T"] == 1.0
        assert temp["between"]["n"] == 23  # prior sample count preserved
        # 'sameday' is METAR-derived, EMOS never covers it -- must stay untouched
        assert temp["sameday"] == {"T": 2.1, "n": 60}

        out = capsys.readouterr().out
        assert "LIVE" in out

    def test_activate_declined_writes_nothing(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "no")
        main._cmd_emos_train(activate=True)

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "Cancelled" in out

    def test_activate_eof_on_prompt_cancels_without_crashing(
        self, isolated_emos_paths, emos_training_rows, monkeypatch
    ):
        """Running --activate non-interactively (e.g. piped through cron) must
        not silently go live or crash -- input() raises EOFError there."""
        import main

        def _eof(*_a, **_kw):
            raise EOFError

        monkeypatch.setattr("builtins.input", _eof)
        main._cmd_emos_train(activate=True)  # must not raise

        assert not (isolated_emos_paths / "emos_params.json").exists()

    def test_activate_refuses_below_variance_floor(
        self, isolated_emos_paths, emos_training_rows_thin, monkeypatch, capsys
    ):
        """Fewer than 40 ens_var rows must refuse activation outright (not
        just warn) -- c/d would otherwise be silently fit on a sample far
        below Gneiting 2005's floor, or be the hardcoded defaults entirely."""
        import main

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("input() must not be called below the floor")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main._cmd_emos_train(activate=True)  # must not raise, must not prompt

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "REFUSING" in out

    def test_activate_force_overrides_variance_floor(
        self, isolated_emos_paths, emos_training_rows_thin, monkeypatch
    ):
        """--force bypasses the floor refusal and reaches the normal confirm
        prompt (still requires typed 'yes' -- force isn't a silent bypass)."""
        import main

        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")
        main._cmd_emos_train(activate=True, force=True)

        assert (isolated_emos_paths / "emos_params.json").exists()

    def test_activate_refuses_while_cron_is_running(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """Activating mid-scan would split one cron cycle across two
        probability methods -- must refuse, not prompt."""
        import main

        monkeypatch.setattr("cron._is_cron_running", lambda: True)

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("input() must not be called while cron is running")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main._cmd_emos_train(activate=True)  # must not raise, must not prompt

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "cron cycle is currently running" in out

    def test_activate_refuses_if_cron_starts_during_confirmation_wait(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """AUD-0029: the pre-prompt check alone can't catch a cron cycle that
        starts DURING the (unbounded-duration) confirmation wait -- must
        re-check immediately before the write, not just before the prompt.
        _is_cron_running() returns False for the pre-prompt check (reaching
        the prompt) then True for the re-check right before save_emos_params
        (simulating cron starting while the operator was typing 'yes')."""
        import main

        calls = []

        def _is_cron_running():
            calls.append(None)
            return len(calls) >= 2  # False first call, True from the second on

        monkeypatch.setattr("cron._is_cron_running", _is_cron_running)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main._cmd_emos_train(activate=True)  # must not raise

        assert not (isolated_emos_paths / "emos_params.json").exists(), (
            "a cron cycle starting mid-confirmation must still block the write"
        )
        assert len(calls) >= 2, "the re-check before the write must actually run"
        out = capsys.readouterr().out
        assert "cron cycle started while waiting" in out

    def test_activate_rolls_back_if_temperature_reset_fails(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """If reset_temperature_scale_for_emos() raises after
        save_emos_params() already wrote the live-switch file, activation
        must roll back to NOT-active rather than leaving EMOS live with
        stale T values (the exact double-calibration this whole gate exists
        to prevent)."""
        import main
        import ml_bias

        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        def _boom():
            raise RuntimeError("disk full")

        monkeypatch.setattr(ml_bias, "reset_temperature_scale_for_emos", _boom)

        main._cmd_emos_train(activate=True)  # must not raise

        assert not (isolated_emos_paths / "emos_params.json").exists(), (
            "activation must be rolled back, not left partially applied"
        )
        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "Rollback complete" in out


class TestEmosRetrainAndCrpsGate:
    """Audit batch-28 items 2/3: a RETRAIN of an already-active EMOS must not
    re-snapshot temperature_scale.json (item 2), and a structurally-broken
    or held-out-CRPS-losing fit must not reach save_emos_params (item 3)."""

    def test_retrain_of_already_active_emos_skips_temperature_scale_reset(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """First activation resets+snapshots T; a second run (retrain) with
        EMOS already active must leave temperature_scale.json completely
        untouched -- both the reset_at timestamp and the pre-EMOS snapshot
        must survive unchanged, proving reset_temperature_scale_for_emos()
        was never called a second time (not just that its own guard no-op'd)."""
        import json

        import main
        import ml_bias

        (isolated_emos_paths / "temperature_scale.json").write_text(
            json.dumps({"global": {"T": 5.2, "n": 40}})
        )
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main._cmd_emos_train(activate=True)  # first activation
        temp_after_first = json.loads(
            (isolated_emos_paths / "temperature_scale.json").read_text()
        )
        assert temp_after_first["global"]["T"] == 1.0
        first_reset_at = temp_after_first["global"]["reset_at"]
        snapshot_after_first = json.loads(
            (isolated_emos_paths / "temperature_scale_pre_emos.json").read_text()
        )
        assert snapshot_after_first["global"] == {"T": 5.2, "n": 40}

        # Positive control: reset_temperature_scale_for_emos really is
        # reachable and mutates the file when called directly -- proves the
        # "untouched" assertion below isn't vacuous (e.g. from a fixture bug
        # that made the file unwritable).
        calls = []
        _real_reset = ml_bias.reset_temperature_scale_for_emos

        def _counting_reset():
            calls.append(1)
            return _real_reset()

        monkeypatch.setattr(
            ml_bias, "reset_temperature_scale_for_emos", _counting_reset
        )
        # Skip the held-out-vs-incumbent CRPS comparison for this test: the
        # retrain here reuses the exact same fixture rows as the first
        # activation, so the "new" fit is numerically identical to the
        # incumbent and would tie (not strictly beat) it -- that specific
        # gate behavior is covered on its own in
        # test_held_out_crps_gate_beaten_by_incumbent_refuses_retrain. This
        # test's purpose is item 2 (does a retrain skip the T-reset), so
        # isolate it from item 3's separate incumbent-comparison gate.
        monkeypatch.setattr(ml_bias, "_load_emos_params", lambda: None)

        main._cmd_emos_train(activate=True)  # retrain -- EMOS already active

        assert calls == [], (
            "reset_temperature_scale_for_emos must not be called at all on a "
            "retrain of an already-active EMOS"
        )
        temp_after_retrain = json.loads(
            (isolated_emos_paths / "temperature_scale.json").read_text()
        )
        assert temp_after_retrain["global"]["reset_at"] == first_reset_at, (
            "temperature_scale.json must be byte-for-byte untouched by a retrain"
        )
        assert (isolated_emos_paths / "temperature_scale_pre_emos.json").exists(), (
            "the original pre-EMOS snapshot must still be there"
        )
        snapshot_after_retrain = json.loads(
            (isolated_emos_paths / "temperature_scale_pre_emos.json").read_text()
        )
        assert snapshot_after_retrain["global"] == {"T": 5.2, "n": 40}, (
            "the snapshot must still hold the ORIGINAL real T=5.2, not a "
            "placeholder captured by a second (wrongly-run) reset"
        )

        out = capsys.readouterr().out
        assert "RETRAIN" in out

    def test_diverged_t_pin_triggers_full_reset_instead_of_skip(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """Independent-review finding (audit batch-28 item 3 follow-up, M2):
        EMOS active (emos_params.json exists) but temperature_scale.json NOT
        correctly pinned (a real, non-1.0 T sitting where a placeholder
        should be -- state drift) must NOT be treated as a normal retrain
        that skips the T-reset; that would perpetuate the divergence
        forever. It must instead run the full reset and re-pin T."""
        import json

        import main
        import ml_bias

        ml_bias.save_emos_params(1.0, 1.0, 1.0, 0.1, n=50)  # EMOS active
        # Diverged: 'above' has a real, non-reset T instead of the 1.0
        # placeholder every OTHER covered key correctly carries.
        (isolated_emos_paths / "temperature_scale.json").write_text(
            json.dumps(
                {
                    "global": {"T": 1.0, "n": 10, "reset_for_emos": True},
                    "above": {"T": 4.1, "n": 20},
                    "below": {"T": 1.0, "n": 10, "reset_for_emos": True},
                    "between": {"T": 1.0, "n": 10, "reset_for_emos": True},
                }
            )
        )
        assert ml_bias.get_emos_status()["t_pinned"] is False  # positive control

        # Isolate from the separate held-out-vs-incumbent CRPS gate (already
        # covered by its own dedicated tests) -- this test's purpose is the
        # T-pin divergence handling, not the CRPS comparison.
        monkeypatch.setattr(ml_bias, "_load_emos_params", lambda: None)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")
        main._cmd_emos_train(activate=True)

        out = capsys.readouterr().out
        assert "diverged" in out.lower() or "NOT correctly pinned" in out
        assert "RETRAIN" not in out, (
            "a diverged pin must not be presented as a normal retrain"
        )

        temp_after = json.loads(
            (isolated_emos_paths / "temperature_scale.json").read_text()
        )
        assert temp_after["above"]["T"] == 1.0, (
            "the diverged 'above' key must have been reset to 1.0, not left "
            "at its stale real value"
        )
        assert temp_after["above"]["reset_for_emos"] is True
        assert ml_bias.get_emos_status()["t_pinned"] is True, (
            "divergence must be fully resolved after this retrain"
        )

    def test_invalid_ab_fit_refused_even_with_force(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """A degenerate fit (here: a negative slope b, physically backwards
        -- a warmer ensemble mean predicting a cooler outcome) must be
        refused outright, and --force must NOT override it -- --force exists
        for the data-sufficiency floor, not for a structurally broken fit."""
        import main
        import ml_bias

        monkeypatch.setattr(
            ml_bias, "fit_emos", lambda *_a, **_kw: (0.0, -0.5, 1.0, 0.1)
        )

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("input() must not be called on an invalid fit")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main._cmd_emos_train(
            activate=True, force=True
        )  # must not raise, must not prompt

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "INVALID FIT" in out

    def test_held_out_crps_gate_refuses_worse_than_baseline_fit(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """A fit that ignores the ensemble mean entirely (b~=0, so mu stays
        near a constant regardless of ens_mean) is far worse than the raw-
        ensemble baseline on this fixture's perfectly linear held-out data
        -- must be refused, not just warned about."""
        import main
        import ml_bias

        # Passes the a/b bounds check (0 < b <= 3, |a| <= 30) but is a much
        # worse predictor than the raw-ensemble baseline on this fixture's
        # held-out rows (the last 12 of 60 ens_var rows: ens_mean ~108-119,
        # true obs ~109-120): mu stays pinned near 1.1-1.2 since b=0.01
        # barely responds to ens_mean.
        monkeypatch.setattr(
            ml_bias, "fit_emos", lambda *_a, **_kw: (0.0, 0.01, 1.0, 0.1)
        )

        def _unexpected_input(*_a, **_kw):
            raise AssertionError(
                "input() must not be called when the CRPS gate refuses"
            )

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main._cmd_emos_train(activate=True)  # must not raise, must not prompt

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "REFUSING to activate" in out
        assert "held-out data" in out

    def test_held_out_crps_gate_force_overrides(
        self, isolated_emos_paths, emos_training_rows, monkeypatch
    ):
        """--force reaches the normal confirm prompt despite a losing
        held-out CRPS comparison -- force isn't a silent bypass, 'yes' is
        still required."""
        import main
        import ml_bias

        monkeypatch.setattr(
            ml_bias, "fit_emos", lambda *_a, **_kw: (0.0, 0.01, 1.0, 0.1)
        )
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main._cmd_emos_train(activate=True, force=True)

        assert (isolated_emos_paths / "emos_params.json").exists()

    def test_held_out_crps_gate_force_still_requires_yes(
        self, isolated_emos_paths, emos_training_rows, monkeypatch
    ):
        """Positive control for the test above: --force reaches the prompt
        but declining it must still write nothing -- proves --force alone
        isn't what wrote the file there, the 'yes' answer was necessary too."""
        import main
        import ml_bias

        monkeypatch.setattr(
            ml_bias, "fit_emos", lambda *_a, **_kw: (0.0, 0.01, 1.0, 0.1)
        )
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "no")

        main._cmd_emos_train(activate=True, force=True)

        assert not (isolated_emos_paths / "emos_params.json").exists()

    def test_held_out_rows_are_never_used_in_fitting(
        self, isolated_emos_paths, monkeypatch, capsys
    ):
        """Item 3's central claim, pinned directly: the held-out rows must
        have zero influence on the fitted a/b. 80 rows follow the true
        relationship (settled_temp_f = ens_mean + 1); the most recent 20
        (the held-out slice) follow a wildly different one (+1000 offset).
        If those 20 leaked into stage-1 fitting, the fitted intercept would
        be dragged far from 1.0 toward the outliers; if truly excluded, it
        stays close to 1.0 regardless."""
        import main

        rows = [
            {
                "ens_mean": 60.0 + i,
                "ens_var": 4.0,
                "settled_temp_f": 61.0 + i + _jitter(i),
            }
            for i in range(80)
        ] + [
            {"ens_mean": 60.0 + i, "ens_var": 4.0, "settled_temp_f": 1060.0 + i}
            for i in range(80, 100)
        ]
        monkeypatch.setattr("tracker.get_emos_training_data", lambda: rows)

        main._cmd_emos_train(activate=False)

        out = capsys.readouterr().out
        import re

        match = re.search(r"a = (-?[\d.]+)\s+b = ", out)
        assert match is not None, f"could not find stage-1 fit output in:\n{out}"
        fitted_a = float(match.group(1))
        assert abs(fitted_a - 1.0) < 5.0, (
            f"fitted a={fitted_a} looks pulled toward the held-out outliers "
            "(true training-only intercept is 1.0) -- held-out rows must not "
            "have influenced stage-1 fitting"
        )

    def test_held_out_crps_gate_beaten_by_incumbent_refuses_retrain(
        self, isolated_emos_paths, emos_training_rows, monkeypatch, capsys
    ):
        """On a retrain, the new fit must beat the CURRENTLY-ACTIVE incumbent
        on held-out data, not just the raw-ensemble baseline -- an incumbent
        that's already a good fit (here: the true a=1,b=1,c=1,d=0.1
        generating relationship) must not be replaced by a worse retrain."""
        import main
        import ml_bias

        ml_bias.save_emos_params(1.0, 1.0, 1.0, 0.1, n=50)  # near-perfect incumbent
        # A fit that's decent (beats the naive baseline) but not as good as
        # the near-perfect incumbent above.
        monkeypatch.setattr(
            ml_bias, "fit_emos", lambda *_a, **_kw: (3.0, 1.0, 1.0, 0.1)
        )

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("input() must not be called when the incumbent wins")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main._cmd_emos_train(activate=True)  # must not raise, must not prompt

        out = capsys.readouterr().out
        assert "REFUSING to activate" in out
        assert "incumbent" in out


class TestEmosStatusAndDeactivate:
    def test_status_reports_inactive_when_no_params_file(
        self, isolated_emos_paths, capsys
    ):
        import main

        main.cmd_emos_status()
        out = capsys.readouterr().out
        assert "NOT active" in out

    def test_status_reports_active_with_fitted_values(
        self, isolated_emos_paths, capsys
    ):
        import main
        import ml_bias

        ml_bias.save_emos_params(1.5, 0.9, 2.0, 0.2, n=48, mean_crps=0.31)
        main.cmd_emos_status()

        out = capsys.readouterr().out
        assert "ACTIVE" in out
        assert "48" in out

    def test_deactivate_already_inactive_does_not_prompt(
        self, isolated_emos_paths, monkeypatch, capsys
    ):
        import main

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("must not prompt when EMOS is already inactive")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main.cmd_emos_deactivate()  # must not raise

        out = capsys.readouterr().out
        assert "nothing to do" in out.lower()

    def test_deactivate_confirmed_removes_params_file(
        self, isolated_emos_paths, monkeypatch, capsys
    ):
        import main
        import ml_bias

        ml_bias.save_emos_params(1.5, 0.9, 2.0, 0.2, n=48, mean_crps=0.31)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main.cmd_emos_deactivate()

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "deactivated" in out.lower()

    def test_deactivate_declined_keeps_params_file(
        self, isolated_emos_paths, monkeypatch
    ):
        import main
        import ml_bias

        ml_bias.save_emos_params(1.5, 0.9, 2.0, 0.2, n=48, mean_crps=0.31)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "no")

        main.cmd_emos_deactivate()

        assert (isolated_emos_paths / "emos_params.json").exists()

    def test_deactivate_refuses_while_cron_is_running(
        self, isolated_emos_paths, monkeypatch, capsys
    ):
        import main
        import ml_bias

        ml_bias.save_emos_params(1.5, 0.9, 2.0, 0.2, n=48, mean_crps=0.31)
        monkeypatch.setattr("cron._is_cron_running", lambda: True)

        def _unexpected_input(*_a, **_kw):
            raise AssertionError("must not prompt while cron is running")

        monkeypatch.setattr("builtins.input", _unexpected_input)
        main.cmd_emos_deactivate()  # must not raise

        assert (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "cron cycle is currently running" in out

    def test_deactivate_refuses_if_cron_starts_during_confirmation_wait(
        self, isolated_emos_paths, monkeypatch, capsys
    ):
        """AUD-0029: same TOCTOU fix as activation's re-check, mirrored for
        deactivation's own write."""
        import main
        import ml_bias

        ml_bias.save_emos_params(1.5, 0.9, 2.0, 0.2, n=48, mean_crps=0.31)
        calls = []

        def _is_cron_running():
            calls.append(None)
            return len(calls) >= 2  # False first call, True from the second on

        monkeypatch.setattr("cron._is_cron_running", _is_cron_running)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main.cmd_emos_deactivate()  # must not raise

        assert (isolated_emos_paths / "emos_params.json").exists(), (
            "a cron cycle starting mid-confirmation must still block the write"
        )
        assert len(calls) >= 2, "the re-check before the write must actually run"
        out = capsys.readouterr().out
        assert "cron cycle started while waiting" in out

    def test_deactivate_restores_pre_activation_temperature_scale(
        self, isolated_emos_paths, emos_training_rows, monkeypatch
    ):
        """The end-to-end round trip: activate (snapshots + resets T),
        deactivate (restores T from the snapshot immediately) -- must not
        leave T pinned at the 1.0 placeholder, which would reproduce the
        zero-calibration incident this whole flow exists to prevent."""
        import json

        import main

        (isolated_emos_paths / "temperature_scale.json").write_text(
            json.dumps({"global": {"T": 5.2, "n": 40}, "above": {"T": 4.1, "n": 20}})
        )
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main._cmd_emos_train(activate=True)
        temp_after_activate = json.loads(
            (isolated_emos_paths / "temperature_scale.json").read_text()
        )
        assert temp_after_activate["global"]["T"] == 1.0

        main.cmd_emos_deactivate()
        temp_after_deactivate = json.loads(
            (isolated_emos_paths / "temperature_scale.json").read_text()
        )
        assert temp_after_deactivate["global"] == {"T": 5.2, "n": 40}
        assert temp_after_deactivate["above"] == {"T": 4.1, "n": 20}
        # snapshot file is consumed, not left lying around after a successful restore
        assert not (isolated_emos_paths / "temperature_scale_pre_emos.json").exists()

    def test_deactivate_archives_params_to_history_before_removing(
        self, isolated_emos_paths, monkeypatch
    ):
        """A bare unlink would make the very first activation's exact fitted
        parameters unrecoverable, since atomic_write_json_with_history only
        snapshots on OVERWRITE (nothing to overwrite on a first write)."""
        import main
        import ml_bias

        ml_bias.save_emos_params(1.5, 0.9, 2.0, 0.2, n=48, mean_crps=0.31)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        main.cmd_emos_deactivate()

        history_dir = isolated_emos_paths / ".history"
        archived = list(history_dir.glob("emos_params_*.json"))
        assert len(archived) == 1, f"expected exactly 1 archived file, got {archived}"
        import json

        archived_data = json.loads(archived[0].read_text())
        assert archived_data["a"] == pytest.approx(1.5)

    def test_status_reports_corrupt_file_distinctly(self, isolated_emos_paths, capsys):
        (isolated_emos_paths / "emos_params.json").write_text("{not valid json")

        import main

        main.cmd_emos_status()
        out = capsys.readouterr().out
        assert "CORRUPT" in out

    def test_deactivate_offers_to_remove_corrupt_file(
        self, isolated_emos_paths, monkeypatch, capsys
    ):
        (isolated_emos_paths / "emos_params.json").write_text("{not valid json")
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "yes")

        import main

        main.cmd_emos_deactivate()

        assert not (isolated_emos_paths / "emos_params.json").exists()
        out = capsys.readouterr().out
        assert "removed" in out.lower()

    def test_deactivate_declined_keeps_corrupt_file(
        self, isolated_emos_paths, monkeypatch
    ):
        (isolated_emos_paths / "emos_params.json").write_text("{not valid json")
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "no")

        import main

        main.cmd_emos_deactivate()

        assert (isolated_emos_paths / "emos_params.json").exists()
