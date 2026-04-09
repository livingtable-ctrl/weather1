"""Shared pytest fixtures for the Kalshi weather markets test suite."""

from datetime import date

import pytest


@pytest.fixture
def sample_market():
    """Minimal market dict that passes is_liquid and parse_market_price."""
    return {
        "ticker": "KXHIGHNYCX-25Apr09-T60",
        "series_ticker": "KXHIGHNYCX",
        "title": "Will NYC reach 60°F high on Apr 9?",
        "yes_bid": 55,
        "yes_ask": 60,
        "no_bid": 40,
        "no_ask": 45,
        "volume": 5000,
        "open_interest": 200,
        "close_time": "2025-04-09T23:59:00Z",
        "status": "open",
    }


@pytest.fixture
def sample_forecast():
    """Typical forecast dict as returned by get_weather_forecast."""
    return {
        "high_f": 62.0,
        "low_f": 48.0,
        "precip_in": 0.0,
        "high_range": (59.0, 65.0),
        "low_range": (46.0, 50.0),
        "models_used": 3,
    }


@pytest.fixture
def target_date():
    return date(2025, 4, 9)
