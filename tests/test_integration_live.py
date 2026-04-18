"""
Live Kalshi API integration tests.

These tests make real network calls to the Kalshi demo environment.
They are excluded from normal pytest runs and must be explicitly opted in:

    pytest -m integration

Requires KALSHI_ENV=demo and valid KALSHI_API_KEY / KALSHI_API_SECRET in .env.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


def _demo_client():
    """Return a KalshiClient pointed at the demo environment, or skip if not configured."""
    if os.getenv("KALSHI_ENV") != "demo":
        pytest.skip("KALSHI_ENV != demo — skipping live integration test")
    try:
        from kalshi_client import KalshiClient

        return KalshiClient()
    except Exception as e:
        pytest.skip(f"Could not initialise KalshiClient: {e}")


@pytest.mark.integration
def test_fetch_markets_returns_list():
    """Fetching weather markets from demo API returns a non-empty list."""
    client = _demo_client()
    from kalshi_client import get_weather_markets

    markets = get_weather_markets(client)
    assert isinstance(markets, list)
    assert len(markets) > 0


@pytest.mark.integration
def test_market_has_required_fields():
    """Each market dict has the minimum keys the rest of the system relies on."""
    client = _demo_client()
    from kalshi_client import get_weather_markets

    markets = get_weather_markets(client)
    required = {"ticker", "yes_bid", "yes_ask"}
    for m in markets[:5]:
        missing = required - set(m.keys())
        assert not missing, f"Market {m.get('ticker')} missing keys: {missing}"


@pytest.mark.integration
def test_analyze_trade_returns_dict_for_live_market():
    """analyze_trade() returns a non-None result for at least one live market."""
    client = _demo_client()
    from kalshi_client import get_weather_markets
    from weather_markets import analyze_trade, enrich_market

    markets = get_weather_markets(client)
    for raw in markets[:10]:
        enriched = enrich_market(raw)
        if enriched is None:
            continue
        result = analyze_trade(enriched)
        if result is not None:
            assert "forecast_prob" in result
            assert "edge" in result or "net_edge" in result
            return  # at least one market analyzed successfully

    pytest.skip("No analyzable markets found in first 10 results")
