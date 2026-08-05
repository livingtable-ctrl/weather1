"""
Tests for P0.1 — Trade execution proof.
_auto_place_trades must return the count of placed trades and log failures.
"""

import datetime
import logging


def _make_opp(ticker="KXTEST", edge=0.30):
    """Minimal flat opportunity dict accepted by _auto_place_trades."""
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "side": "yes",
        "_city": "NYC",
        "_date": datetime.date.today() + datetime.timedelta(days=1),
        "ci_adjusted_kelly": 0.15,
        "fee_adjusted_kelly": 0.15,
        "market_prob": 0.50,
        "forecast_prob": 0.80,
        "net_edge": edge,
        "model_consensus": True,
        "method": "ensemble",
        "condition": {"type": "above", "threshold": 82.0},
    }


def _stub_auto_prereqs(monkeypatch):
    """Stub out all guards so _auto_place_trades reaches the trade loop."""
    # These are imported from paper inside _auto_place_trades, so patch on paper module
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: False)
    monkeypatch.setattr("paper.is_daily_loss_halted", lambda c: False)
    monkeypatch.setattr("paper.is_streak_paused", lambda: False)
    monkeypatch.setattr("paper.get_open_trades", lambda: [])
    monkeypatch.setattr("paper.kelly_quantity", lambda kf, p, cap=None, method=None: 5)
    monkeypatch.setattr(
        "paper.portfolio_kelly_fraction", lambda kf, c, d, side=None: kf
    )
    # These now live in order_executor (re-exported by main)
    monkeypatch.setattr("order_executor._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("order_executor._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr(
        "order_executor.execution_log.was_ordered_this_cycle", lambda t, s, c: False
    )
    # Stub execution_log writes — prevents P0-10 pre-log from writing to the real
    # DB and causing was_traded_today to return True on subsequent test runs
    monkeypatch.setattr(
        "order_executor.execution_log.was_traded_today", lambda t, s: False
    )
    monkeypatch.setattr("order_executor.execution_log.log_order", lambda *a, **kw: 999)
    monkeypatch.setattr(
        "order_executor.execution_log.log_order_result", lambda *a, **kw: None
    )
    # Stub system health — CI environments can report 100% CPU and block trades
    import system_health

    monkeypatch.setattr(
        system_health,
        "check_system_health",
        lambda: system_health.HealthStatus(healthy=True, reason=""),
    )


# ── _auto_place_trades returns placed count ──────────────────────────────────


def test_auto_place_trades_returns_placed_count(monkeypatch, tmp_path):
    """_auto_place_trades must return the count of actually placed trades."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    _stub_auto_prereqs(monkeypatch)

    placed_tickers = []

    def fake_place(ticker, side, qty, price, **kwargs):
        placed_tickers.append(ticker)
        return {"id": len(placed_tickers), "status": "open", "cost": price * qty}

    monkeypatch.setattr("order_executor.place_paper_order", fake_place)

    import main

    result = main._auto_place_trades([_make_opp("KXTEST1"), _make_opp("KXTEST2")])
    assert result == 2, f"Expected 2 placed trades, got {result}"
    assert "KXTEST1" in placed_tickers
    assert "KXTEST2" in placed_tickers


def test_auto_place_trades_returns_zero_when_halted(monkeypatch):
    """Returns 0 immediately when drawdown guard is active."""
    # is_paused_drawdown is imported from paper inside _auto_place_trades
    monkeypatch.setattr("paper.is_paused_drawdown", lambda: True)

    import main

    result = main._auto_place_trades([_make_opp()])
    assert result == 0


# ── _auto_place_trades logs paper order failure ──────────────────────────────


def test_auto_place_trades_logs_paper_failure(monkeypatch, caplog):
    """If place_paper_order raises a non-ValueError, it must be logged."""
    _stub_auto_prereqs(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("db locked")

    monkeypatch.setattr("order_executor.place_paper_order", boom)

    import main

    with caplog.at_level(logging.WARNING):
        result = main._auto_place_trades([_make_opp("KXFAIL")])

    assert result == 0
    assert any(
        "db locked" in r.message or "KXFAIL" in r.message for r in caplog.records
    ), (
        "place_paper_order failure must be logged.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


def test_auto_place_trades_logs_analysis_attempt_failure(monkeypatch, caplog, tmp_path):
    """If log_analysis_attempt fails after a successful trade, it must be logged."""
    from unittest.mock import patch

    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    _stub_auto_prereqs(monkeypatch)

    placed = []

    def fake_place(ticker, side, qty, price, **kwargs):
        placed.append(ticker)
        return {"id": 1, "status": "open", "cost": price * qty}

    monkeypatch.setattr("order_executor.place_paper_order", fake_place)

    import main

    with patch(
        "tracker.log_analysis_attempt", side_effect=RuntimeError("tracker full")
    ):
        with caplog.at_level(logging.WARNING):
            result = main._auto_place_trades([_make_opp("KXTEST")])

    # Trade must still be placed even when logging fails
    assert result == 1
    assert "KXTEST" in placed
    assert any("tracker full" in r.message for r in caplog.records), (
        "log_analysis_attempt failure must be logged.\n"
        f"Records: {[r.message for r in caplog.records]}"
    )


# ── L1-D: paper order failure must be printed visibly ────────────────────────


def test_l1d_paper_failure_printed_to_console(monkeypatch, capsys):
    """L1-D: place_paper_order failure must print a visible error — not just log.

    A WARNING log is silent when the operator is watching console output.
    The error must appear in stdout/stderr so it cannot be missed.
    """
    _stub_auto_prereqs(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr("order_executor.place_paper_order", boom)

    import main

    result = main._auto_place_trades([_make_opp("KXPRINTFAIL")])

    assert result == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "KXPRINTFAIL" in output and ("disk full" in output or "FAILED" in output), (
        "L1-D: paper order failure must be printed to console (stdout/stderr), "
        "not only logged to the WARNING logger.\n"
        f"Console output was: {output!r}"
    )


# ── L1-B: price re-fetch before placement ─────────────────────────────────────


class _FakeClient:
    """Minimal KalshiClient stand-in for price-refresh tests."""

    def __init__(self, implied_prob: float):
        self._implied_prob = implied_prob

    def get_market(self, ticker: str) -> dict:
        # Return a market dict whose yes_bid/yes_ask give the desired implied prob.
        # implied_prob = (yes_bid + yes_ask) / 2  →  symmetric spread: both at prob*100
        cents = int(round(self._implied_prob * 100))
        return {
            "ticker": ticker,
            "yes_bid": cents,
            "yes_ask": cents,
            "no_bid": 100 - cents,
            "no_ask": 100 - cents,
        }


def test_l1b_price_refresh_uses_fresh_market_prob(monkeypatch):
    """L1-B: when a client is supplied, entry_price must reflect the re-fetched
    market probability, not the stale value in the analysis dict.

    Scenario: analysis recorded market_prob=0.50 (stale), but the live market
    has moved to 0.60.  Entry price for YES side should be 0.60, not 0.50.
    """
    _stub_auto_prereqs(monkeypatch)

    captured_prices: list[float] = []

    def _capture_place(ticker, side, qty, price, **kwargs):
        captured_prices.append(price)
        return {"id": 1, "status": "open", "cost": price * qty}

    monkeypatch.setattr("order_executor.place_paper_order", _capture_place)

    import main

    opp = _make_opp("KXREFRESH")  # market_prob=0.50 (stale)
    client = _FakeClient(implied_prob=0.60)  # live price is 0.60

    result = main._auto_place_trades([opp], client=client)
    assert result == 1, "Expected 1 placed trade"
    assert len(captured_prices) == 1
    assert abs(captured_prices[0] - 0.60) < 0.01, (
        f"L1-B: entry_price should be the fresh market price 0.60, "
        f"got {captured_prices[0]:.3f}. Stale analysis price (0.50) was used."
    )


def test_l1b_price_refresh_skips_when_edge_gone(monkeypatch):
    """L1-B: if the fresh market price eliminates our edge, trade must be skipped.

    Scenario: analysis said YES at market_prob=0.50, forecast_prob=0.80.
    Market moved to 0.85 before placement — we'd now be buying YES at 0.85
    against a forecast of 0.80, a *negative* edge.  Must skip.
    """
    _stub_auto_prereqs(monkeypatch)

    placed: list[str] = []

    def _capture_place(ticker, side, qty, price, **kwargs):
        placed.append(ticker)
        return {"id": 1, "status": "open", "cost": price * qty}

    monkeypatch.setattr("order_executor.place_paper_order", _capture_place)

    import main

    opp = _make_opp("KXEDGE_GONE")  # market_prob=0.50, forecast_prob=0.80, YES
    client = _FakeClient(implied_prob=0.85)  # market moved above our forecast!

    result = main._auto_place_trades([opp], client=client)
    assert result == 0, (
        f"L1-B: trade should be skipped when fresh price (0.85) exceeds "
        f"forecast_prob (0.80), got placed={placed}"
    )


def test_l1b_no_client_uses_stale_price(monkeypatch):
    """L1-B: without a client (paper-only mode), stale analysis price is used.

    This tests the graceful fallback path — no crash, trade proceeds at the
    price recorded during analysis.
    """
    _stub_auto_prereqs(monkeypatch)

    captured_prices: list[float] = []

    def _capture_place(ticker, side, qty, price, **kwargs):
        captured_prices.append(price)
        return {"id": 1, "status": "open", "cost": price * qty}

    monkeypatch.setattr("order_executor.place_paper_order", _capture_place)

    import main

    opp = _make_opp("KXNOCLIENT")  # market_prob=0.50
    result = main._auto_place_trades([opp], client=None)
    assert result == 1, "Expected 1 placed trade in paper-only mode"
    assert len(captured_prices) == 1
    # Without a client, entry_price comes from the stale market_prob=0.50
    assert abs(captured_prices[0] - 0.50) < 0.01, (
        f"L1-B fallback: expected stale entry_price 0.50, got {captured_prices[0]:.3f}"
    )
