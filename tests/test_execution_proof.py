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
    # These are on main directly
    monkeypatch.setattr("main._daily_paper_spend", lambda: 0.0)
    monkeypatch.setattr("main._current_forecast_cycle", lambda: "12z")
    monkeypatch.setattr(
        "main.execution_log.was_ordered_this_cycle", lambda t, s, c: False
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

    monkeypatch.setattr("main.place_paper_order", fake_place)

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

    monkeypatch.setattr("main.place_paper_order", boom)

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

    monkeypatch.setattr("main.place_paper_order", fake_place)

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
