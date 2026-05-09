"""Tests for P0.2 — EDGE_CALC_VERSION constant and analyze_trade stamp."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

import weather_markets as wm
from weather_markets import EDGE_CALC_VERSION, analyze_trade


def _enriched(city="NYC"):
    """Minimal enriched dict that produces a non-None analyze_trade result."""
    target = date.today() + timedelta(days=1)
    return {
        "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
        "title": "NYC high > 70°F",
        "_city": city,
        "_date": target,
        "_hour": None,
        "_forecast": {
            "high_f": 80.0,
            "low_f": 62.0,
            "precip_in": 0.0,
            "date": target.isoformat(),
            "city": city,
            "models_used": 3,
            "high_range": (78.0, 82.0),
        },
        "yes_bid": 0.45,
        "yes_ask": 0.55,
        "no_bid": 0.45,
        "close_time": "",
        "series_ticker": "KXHIGHNY",
        "volume": 500,
        "open_interest": 200,
    }


def test_edge_calc_version_is_string():
    """EDGE_CALC_VERSION must be a non-empty string constant."""
    assert isinstance(EDGE_CALC_VERSION, str)
    assert len(EDGE_CALC_VERSION) > 0


def test_analyze_trade_returns_edge_version():
    """Every non-None analyze_trade result must carry an edge_calc_version key."""
    with (
        patch.object(
            wm,
            "get_ensemble_temps",
            return_value=[
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
            ],
        ),
        patch("climatology.climatological_prob", return_value=0.6),
        patch("nws.nws_prob", return_value=None),
        patch("nws.get_live_observation", return_value=None),
        patch("climate_indices.temperature_adjustment", return_value=0.0),
    ):
        result = analyze_trade(_enriched())

    assert result is not None, "Expected a trade signal for this input"
    assert "edge_calc_version" in result, "analyze_trade must stamp edge_calc_version"
    assert result["edge_calc_version"] == EDGE_CALC_VERSION


def test_precip_fast_path_stamps_edge_version():
    """Precipitation fast-path returns must also carry edge_calc_version."""
    target = date.today() + timedelta(days=1)
    enriched = {
        "ticker": f"KXPRECIPNY-{target.strftime('%d%b%y').upper()}",
        "title": "NYC precip > 0.1in",
        "_city": "NYC",
        "_date": target,
        "_hour": None,
        "_forecast": {
            "high_f": 70.0,
            "low_f": 55.0,
            "precip_in": 0.5,
            "date": target.isoformat(),
            "city": "NYC",
            "models_used": 3,
            "high_range": (68.0, 72.0),
        },
        "yes_bid": 0.40,
        "yes_ask": 0.50,
        "no_bid": 0.50,
        "close_time": "",
        "series_ticker": "KXPRECIPNY",
        "volume": 500,
        "open_interest": 200,
    }
    with (
        patch.object(
            wm,
            "get_ensemble_temps",
            return_value=[
                68.0,
                69.0,
                70.0,
                71.0,
                72.0,
                68.0,
                69.0,
                70.0,
                71.0,
                72.0,
                68.0,
                69.0,
                70.0,
                71.0,
                72.0,
                68.0,
                69.0,
                70.0,
                71.0,
                72.0,
            ],
        ),
        patch("climatology.climatological_prob", return_value=0.5),
        patch("nws.nws_prob", return_value=None),
        patch("nws.get_live_observation", return_value=None),
        patch("climate_indices.temperature_adjustment", return_value=0.0),
    ):
        result = analyze_trade(enriched)

    if result is None:
        pytest.skip("No precip trade signal for this input")
    assert "edge_calc_version" in result, (
        "Precip fast-path must stamp edge_calc_version"
    )
    assert result["edge_calc_version"] == EDGE_CALC_VERSION
