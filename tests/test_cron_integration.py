"""
Integration tests for cmd_cron() orchestration layer.

All external calls (weather APIs, Kalshi client, alerts) are mocked.
These tests cover the orchestration logic — stop-loss ordering, VaR gate,
drift tightening — that unit tests cannot reach.
"""

from __future__ import annotations

import importlib
import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def cron_env(tmp_path, monkeypatch):
    """Isolate cmd_cron from real data, networks, and alerts."""
    import alerts
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)

    import main

    monkeypatch.setattr(main, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
    monkeypatch.setattr(alerts, "run_black_swan_check", lambda: [])
    monkeypatch.setattr(alerts, "run_anomaly_check", lambda log_results=False: None)

    client = MagicMock()
    yield tmp_path, client, main, paper


@pytest.mark.integration
def test_cron_places_paper_trade_on_strong_signal(cron_env):
    """Full cron run with a mocked strong signal: _auto_place_trades called with strong_opps."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR17-B70", "yes_bid": 30, "yes_ask": 34}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-17", _target_date="2026-04-17"
    )
    fake_analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.30,
        "days_out": 1,
        "target_date": "2026-04-17",
    }

    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(placed_calls) > 0, (
        "Expected at least one strong opportunity passed to _auto_place_trades"
    )


@pytest.mark.integration
def test_cron_drawdown_guard_blocks_auto_trades(cron_env):
    """When drawdown guard is active, _auto_place_trades returns 0 and places nothing."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR17-B70", "yes_bid": 30, "yes_ask": 34}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-17", _target_date="2026-04-17"
    )
    fake_analysis = {
        "edge": STRONG_EDGE + 0.05,
        "net_edge": STRONG_EDGE + 0.05,
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.30,
        "days_out": 1,
        "target_date": "2026-04-17",
    }

    auto_place_returns: list[int] = []

    def _instrumented_auto_place(opps, client=None, cap=None, **kwargs):
        # Run real function but capture return value
        with patch("paper.is_paused_drawdown", return_value=True):
            result = (
                main._auto_place_trades.__wrapped__(opps, client=client, cap=cap)
                if hasattr(main._auto_place_trades, "__wrapped__")
                else 0
            )
        auto_place_returns.append(result)
        return result

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=True),
        patch("paper.is_daily_loss_halted", return_value=False),
        patch("paper.is_streak_paused", return_value=False),
        patch("paper.get_open_trades", return_value=[]),
        patch(
            "paper.place_paper_order",
            side_effect=AssertionError("should not be called"),
        ),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass
        except AssertionError as e:
            pytest.fail(f"Drawdown guard failed: {e}")


@pytest.mark.integration
def test_cron_drift_tightens_effective_edge(cron_env, caplog):
    """When Brier drift is detected, cmd_cron logs the tightened STRONG_EDGE threshold."""
    tmp_path, client, main, paper = cron_env
    from utils import DRIFT_TIGHTEN_EDGE, STRONG_EDGE

    expected_tightened = STRONG_EDGE + DRIFT_TIGHTEN_EDGE

    with (
        patch(
            "tracker.detect_brier_drift",
            return_value={
                "drifting": True,
                "message": "Brier degraded 0.08",
                "delta": 0.08,
            },
        ),
        caplog.at_level(logging.WARNING, logger="main"),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    warning_msgs = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    ]
    assert any(f"{expected_tightened:.2f}" in msg for msg in warning_msgs), (
        f"Expected tightened edge {expected_tightened:.2f} in warning log; got: {warning_msgs}"
    )


