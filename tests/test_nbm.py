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
            with patch("weather_markets._om_request") as mock_req:
                mock_req.return_value.json.return_value = mock_response
                mock_req.return_value.raise_for_status.return_value = None
                mock_req.return_value.status_code = 200
                result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        # Should return the max daily temp in °F
        assert result == pytest.approx(20.5, abs=0.01)

    def test_fetch_temperature_nbm_returns_none_on_error(self):
        """Returns None gracefully on API failure."""
        from datetime import date

        import requests

        from weather_markets import fetch_temperature_nbm

        with patch("weather_markets._NBM_CACHE", {}):
            with patch("weather_markets._om_request") as mock_req:
                mock_req.side_effect = requests.RequestException("timeout")
                result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        assert result is None


class TestNBMQuantiles:
    def test_nws_prob_uses_quantiles_above(self):
        """nws_prob_from_quantiles uses ECDF interpolation for above condition."""
        from nws import nws_prob_from_quantiles

        # NBM quantiles: [T10=62, T25=65, T50=68, T75=71, T90=74]
        quantiles = {10: 62.0, 25: 65.0, 50: 68.0, 75: 71.0, 90: 74.0}

        # P(T > 70) should be between 0.15 and 0.40 (threshold is between T50=68 and T75=71)
        prob = nws_prob_from_quantiles(
            quantiles, threshold=70.0, condition_type="above"
        )
        assert 0.15 <= prob <= 0.40

    def test_nws_prob_at_median_is_near_half(self):
        """P(T > median) should be ~0.50 by definition."""
        from nws import nws_prob_from_quantiles

        quantiles = {10: 62.0, 25: 65.0, 50: 68.0, 75: 71.0, 90: 74.0}
        prob_at_median = nws_prob_from_quantiles(
            quantiles, threshold=68.0, condition_type="above"
        )
        assert 0.45 <= prob_at_median <= 0.55

    def test_nws_prob_below_is_complement_of_above(self):
        """P(T < threshold) + P(T > threshold) should approximately equal 1."""
        from nws import nws_prob_from_quantiles

        quantiles = {10: 62.0, 25: 65.0, 50: 68.0, 75: 71.0, 90: 74.0}
        p_above = nws_prob_from_quantiles(
            quantiles, threshold=68.0, condition_type="above"
        )
        p_below = nws_prob_from_quantiles(
            quantiles, threshold=68.0, condition_type="below"
        )
        # At an exact quantile point, above + below should sum near 1.0
        assert abs(p_above + p_below - 1.0) < 0.01

    def test_nws_prob_empty_quantiles_returns_half(self):
        """Empty quantile dict should return 0.5 as a safe fallback."""
        from nws import nws_prob_from_quantiles

        prob = nws_prob_from_quantiles({}, threshold=70.0, condition_type="above")
        assert prob == 0.5
