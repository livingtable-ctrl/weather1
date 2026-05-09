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

    def test_accuracy_halt_blocks_market_scan(self, minimal_mocks, monkeypatch):
        """cmd_cron exits early when the accuracy circuit breaker is active."""
        import main
        import paper

        monkeypatch.setattr(paper, "is_accuracy_halted", lambda: True)

        scan_called = []
        monkeypatch.setattr(
            main, "get_weather_markets", lambda c: scan_called.append(1) or []
        )
        client = MagicMock()
        main.cmd_cron(client)
        assert scan_called == [], "market scan should be skipped on accuracy halt"

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
