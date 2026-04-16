"""Tests for P1.1+P1.2 — _validate_trade_opportunity() pre-trade gate."""

import datetime
import time
from unittest.mock import patch

import pytest

_HEALTHY = (
    "system_health.check_system_health",
    lambda: __import__("system_health").HealthStatus(True, ""),
)


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


@pytest.fixture(autouse=True)
def healthy_system():
    """Prevent CPU/memory checks from interfering with trade-logic assertions."""
    import system_health

    with patch.object(
        system_health,
        "check_system_health",
        return_value=system_health.HealthStatus(True, ""),
    ):
        yield


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


def test_validate_missing_ensemble_spread_uses_flat_threshold():
    """Without ensemble_spread key, fall back to flat PAPER_MIN_EDGE threshold (0.05)."""
    from main import _validate_trade_opportunity

    # edge=0.04 is below flat threshold of 0.05, should be rejected
    opp = _opp(edge=0.04)
    # Ensure no ensemble_spread key at all
    assert "ensemble_spread" not in opp
    ok, reason = _validate_trade_opportunity(opp)
    assert not ok
    assert "edge" in reason.lower()


def test_validate_low_spread_tier_rejects_edge_below_threshold():
    """ensemble_spread=0.20 (LOW tier) requires edge >= 0.10; edge=0.08 should be rejected."""
    from main import _validate_trade_opportunity

    opp = _opp(edge=0.08)
    opp["ensemble_spread"] = 0.20  # LOW tier, paper min=0.10
    ok, reason = _validate_trade_opportunity(opp)
    assert not ok
    assert "edge" in reason.lower()
    assert "spread" in reason.lower()  # reason should mention spread info
