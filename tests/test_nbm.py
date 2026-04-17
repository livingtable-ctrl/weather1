"""Tests for NBM data source integration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNBMFetch:
    def test_nbm_in_ensemble_models(self):
        """ENSEMBLE_MODELS_EXTENDED includes NBM."""
        from weather_markets import ENSEMBLE_MODELS_EXTENDED

        assert "nbm" in ENSEMBLE_MODELS_EXTENDED or any(
            "nbm" in m for m in ENSEMBLE_MODELS_EXTENDED
        )

    def test_fetch_temperature_nbm_returns_float_or_none(self):
        """fetch_temperature_nbm returns a float for a known city or None on failure."""
        from datetime import date

        from weather_markets import fetch_temperature_nbm

        # With mocked HTTP — any well-formed Open-Meteo response should parse
        mock_response = {
            "hourly": {
                "time": ["2026-04-17T15:00", "2026-04-17T18:00"],
                "temperature_2m": [20.5, 19.0],
            }
        }
        with patch("weather_markets._NBM_CACHE", {}):
            with patch("weather_markets._request_with_retry") as mock_req:
                mock_req.return_value.json.return_value = mock_response
                mock_req.return_value.raise_for_status.return_value = None
                result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        # Should return the max daily temp in °F
        assert result == pytest.approx(20.5, abs=0.01)

    def test_fetch_temperature_nbm_returns_none_on_error(self):
        """Returns None gracefully on API failure."""
        from datetime import date

        import requests

        from weather_markets import fetch_temperature_nbm

        with patch("weather_markets._NBM_CACHE", {}):
            with patch("weather_markets._request_with_retry") as mock_req:
                mock_req.side_effect = requests.RequestException("timeout")
                result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        assert result is None

    def test_nbm_included_in_ensemble_average(self):
        """When NBM returns a value, it is included in the ensemble average."""
        from weather_markets import _compute_ensemble_mean

        temps = {"gfs_seamless": 70.0, "icon_seamless": 72.0, "nbm": 71.0}
        mean = _compute_ensemble_mean(temps)
        assert mean == pytest.approx((70.0 + 72.0 + 71.0) / 3, abs=0.1)

    def test_nbm_excluded_on_none(self):
        """None values from NBM are excluded from ensemble average."""
        from weather_markets import _compute_ensemble_mean

        temps = {"gfs_seamless": 70.0, "icon_seamless": 72.0, "nbm": None}
        mean = _compute_ensemble_mean(temps)
        assert mean == pytest.approx((70.0 + 72.0) / 2, abs=0.1)
