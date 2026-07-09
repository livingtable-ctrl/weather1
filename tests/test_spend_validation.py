"""
Tests for the MAX_DAILY_SPEND vs balance validation check in cron.py
(re-exported through main.py).
"""

from __future__ import annotations

import logging

import pytest


def test_spend_cap_warning_logged_when_exceeds_balance(monkeypatch, caplog):
    """Warning logged when MAX_DAILY_SPEND exceeds current paper balance."""
    import main
    import paper
    import utils

    # F8: cron._check_spend_cap_vs_balance now reads utils.MAX_DAILY_SPEND
    # directly (a module constant resolved once at import) instead of a second
    # os.getenv() with its own default — monkeypatch the attribute itself,
    # not the env var, per this repo's established pattern (setenv can't
    # reach an already-imported module constant).
    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 500.0)
    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)


def test_no_warning_when_spend_cap_below_balance(monkeypatch, caplog):
    """No warning when MAX_DAILY_SPEND is below current balance."""
    import main
    import paper
    import utils

    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 50.0)
    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert not any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)


def test_no_warning_when_spend_cap_zero(monkeypatch, caplog):
    """No warning when MAX_DAILY_SPEND is 0 (disabled)."""
    import main
    import paper
    import utils

    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 0.0)
    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert not any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records)


def test_uses_real_utils_default_not_a_second_zero_default(monkeypatch, caplog):
    """F8 regression: the check used to read os.getenv("MAX_DAILY_SPEND", "0")
    directly — an unset env var silently resolved to 0 (check always inert)
    instead of utils.py's real "500.0" default. It must now agree with
    whatever utils.MAX_DAILY_SPEND actually resolves to."""
    import main
    import paper
    import utils

    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 500.0)  # utils.py's real default
    monkeypatch.setattr(paper, "get_balance", lambda: 100.0)

    with caplog.at_level(logging.WARNING):
        main._check_spend_cap_vs_balance()

    assert any("MAX_DAILY_SPEND" in rec.message for rec in caplog.records), (
        "500 > 100 must warn under utils.py's real default — the old code's "
        "second env-read defaulted to 0 and never warned in this exact scenario"
    )


def test_balance_fetch_failure_does_not_crash_full_cron_cycle(
    tmp_path, monkeypatch, caplog
):
    """F8: _check_spend_cap_vs_balance() itself has no internal guard (a
    paper.get_balance() failure raises) — the call site inside _cmd_cron_body
    must catch it so this cosmetic config-mistake warning can never crash the
    whole cron cycle before settlement/stop-losses get a chance to run."""
    from unittest.mock import MagicMock

    import alerts
    import cron
    import main
    import paper
    import utils

    monkeypatch.setattr(cron, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(cron, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
    monkeypatch.setattr(cron, "LOCK_PATH", tmp_path / ".cron_lock")
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "_check_manual_override", lambda: False)
    sync_calls = []
    monkeypatch.setattr(main, "sync_outcomes", lambda client: sync_calls.append(1) or 0)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
    monkeypatch.setattr(alerts, "run_anomaly_check", lambda **kw: ([], False))
    monkeypatch.setattr(alerts, "run_black_swan_check", lambda **kw: [])
    monkeypatch.setattr(utils, "MAX_DAILY_SPEND", 500.0)
    monkeypatch.setattr(
        paper, "get_balance", lambda: (_ for _ in ()).throw(RuntimeError("db locked"))
    )

    with caplog.at_level(logging.WARNING):
        try:
            main.cmd_cron(MagicMock())
        except SystemExit:
            pass
        except RuntimeError:
            pytest.fail(
                "a paper.get_balance() failure in the spend-cap check must not "
                "crash the whole cron cycle"
            )

    assert sync_calls, (
        "settlement must still run even though the spend-cap check failed"
    )
