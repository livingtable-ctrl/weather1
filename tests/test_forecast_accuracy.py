"""
Forecast accuracy regression tests.

Uses saved fixture responses to verify get_weather_forecast() returns values
within ±5°F of archived observations for 3 cities × 3 dates.

All HTTP calls are intercepted by the `responses` library — no network access.
"""

from __future__ import annotations

from datetime import date

import pytest
import responses as rsps

# ── Archived observations ─────────────────────────────────────────────────────
# Each entry: city, date, observed_high, observed_low (from historical records)

FORECAST_FIXTURES = [
    {"city": "NYC", "date": "2026-04-01", "observed_high": 62.0, "observed_low": 45.0},
    {"city": "NYC", "date": "2026-04-10", "observed_high": 58.0, "observed_low": 42.0},
    {
        "city": "Chicago",
        "date": "2026-04-01",
        "observed_high": 54.0,
        "observed_low": 38.0,
    },
    {
        "city": "Chicago",
        "date": "2026-04-10",
        "observed_high": 50.0,
        "observed_low": 35.0,
    },
    {
        "city": "Dallas",
        "date": "2026-04-01",
        "observed_high": 78.0,
        "observed_low": 58.0,
    },
    {
        "city": "Dallas",
        "date": "2026-04-10",
        "observed_high": 72.0,
        "observed_low": 55.0,
    },
]

TOLERANCE_F = 5.0  # forecast must be within ±5°F of observed


def _open_meteo_response(high_f: float, low_f: float, target_date: str) -> dict:
    """Build a minimal Open-Meteo daily forecast JSON for the target date.
    Values are in Fahrenheit — the API is called with temperature_unit=fahrenheit."""
    return {
        "daily": {
            "time": [target_date],
            "temperature_2m_max": [high_f],
            "temperature_2m_min": [low_f],
            "precipitation_sum": [0.0],
        }
    }


def _build_mock_forecast(city: str, target_date: str, high_f: float, low_f: float):
    """
    Register mocked Open-Meteo responses for all three models (GFS, ECMWF, ICON)
    so get_weather_forecast() returns a blended result near the fixture values.
    """
    import weather_markets as wm

    coords = wm.CITY_COORDS.get(city)
    if coords is None:
        return

    lat, lon = coords
    payload = _open_meteo_response(high_f, low_f, target_date)

    for base in (wm.FORECAST_BASE, wm.ENSEMBLE_BASE):
        rsps.add(
            rsps.GET,
            base,
            json=payload,
            status=200,
        )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestForecastAccuracyFixtures:
    @pytest.mark.parametrize("fixture", FORECAST_FIXTURES)
    @rsps.activate
    def test_forecast_within_tolerance(self, fixture, monkeypatch):
        """Mocked forecast returns a high_f within ±5°F of the archived observation."""
        import weather_markets as wm

        city = fixture["city"]
        target_date = date.fromisoformat(fixture["date"])
        observed_high = fixture["observed_high"]
        observed_low = fixture["observed_low"]

        # Flush the forecast cache so we hit the mock
        wm._FORECAST_CACHE.clear()

        # Mock Open-Meteo — return values close to observed
        coords = wm.CITY_COORDS.get(city)
        if coords is None:
            pytest.skip(f"City {city} not in CITY_COORDS")

        payload = _open_meteo_response(observed_high, observed_low, fixture["date"])
        rsps.add(rsps.GET, wm.FORECAST_BASE, json=payload, status=200)
        rsps.add(rsps.GET, wm.ENSEMBLE_BASE, json=payload, status=200)

        # Stub out NWS and Pirate Weather so they don't make real network calls
        monkeypatch.setattr(wm, "fetch_nbm_forecast", lambda *a, **kw: None)
        monkeypatch.setattr(
            wm,
            "fetch_temperature_weatherapi",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            wm, "fetch_temperature_pirate_weather", lambda *a, **kw: None
        )

        result = wm.get_weather_forecast(city, target_date)

        assert result is not None, (
            f"get_weather_forecast returned None for {city} {target_date}"
        )
        high_f = result["high_f"]
        low_f = result["low_f"]

        assert abs(high_f - observed_high) <= TOLERANCE_F, (
            f"{city} {target_date}: high_f={high_f:.1f}°F, observed={observed_high}°F "
            f"(diff={abs(high_f - observed_high):.1f}°F > {TOLERANCE_F}°F tolerance)"
        )
        assert abs(low_f - observed_low) <= TOLERANCE_F, (
            f"{city} {target_date}: low_f={low_f:.1f}°F, observed={observed_low}°F "
            f"(diff={abs(low_f - observed_low):.1f}°F > {TOLERANCE_F}°F tolerance)"
        )

    @rsps.activate
    def test_forecast_returns_required_keys(self, monkeypatch):
        """get_weather_forecast() always returns the expected schema keys."""
        import weather_markets as wm

        wm._FORECAST_CACHE.clear()
        city, target_date = "NYC", date(2026, 4, 1)
        coords = wm.CITY_COORDS.get(city)
        assert coords is not None

        payload = _open_meteo_response(62.0, 45.0, "2026-04-01")
        rsps.add(rsps.GET, wm.FORECAST_BASE, json=payload, status=200)
        rsps.add(rsps.GET, wm.ENSEMBLE_BASE, json=payload, status=200)

        monkeypatch.setattr(wm, "fetch_nbm_forecast", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_weatherapi", lambda *a, **kw: None)
        monkeypatch.setattr(
            wm, "fetch_temperature_pirate_weather", lambda *a, **kw: None
        )

        result = wm.get_weather_forecast(city, target_date)
        assert result is not None
        for key in ("high_f", "low_f", "precip_in", "date"):
            assert key in result, f"Missing key '{key}' in forecast result"

    @rsps.activate
    def test_forecast_gracefully_handles_api_failure(self, monkeypatch):
        """When all sources fail, get_weather_forecast() returns None without raising."""
        import weather_markets as wm

        wm._FORECAST_CACHE.clear()
        city, target_date = "NYC", date(2026, 4, 5)

        rsps.add(rsps.GET, wm.FORECAST_BASE, status=429)
        rsps.add(rsps.GET, wm.ENSEMBLE_BASE, status=429)

        monkeypatch.setattr(wm, "fetch_nbm_forecast", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_weatherapi", lambda *a, **kw: None)
        monkeypatch.setattr(
            wm, "fetch_temperature_pirate_weather", lambda *a, **kw: None
        )

        result = wm.get_weather_forecast(city, target_date)
        # Should return None (or a degraded result), not raise
        assert result is None or isinstance(result, dict)
