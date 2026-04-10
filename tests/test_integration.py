"""
Integration tests for the analyze_trade pipeline (#112).

Tests verify that analyze_trade:
  - Returns a dict with the expected keys when given valid forecast data
  - Handles missing forecast data gracefully (returns None, does not raise)

All external I/O (Open-Meteo, NWS, climatology, climate indices, regime,
tracker bias) is mocked so the tests run offline without touching real APIs.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from unittest.mock import patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_enriched(
    ticker: str = "KXHIGHNY-26APR15-T68",
    city: str = "NYC",
    target_date: date = date(2026, 4, 15),
    forecast: dict | None = None,
) -> dict:
    """Build a minimal enriched market dict as produced by enrich_market()."""
    if forecast is None:
        forecast = {
            "high_f": 72.0,
            "low_f": 55.0,
            "precip_in": 0.0,
            "date": target_date.isoformat(),
        }
    return {
        "ticker": ticker,
        "series_ticker": "KXHIGHNY",
        "title": "NYC High Temp > 68°F on Apr 15",
        "yes_bid": 0.55,
        "yes_ask": 0.60,
        "no_bid": 0.40,
        "no_ask": 0.45,
        "volume": 3000,
        "open_interest": 1000,
        "close_time": "2026-04-15T23:59:00Z",
        "status": "open",
        "_city": city,
        "_date": target_date,
        "_hour": None,
        "_forecast": forecast,
    }


# ── Core return-value keys we always expect ───────────────────────────────────

REQUIRED_KEYS = {
    "forecast_prob",
    "market_prob",
    "edge",
    "signal",
    "recommended_side",
    "condition",
    "method",
    "data_quality",
}


class TestAnalyzePipeline:
    """Integration tests for analyze_trade() (#112)."""

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", return_value=0.62)
    @patch("weather_markets.climatological_prob", return_value=0.58)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch(
        "weather_markets.get_ensemble_temps",
        return_value=[
            70.0,
            71.0,
            72.0,
            73.0,
            68.0,
            69.0,
            71.5,
            70.5,
            72.5,
            67.0,
            70.0,
            71.0,
        ],
    )
    def test_analyze_trade_returns_result(
        self,
        mock_ens,
        mock_temp_adj,
        mock_clim,
        mock_nws,
        mock_obs,
    ):
        """analyze_trade returns a non-None dict with forecast_prob and edge keys."""
        from weather_markets import analyze_trade

        enriched = _make_enriched()
        result = analyze_trade(enriched)

        assert result is not None, "analyze_trade should return a dict for valid input"
        assert isinstance(result, dict)

        for key in REQUIRED_KEYS:
            assert key in result, f"Expected key '{key}' missing from result"

        # forecast_prob should be a probability in [0, 1]
        assert 0.0 <= result["forecast_prob"] <= 1.0

        # edge = forecast_prob - market_prob (no hard sign constraint, just finite)
        assert isinstance(result["edge"], float)

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", side_effect=Exception("NWS unavailable"))
    @patch("weather_markets.climatological_prob", return_value=None)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch("weather_markets.get_ensemble_temps", return_value=[])
    def test_analyze_trade_handles_missing_forecast(
        self,
        mock_ens,
        mock_temp_adj,
        mock_clim,
        mock_nws,
        mock_obs,
    ):
        """analyze_trade returns None when _forecast is missing (no forecast data)."""
        from weather_markets import analyze_trade

        enriched = _make_enriched(forecast=None)
        enriched["_forecast"] = None  # simulate no forecast available

        # Must not raise; must return None
        result = analyze_trade(enriched)
        assert result is None

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", return_value=None)
    @patch("weather_markets.climatological_prob", return_value=None)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch(
        "weather_markets.get_ensemble_temps",
        return_value=[
            70.0,
            71.0,
            72.0,
            73.0,
            68.0,
            69.0,
            71.5,
            70.5,
            72.5,
            67.0,
            70.0,
            71.0,
        ],
    )
    def test_analyze_trade_works_without_nws_or_clim(
        self,
        mock_ens,
        mock_temp_adj,
        mock_clim,
        mock_nws,
        mock_obs,
    ):
        """analyze_trade succeeds even when NWS and climatology return None."""
        from weather_markets import analyze_trade

        enriched = _make_enriched()
        result = analyze_trade(enriched)

        assert result is not None
        assert "forecast_prob" in result
        # data_quality should be reduced (only ensemble available)
        assert result["data_quality"] < 1.0

    def test_analyze_trade_missing_city_returns_none(self):
        """analyze_trade returns None when _city is missing."""
        from weather_markets import analyze_trade

        enriched = _make_enriched()
        enriched["_city"] = None

        result = analyze_trade(enriched)
        assert result is None

    def test_analyze_trade_missing_date_returns_none(self):
        """analyze_trade returns None when _date is missing."""
        from weather_markets import analyze_trade

        enriched = _make_enriched()
        enriched["_date"] = None

        result = analyze_trade(enriched)
        assert result is None

    def test_analyze_trade_invalid_input_raises(self):
        """analyze_trade raises ValueError for non-dict input."""
        from weather_markets import analyze_trade

        with pytest.raises(ValueError, match="must be a dict"):
            analyze_trade("not a dict")  # type: ignore[arg-type]


class TestAnalyzePipelineExtra:
    """Additional integration tests for below + precip conditions (#112)."""

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", return_value=0.45)
    @patch("weather_markets.climatological_prob", return_value=0.40)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch(
        "weather_markets.get_ensemble_temps",
        return_value=[
            50.0,
            51.0,
            52.0,
            53.0,
            54.0,
            55.0,
            56.0,
            57.0,
            58.0,
            59.0,
            60.0,
            61.0,
        ],
    )
    def test_analyze_trade_below_condition(
        self, mock_ens, mock_temp_adj, mock_clim, mock_nws, mock_obs
    ):
        """analyze_trade handles a LOW market (below condition) correctly."""
        from weather_markets import analyze_trade

        enriched = _make_enriched(
            ticker="KXLOWNY-26APR15-T55",
            city="NYC",
            target_date=date(2026, 4, 15),
            forecast={
                "high_f": 68.0,
                "low_f": 52.0,
                "precip_in": 0.0,
                "date": "2026-04-15",
            },
        )
        enriched["series_ticker"] = "KXLOWNY"
        enriched["title"] = "NYC Low Temp below 55°F on Apr 15"

        result = analyze_trade(enriched)

        assert result is not None, "below condition should return a result"
        assert "forecast_prob" in result
        assert 0.0 <= result["forecast_prob"] <= 1.0
        assert result["condition"]["type"] == "below"

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch(
        "weather_markets._analyze_precip_trade",
        return_value={
            "forecast_prob": 0.30,
            "market_prob": 0.35,
            "edge": -0.05,
            "signal": "PASS",
            "recommended_side": "NO",
            "condition": {"type": "precip_any"},
            "method": "ensemble",
            "data_quality": 0.7,
        },
    )
    def test_analyze_trade_precip_any_condition(self, mock_precip, mock_obs):
        """analyze_trade routes precip_any markets through _analyze_precip_trade."""
        from weather_markets import analyze_trade

        enriched = _make_enriched(
            ticker="KXRAIN-26APR15",
            city="NYC",
            target_date=date(2026, 4, 15),
            forecast={
                "high_f": 68.0,
                "low_f": 55.0,
                "precip_in": 0.02,
                "date": "2026-04-15",
            },
        )
        enriched["series_ticker"] = "KXRAIN"
        enriched["title"] = "Will there be any measurable rain in NYC on Apr 15?"

        result = analyze_trade(enriched)

        assert result is not None
        assert result["condition"]["type"] == "precip_any"
        assert "forecast_prob" in result

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", return_value=0.70)
    @patch("weather_markets.climatological_prob", return_value=0.65)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch(
        "weather_markets.get_ensemble_temps",
        return_value=[
            70.0,
            71.0,
            72.0,
            73.0,
            68.0,
            69.0,
            71.5,
            70.5,
            72.5,
            67.0,
            70.0,
            71.0,
        ],
    )
    def test_analyze_trade_signal_is_valid(
        self, mock_ens, mock_temp_adj, mock_clim, mock_nws, mock_obs
    ):
        """signal field must be a non-empty string with a recognised prefix (BUY, SELL, PASS, NEUTRAL, STRONG BUY, or WEAK)."""
        from weather_markets import analyze_trade

        enriched = _make_enriched()
        result = analyze_trade(enriched)

        assert result is not None
        assert "signal" in result
        signal = result["signal"]
        assert isinstance(signal, str) and len(signal) > 0, (
            f"signal must be a non-empty string, got {signal!r}"
        )
        signal_upper = signal.upper().strip()
        valid_prefixes = ("BUY", "SELL", "PASS", "NEUTRAL", "STRONG BUY", "WEAK")
        assert any(signal_upper.startswith(p) for p in valid_prefixes), (
            f"Unexpected signal: {signal!r}"
        )
