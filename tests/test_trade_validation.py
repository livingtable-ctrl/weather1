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


class TestFlashCrashPriceFeed:
    """F3: the flash-crash circuit breaker read opp.get("yes_bid")/opp.get("yes_ask")
    directly, but opp (analyze_trade's result) never carries those keys — it had
    never once received a real price. Fixed by threading the real market dict
    through as a separate `market` param."""

    def test_market_dict_feeds_a_real_price_to_the_breaker(self):
        from circuit_breaker import flash_crash_cb
        from main import _validate_trade_opportunity

        market = {"yes_bid": 40, "yes_ask": 44}  # cents; parse_market_price → 0.42
        calls = []
        with patch.object(
            flash_crash_cb,
            "check",
            side_effect=lambda ticker, price: calls.append((ticker, price)) or False,
        ):
            _validate_trade_opportunity(_opp(), market=market)

        assert calls, "flash_crash_cb.check must be called when a market dict is given"
        ticker, price = calls[0]
        assert price == pytest.approx(0.42), (
            f"expected the real mid-price derived from the market dict, got {price}"
        )

    def test_ws_cached_price_is_preferred_over_market_dict(self):
        """A fresher WebSocket-cached mid-price should win over the REST-derived one."""
        from circuit_breaker import flash_crash_cb
        from main import _validate_trade_opportunity

        opp = _opp()
        opp["_ws_mid_price"] = 0.61
        market = {"yes_bid": 40, "yes_ask": 44}
        calls = []
        with patch.object(
            flash_crash_cb,
            "check",
            side_effect=lambda ticker, price: calls.append((ticker, price)) or False,
        ):
            _validate_trade_opportunity(opp, market=market)

        assert calls and calls[0][1] == pytest.approx(0.61)

    def test_no_market_dict_does_not_crash(self):
        """Callers that genuinely have no market dict (market=None, the default)
        must not crash — just skip the breaker check, same as before this fix."""
        from main import _validate_trade_opportunity

        ok, _ = _validate_trade_opportunity(_opp())
        assert ok
