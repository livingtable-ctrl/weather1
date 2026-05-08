"""Tests for ECMWF AIFS ensemble data source."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestECMWFAIFS:
    def test_fetch_temperature_ecmwf_returns_float_or_none(self):
        """fetch_temperature_ecmwf returns a float or None."""
        from datetime import date

        from weather_markets import fetch_temperature_ecmwf

        mock_response = {
            "hourly": {
                "time": ["2026-04-17T12:00", "2026-04-17T18:00"],
                "temperature_2m": [18.5, 21.0],
            }
        }
        with patch("weather_markets._ECMWF_CACHE", {}):
            with patch("weather_markets._om_request") as mock_req:
                mock_req.return_value.json.return_value = mock_response
                mock_req.return_value.raise_for_status.return_value = None
                mock_req.return_value.status_code = 200
                result = fetch_temperature_ecmwf("NYC", date(2026, 4, 17))

        assert result == pytest.approx(21.0, abs=0.01)

    def test_fetch_temperature_ecmwf_none_on_failure(self):
        from datetime import date

        import requests

        import weather_markets

        with patch("weather_markets._ECMWF_CACHE", {}):
            with patch("weather_markets._om_request") as mock_req:
                mock_req.side_effect = requests.RequestException("timeout")
                assert (
                    weather_markets.fetch_temperature_ecmwf("NYC", date(2026, 4, 17))
                    is None
                )

    def test_ecmwf_in_extended_ensemble(self):
        """ENSEMBLE_MODELS_EXTENDED includes an ecmwf entry."""
        from weather_markets import ENSEMBLE_MODELS_EXTENDED

        assert any("ecmwf" in m for m in ENSEMBLE_MODELS_EXTENDED)

    def test_ecmwf_spread_computation(self):
        """ensemble_spread computed when ECMWF included raises no error."""
        from weather_markets import _compute_ensemble_spread

        temps = {
            "gfs_seamless": 70.0,
            "icon_seamless": 68.0,
            "ecmwf": 71.0,
            "nbm": 69.0,
        }
        spread = _compute_ensemble_spread(temps)
        assert isinstance(spread, float)
        assert spread >= 0

    def test_spread_single_valid_member_returns_zero(self):
        """_compute_ensemble_spread returns 0.0 when only one member is valid."""
        from weather_markets import _compute_ensemble_spread

        spread = _compute_ensemble_spread({"nbm": 70.0, "ecmwf": None})
        assert spread == 0.0
