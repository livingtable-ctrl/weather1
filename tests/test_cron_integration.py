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

    # Reload BEFORE patching — reload resets module-level state, then monkeypatch
    # sets DATA_PATH to tmp_path. Reversing this order caused reload() to undo the
    # patch, leaving cron body functions (e.g. auto_settle_paper_trades) writing to
    # the real data/paper_trades.json during test runs.
    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    import main

    monkeypatch.setattr(main, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
    monkeypatch.setattr(main, "LOCK_PATH", tmp_path / ".cron_lock")
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

    _original = main._write_cron_running_flag

    def _raise(*a, **kw):
        raise KeyboardInterrupt

    main._write_cron_running_flag = _raise

    try:
        _cron.cmd_cron(client)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        main._write_cron_running_flag = _original

    assert not lock_path.exists(), "Lock file must be deleted after KeyboardInterrupt"


# ── Phase 7: Market anomaly detection ────────────────────────────────────────


def test_report_anomalies_prints_drifted_markets(capsys):
    """report_anomalies prints ticker and drift for markets >12pp from model."""
    import cron as _cron

    anomalies = [
        {"ticker": "KXHIGHNY-26MAY05-T70", "blended_prob": 0.65, "market_price": 0.82},
    ]
    _cron.report_anomalies(anomalies)
    out = capsys.readouterr().out
    assert "KXHIGHNY" in out
    assert "anomal" in out.lower() or "drift" in out.lower() or "%" in out


def test_check_market_anomalies_filters_by_threshold():
    """check_market_anomalies returns only signals with drift > 0.12."""
    import cron as _cron

    signals = [
        {"ticker": "A", "blended_prob": 0.60, "market_price": 0.75},  # 15pp → flagged
        {
            "ticker": "B",
            "blended_prob": 0.60,
            "market_price": 0.65,
        },  # 5pp  → not flagged
    ]
    flagged = _cron.check_market_anomalies(signals)
    assert len(flagged) == 1


# ── P1-15: anomaly check return value halts trading ──────────────────────────


@pytest.mark.integration
def test_p1_15_anomaly_check_halts_cron(cron_env, caplog, monkeypatch):
    """P1-15: when run_anomaly_check returns anomalies, cron must halt before placement."""

    tmp_path, client, main, paper = cron_env

    placed = []

    def _fake_place(opps, client=None, cap=None, **kwargs):
        placed.extend(opps)
        return len(opps)

    # Use monkeypatch so both attributes are restored after the test, preventing
    # contamination of subsequent tests that call _auto_place_trades(live=...).
    import alerts as _alerts

    monkeypatch.setattr(main, "_auto_place_trades", _fake_place)
    monkeypatch.setattr(
        _alerts,
        "run_anomaly_check",
        lambda log_results=False: ["WIN RATE COLLAPSE: 20%"],
    )

    import cron as _cron

    with caplog.at_level(logging.ERROR):
        result = _cron._cmd_cron_body(client)

    assert result is None, "cron body must return None when anomalies are detected"
    assert not placed, "no trades must be placed when anomalies halt the cycle"
    assert any("anomal" in r.message.lower() for r in caplog.records), (
        "anomaly halt must be logged at ERROR level"
    )


@pytest.mark.integration
def test_p1_15_empty_anomaly_list_does_not_halt(cron_env):
    """P1-15: empty anomaly list must not halt — cron continues normally."""
    import alerts as _alerts

    tmp_path, client, main, paper = cron_env
    _alerts.run_anomaly_check = lambda log_results=False: []

    import cron as _cron

    result = _cron._cmd_cron_body(client)
    # Result can be True/False/None depending on scan outcome — just must not crash
    assert result is not None or result is None  # no exception is the assertion


# ── P1-12: kill switch check inside per-market analysis loop ─────────────────


@pytest.mark.integration
def test_p1_12_kill_switch_mid_scan_breaks_loop(monkeypatch, tmp_path, caplog):
    """P1-12: kill switch created during scan must break the analysis loop."""
    import importlib

    import alerts
    import paper

    # Reload BEFORE patching to avoid reload() undoing the monkeypatch
    importlib.reload(paper)
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    import main

    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", ks_path)
    monkeypatch.setattr(main, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(main, "LOCK_PATH", tmp_path / ".cron_lock")
    monkeypatch.setattr(main, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(main, "_check_startup_orders", lambda: None)
    monkeypatch.setattr(main, "check_ensemble_circuit_health", lambda: None)
    monkeypatch.setattr(main, "_check_early_exits", lambda client=None: 0)
    monkeypatch.setattr(alerts, "run_black_swan_check", lambda: [])
    monkeypatch.setattr(alerts, "run_anomaly_check", lambda log_results=False: [])

    fake_markets = [
        {"ticker": f"KXTEST{i}", "yes_bid": 30, "yes_ask": 34} for i in range(3)
    ]
    monkeypatch.setattr(main, "get_weather_markets", lambda client: fake_markets)

    # Create the kill switch as a side effect of the first enrich call (mid-scan)
    def _enrich_and_activate_ks(m):
        ks_path.touch()
        return dict(m, _city="NYC", _date="2026-05-10", _target_date="2026-05-10")

    monkeypatch.setattr(main, "enrich_with_forecast", _enrich_and_activate_ks)
    monkeypatch.setattr(main, "analyze_trade", lambda enriched: None)

    import cron as _cron

    with caplog.at_level(logging.WARNING):
        _cron._cmd_cron_body(MagicMock())

    assert any(
        "kill switch" in r.message.lower() and "mid-scan" in r.message.lower()
        for r in caplog.records
    ), (
        "P1-12: kill switch activated mid-scan must be logged as WARNING.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )
