"""Tests for P0.3 — FORECAST_MAX_AGE_SECS and stale data rejection in analyze_trade."""

import time
from datetime import date, timedelta
from unittest.mock import patch

import weather_markets as wm
from weather_markets import FORECAST_MAX_AGE_SECS, analyze_trade


def _enriched(fetched_at: float | None = None, city: str = "NYC") -> dict:
    """Enriched dict with correct keys; fetched_at controls freshness."""
    target = date.today() + timedelta(days=1)
    enriched = {
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
    if fetched_at is not None:
        enriched["data_fetched_at"] = fetched_at
    return enriched


def _mock_externals():
    """Context manager stack that patches all network calls inside analyze_trade."""
    return (
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
    )


def test_forecast_max_age_secs_is_positive_int():
    """FORECAST_MAX_AGE_SECS must be a positive integer."""
    assert isinstance(FORECAST_MAX_AGE_SECS, int)
    assert FORECAST_MAX_AGE_SECS > 0


def test_analyze_trade_rejects_stale_data():
    """analyze_trade must return None when data_fetched_at is beyond FORECAST_MAX_AGE_SECS."""
    stale_ts = time.time() - (FORECAST_MAX_AGE_SECS + 60)
    enriched = _enriched(fetched_at=stale_ts)

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
        result = analyze_trade(enriched)

    assert result is None, "analyze_trade must reject stale enriched data"


def test_analyze_trade_accepts_fresh_data():
    """analyze_trade must not reject data when data_fetched_at is recent."""
    fresh_ts = time.time()  # just now
    enriched = _enriched(fetched_at=fresh_ts)

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
        result = analyze_trade(enriched)

    # With this enriched input a trade signal should be produced
    assert result is not None, "analyze_trade must not reject fresh data"


def test_analyze_trade_no_fetched_at_is_treated_as_fresh():
    """If data_fetched_at is absent, analyze_trade must not reject the data."""
    enriched = _enriched(fetched_at=None)  # no timestamp

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
        result = analyze_trade(enriched)

    # Should not reject — absence of timestamp means caller doesn't track age
    assert result is not None, "Missing data_fetched_at must not cause rejection"


def test_enrich_with_forecast_stamps_data_fetched_at():
    """enrich_with_forecast must add data_fetched_at to the returned dict."""
    market = {"ticker": "KXHIGHNY-26APR15-T70", "title": "NYC high > 70°F"}
    before = time.time()
    with patch.object(wm, "get_weather_forecast", return_value=None):
        enriched = wm.enrich_with_forecast(market)
    after = time.time()

    assert "data_fetched_at" in enriched, (
        "enrich_with_forecast must stamp data_fetched_at"
    )
    assert before <= enriched["data_fetched_at"] <= after
