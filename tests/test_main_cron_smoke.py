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
            (50, 40, "READY"),
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


@pytest.fixture()
def emos_training_rows(monkeypatch):
    """40 rows with real ens_var -- clears the >=40 activation floor
    (main.py's _EMOS_VAR_FLOOR) so tests exercising the confirm/decline/EOF
    paths reach the prompt instead of being refused for thin data."""
    rows = [
        {"ens_mean": 60.0 + i, "ens_var": 4.0 + i * 0.1, "settled_temp_f": 61.0 + i}
        for i in range(40)
    ]
    monkeypatch.setattr("tracker.get_emos_training_data", lambda: rows)
    return rows


@pytest.fixture()
def emos_training_rows_thin(monkeypatch):
    """Only 12 rows with real ens_var -- below the >=40 activation floor,
    for testing the floor-refusal path itself."""
    rows = [
        {"ens_mean": 60.0 + i, "ens_var": 4.0 + i * 0.1, "settled_temp_f": 61.0 + i}
        for i in range(12)
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
