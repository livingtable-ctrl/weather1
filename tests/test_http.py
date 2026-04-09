"""
HTTP integration tests using `responses` to mock Open-Meteo API calls.
These run offline — no real network calls are made.
"""

import unittest
from datetime import date

import responses as resp

from weather_markets import FORECAST_BASE, get_weather_forecast


def _open_meteo_payload(target: str, high: float, low: float, precip: float) -> dict:
    """Minimal Open-Meteo daily response."""
    return {
        "daily": {
            "time": [target],
            "temperature_2m_max": [high],
            "temperature_2m_min": [low],
            "precipitation_sum": [precip],
        }
    }


class TestGetWeatherForecastMocked(unittest.TestCase):
    @resp.activate
    def test_returns_forecast_when_all_models_respond(self):
        """All three models respond — forecast should average their values."""
        target = date(2025, 4, 9)

        # Register the same response for every GET to the forecast URL
        # (all three model calls hit the same base URL with different params)
        for _ in range(3):
            resp.add(
                resp.GET,
                FORECAST_BASE,
                json=_open_meteo_payload(
                    target.isoformat(), high=65.0, low=50.0, precip=0.0
                ),
                status=200,
            )

        result = get_weather_forecast("NYC", target)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result["high_f"], 65.0)
        self.assertAlmostEqual(result["low_f"], 50.0)
        self.assertEqual(result["models_used"], 3)

    @resp.activate
    def test_returns_none_when_target_date_missing(self):
        """If the API doesn't include our target date, return None."""
        target = date(2025, 4, 9)

        for _ in range(3):
            resp.add(
                resp.GET,
                FORECAST_BASE,
                json=_open_meteo_payload("2025-04-10", high=65.0, low=50.0, precip=0.0),
                status=200,
            )

        result = get_weather_forecast("NYC", target)
        self.assertIsNone(result)

    @resp.activate
    def test_partial_model_failure_still_returns(self):
        """If one model returns data for the wrong date, we still get a result from the others."""
        target = date(2025, 4, 9)

        # Model 1: responds but for the wrong date — should be skipped
        resp.add(
            resp.GET,
            FORECAST_BASE,
            json=_open_meteo_payload("2025-04-10", high=65.0, low=49.0, precip=0.0),
            status=200,
        )
        # Models 2 & 3: have the correct date
        resp.add(
            resp.GET,
            FORECAST_BASE,
            json=_open_meteo_payload(
                target.isoformat(), high=68.0, low=52.0, precip=0.1
            ),
            status=200,
        )
        resp.add(
            resp.GET,
            FORECAST_BASE,
            json=_open_meteo_payload(
                target.isoformat(), high=70.0, low=54.0, precip=0.0
            ),
            status=200,
        )

        result = get_weather_forecast("NYC", target)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["models_used"], 2)
        self.assertAlmostEqual(result["high_f"], 69.0)  # (68 + 70) / 2

    @resp.activate
    def test_all_models_fail_returns_none(self):
        """If every model call fails, return None."""
        for _ in range(3):
            resp.add(resp.GET, FORECAST_BASE, status=503)

        result = get_weather_forecast("NYC", date(2025, 4, 9))
        self.assertIsNone(result)

    def test_unknown_city_returns_none(self):
        """Unknown city should return None without making any HTTP calls."""
        result = get_weather_forecast("Atlantis", date(2025, 4, 9))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
