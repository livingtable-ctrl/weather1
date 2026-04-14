"""Tests for P1.1+P1.2 — _validate_trade_opportunity() pre-trade gate."""

import datetime
import time


def _opp(edge: float = 0.20, kelly: float = 0.10, ticker: str = "KXTEST") -> dict:
    return {
        "ticker": ticker,
        "recommended_side": "yes",
        "_city": "NYC",
        "_date": datetime.date.today() + datetime.timedelta(days=1),
        "ci_adjusted_kelly": kelly,
        "fee_adjusted_kelly": kelly,
        "market_prob": 0.50,
        "forecast_prob": 0.70,
        "net_edge": edge,
        "model_consensus": True,
        "data_fetched_at": time.time(),
    }


def test_validate_rejects_zero_edge():
    from main import _validate_trade_opportunity

    ok, reason = _validate_trade_opportunity(_opp(edge=0.0))
    assert not ok
    assert "edge" in reason.lower()


def test_validate_rejects_negative_edge():
    from main import _validate_trade_opportunity

    ok, reason = _validate_trade_opportunity(_opp(edge=-0.05))
    assert not ok
    assert "edge" in reason.lower()


def test_validate_rejects_zero_kelly():
    from main import _validate_trade_opportunity

    ok, reason = _validate_trade_opportunity(_opp(kelly=0.0))
    assert not ok
    assert "kelly" in reason.lower()


def test_validate_rejects_missing_ticker():
    from main import _validate_trade_opportunity

    ok, reason = _validate_trade_opportunity(_opp(ticker=""))
    assert not ok
    assert "ticker" in reason.lower()


def test_validate_rejects_stale_data():
    from main import _validate_trade_opportunity

    opp = _opp()
    opp["data_fetched_at"] = time.time() - 99999  # very stale
    ok, reason = _validate_trade_opportunity(opp)
    assert not ok
    assert "stale" in reason.lower()


def test_validate_accepts_good_opportunity():
    from main import _validate_trade_opportunity

    ok, reason = _validate_trade_opportunity(_opp(edge=0.20, kelly=0.10))
    assert ok, f"Expected valid opp but got: {reason}"


def test_validate_no_fetched_at_accepted():
    """Missing data_fetched_at should not be treated as stale."""
    from main import _validate_trade_opportunity

    opp = _opp()
    del opp["data_fetched_at"]
    ok, reason = _validate_trade_opportunity(opp)
    assert ok, f"Opp without data_fetched_at should be accepted: {reason}"
