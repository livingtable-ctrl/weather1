"""Shared pytest fixtures for the Kalshi weather markets test suite."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_open_meteo_circuit_breaker():
    """Reset the open_meteo circuit breaker before every test.

    The circuit breaker is a module-level singleton in weather_markets.py.
    Tests that make real (or mocked) API calls can trip it, causing subsequent
    tests in the same run to see the circuit as open and return None instead of
    forecast data, producing false failures.
    """
    import weather_markets

    weather_markets._ensemble_cb.record_success()  # clears _failure_count and _opened_at
    yield


FIXTURES = Path(__file__).parent / "fixtures"


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
    """Load sample forecast from fixture JSON file."""
    return json.loads((FIXTURES / "sample_forecast.json").read_text())


@pytest.fixture
def target_date():
    return date(2025, 4, 9)


@pytest.fixture
def sample_markets():
    """Load sample markets from fixture JSON file."""
    return json.loads((FIXTURES / "sample_markets.json").read_text())


@pytest.fixture
def mock_kalshi_client(sample_markets):
    """Mock Kalshi API client with sample market data."""
    client = MagicMock()
    client.get_markets.return_value = sample_markets
    client.get_market.side_effect = lambda ticker: next(
        (m for m in sample_markets if m["ticker"] == ticker), {}
    )
    return client


@pytest.fixture
def mock_forecast(sample_forecast):
    """Patch get_weather_forecast to return fixture data."""
    with patch("weather_markets.get_weather_forecast") as mock:
        mock.side_effect = lambda city, date: sample_forecast.get(city)
        yield mock


@pytest.fixture
def mock_balance_1000(tmp_path, monkeypatch):
    """Patch paper to use a temp data file and start with $1000 balance."""
    monkeypatch.setattr("paper.DATA_PATH", tmp_path / "paper_trades.json")
    import importlib

    import paper

    importlib.reload(paper)
    yield paper
