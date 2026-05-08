"""Shared pytest fixtures for the Kalshi weather markets test suite."""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolate_retired_strategies(tmp_path, monkeypatch):
    """Redirect tracker._RETIRED_PATH to an empty temp file for every test.

    Prevents the real retired_strategies.json on disk (which may have
    'ensemble' retired) from blocking analyze_trade in unrelated tests.
    Tests that exercise the retirement gate write their own data to the
    redirected path via auto_retire_strategies(), so they still work correctly.
    Tests that need a specific retired state use patch() context managers.
    """
    monkeypatch.setattr("tracker._RETIRED_PATH", tmp_path / "retired_strategies.json")


@pytest.fixture(autouse=True)
def isolate_circuit_breaker_state(tmp_path, monkeypatch):
    """Redirect circuit_breaker._CB_STATE_PATH to a per-test temp file.

    CircuitBreaker.__init__ now calls _load_state() which reads from
    _CB_STATE_PATH. Without isolation, state from one test (or from the
    real data/ directory) leaks into subsequent tests, causing spurious
    open-circuit failures.
    """
    import circuit_breaker

    monkeypatch.setattr(circuit_breaker, "_CB_STATE_PATH", tmp_path / ".cb_state.json")


@pytest.fixture(autouse=True)
def reset_open_meteo_circuit_breaker():
    """Reset all weather_markets circuit breakers before every test.

    There are four CBs (_forecast_cb, _ensemble_cb, _weatherapi_cb, _pirate_cb),
    all module-level singletons. Any test that trips one leaves it open for
    subsequent tests, causing false failures (get_weather_forecast returns None).
    """
    import weather_markets

    for cb in (
        weather_markets._forecast_cb,
        weather_markets._ensemble_cb,
        weather_markets._weatherapi_cb,
        weather_markets._pirate_cb,
    ):
        cb.record_success()  # clears _failure_count and _opened_at
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
    return date.today() + timedelta(days=3)


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


@pytest.fixture()
def mock_market():
    """Standard mock Kalshi market dict — must stay in sync with production field names."""
    return {
        "ticker": "KXTEMP-25-NYC-B70-T",
        "volume_fp": 500,
        "volume": 500,
        "open_interest_fp": 1000,
        "open_interest": 1000,
        "yes_bid": "0.60",
        "yes_ask": "0.65",
        "close_time": "2026-04-20T20:00:00Z",
        "_forecast": None,
        "_date": None,
        "_city": None,
        "_hour": None,
        "data_fetched_at": None,
    }


@pytest.fixture
def mock_balance_1000(tmp_path, monkeypatch):
    """Patch paper to use a temp data file and start with $1000 balance."""
    monkeypatch.setattr("paper.DATA_PATH", tmp_path / "paper_trades.json")
    import importlib

    import paper

    importlib.reload(paper)
    yield paper