@pytest.mark.integration
def test_cron_kill_switch_halts_before_scan(cron_env):
    """If kill switch file exists, cmd_cron must return without calling get_weather_markets."""
    tmp_path, client, main, paper = cron_env

    # Activate kill switch
    ks = tmp_path / ".kill_switch"
    ks.write_text('{"reason":"test"}')
    monkeypatch_ks = patch.object(main, "KILL_SWITCH_PATH", ks)

    markets_called = []

    def _fake_markets(c):
        markets_called.append(c)
        return []

    with (
        monkeypatch_ks,
        patch.object(main, "get_weather_markets", side_effect=_fake_markets),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(markets_called) == 0, (
        "Kill switch: get_weather_markets must not be called"
    )


# ---------------------------------------------------------------------------
# L2-E regression tests: gate must use adjusted_edge, not net_edge
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cron_gate_blocks_when_adjusted_edge_below_threshold(cron_env):
    """A market whose net_edge clears STRONG_EDGE but adjusted_edge does not must
    NOT be auto-placed — the gate must use adjusted_edge (L2-E)."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR25-B70", "yes_bid": 30, "yes_ask": 34}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-25", _target_date="2026-04-25"
    )
    # net_edge passes STRONG_EDGE; adjusted_edge (net_edge * 0.4) does not
    net_edge_val = STRONG_EDGE + 0.05  # e.g. 0.20 if STRONG_EDGE=0.15
    fake_analysis = {
        "edge": net_edge_val,
        "net_edge": net_edge_val,
        "adjusted_edge": net_edge_val * 0.4,  # far-out market confidence penalty
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.75,
        "market_prob": 0.30,
        "days_out": 5,
        "target_date": "2026-04-25",
    }

    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(placed_calls) == 0, (
        "Gate must block when adjusted_edge < STRONG_EDGE even if net_edge passes (L2-E)"
    )


@pytest.mark.integration
def test_cron_gate_allows_when_adjusted_edge_above_threshold(cron_env):
    """A market whose adjusted_edge clears STRONG_EDGE must be auto-placed (L2-E)."""
    tmp_path, client, main, paper = cron_env
    from utils import STRONG_EDGE

    fake_market = {"ticker": "KXHIGH-NYC-26APR26-B70", "yes_bid": 30, "yes_ask": 34}
    fake_enriched = dict(
        fake_market, _city="NYC", _date="2026-04-26", _target_date="2026-04-26"
    )
    net_edge_val = STRONG_EDGE + 0.10
    fake_analysis = {
        "edge": net_edge_val,
        "net_edge": net_edge_val,
        "adjusted_edge": net_edge_val,  # high-confidence near-term market
        "signal": "STRONG BUY",
        "net_signal": "STRONG BUY",
        "recommended_side": "yes",
        "time_risk": "LOW",
        "forecast_prob": 0.80,
        "market_prob": 0.30,
        "days_out": 1,
        "target_date": "2026-04-26",
    }

    placed_calls: list = []

    def _fake_auto_place(opps, client=None, cap=None, **kwargs):
        placed_calls.extend(opps)
        return len(opps)

    with (
        patch.object(main, "get_weather_markets", return_value=[fake_market]),
        patch.object(main, "enrich_with_forecast", return_value=fake_enriched),
        patch.object(main, "analyze_trade", return_value=fake_analysis),
        patch.object(main, "_auto_place_trades", side_effect=_fake_auto_place),
        patch("tracker.detect_brier_drift", return_value={"drifting": False}),
        patch("paper.is_paused_drawdown", return_value=False),
    ):
        try:
            main.cmd_cron(client)
        except SystemExit:
            pass

    assert len(placed_calls) > 0, (
        "Gate must allow trade when adjusted_edge >= STRONG_EDGE (L2-E)"
    )


@pytest.mark.integration
def test_cron_lock_released_on_keyboard_interrupt(cron_env):
    """Lock must be cleaned up even if cron is interrupted mid-run."""
    import cron as _cron

    tmp_path, client, main, paper = cron_env
    lock_path = tmp_path / "cron.lock"
    main.LOCK_PATH = lock_path

    def _raise(*a, **kw):
        raise KeyboardInterrupt

    main._write_cron_running_flag = _raise

    try:
        _cron.cmd_cron(client)
    except (KeyboardInterrupt, SystemExit):
        pass

    assert not lock_path.exists(), "Lock file must be deleted after KeyboardInterrupt"
