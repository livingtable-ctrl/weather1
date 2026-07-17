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
        """fetch_temperature_nbm falls back to Open-Meteo best_match when the
        real-NBM IEM path (tried first, 2026-07-17) has no coverage."""
        from datetime import date

        from weather_markets import fetch_temperature_nbm

        # With mocked HTTP — any well-formed Open-Meteo response should parse
        mock_response = {
            "hourly": {
                "time": ["2026-04-17T15:00", "2026-04-17T18:00"],
                "temperature_2m": [20.5, 19.0],
            }
        }
        with (
            patch("weather_markets._NBM_CACHE", {}),
            patch("mos.fetch_nbm_iem", return_value=None),
            patch("weather_markets._om_request") as mock_req,
        ):
            mock_req.return_value.json.return_value = mock_response
            mock_req.return_value.raise_for_status.return_value = None
            mock_req.return_value.status_code = 200
            result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        # Should return the max daily temp in °F
        assert result == pytest.approx(20.5, abs=0.01)

    def test_fetch_temperature_nbm_returns_none_on_error(self):
        """Returns None gracefully when both the IEM and Open-Meteo paths fail."""
        from datetime import date

        import requests

        from weather_markets import fetch_temperature_nbm

        with (
            patch("weather_markets._NBM_CACHE", {}),
            patch("mos.fetch_nbm_iem", return_value=None),
            patch("weather_markets._om_request") as mock_req,
        ):
            mock_req.side_effect = requests.RequestException("timeout")
            result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        assert result is None

    def test_fetch_temperature_nbm_prefers_real_nbm_over_openmeteo(self):
        """2026-07-17: fetch_temperature_nbm must try the real-NBM IEM path
        first and use it directly, never falling through to the Open-Meteo
        best_match substitute when IEM has real coverage."""
        from datetime import date

        from weather_markets import fetch_temperature_nbm

        with (
            patch("weather_markets._NBM_CACHE", {}),
            patch("mos.fetch_nbm_iem", return_value=77.0) as mock_iem,
            patch("weather_markets._om_request") as mock_om,
        ):
            result = fetch_temperature_nbm("NYC", date(2026, 4, 17), var="max")

        assert result == 77.0
        mock_iem.assert_called_once()
        # Open-Meteo must never be hit once IEM returns a real value.
        mock_om.assert_not_called()

    def test_fetch_temperature_nbm_unknown_station_skips_iem(self):
        """A city with no ASOS station mapping must skip straight to
        Open-Meteo rather than erroring."""
        from datetime import date

        from weather_markets import fetch_temperature_nbm

        mock_response = {
            "hourly": {"time": ["2026-04-17T15:00"], "temperature_2m": [50.0]}
        }
        with (
            patch("weather_markets._NBM_CACHE", {}),
            patch("weather_markets._metar_station_for_city", return_value=None),
            patch("weather_markets._om_request") as mock_req,
        ):
            mock_req.return_value.json.return_value = mock_response
            mock_req.return_value.raise_for_status.return_value = None
            result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        assert result == pytest.approx(50.0, abs=0.01)

    def test_openmeteo_fallback_does_not_clobber_iem_value_for_other_var(self):
        """2026-07-17 (opus review finding): NBS has per-var coverage gaps at
        its ~3-day horizon edge -- a date can have a real IEM max but no IEM
        min yet, or vice versa. When the min lookup falls through to the
        Open-Meteo best_match fallback, that fallback's opportunistic
        dual-var cache write must NOT clobber the max value IEM already
        cached -- doing so would silently reintroduce the exact placeholder
        this feature replaces, order-dependently, with no error raised."""
        from datetime import date

        from weather_markets import fetch_temperature_nbm

        target = date(2026, 4, 17)
        shared_cache: dict = {}
        # Open-Meteo response for the "min" lookup -- deliberately different
        # values from the real IEM max, so a clobber is unmistakable.
        om_response = {
            "hourly": {
                "time": ["2026-04-17T09:00", "2026-04-17T15:00"],
                "temperature_2m": [50.0, 60.0],
            }
        }

        with (
            patch("weather_markets._NBM_CACHE", shared_cache),
            patch("mos.fetch_nbm_iem", return_value=81.0),
            patch("weather_markets._om_request") as mock_om,
        ):
            max_result = fetch_temperature_nbm("NYC", target, var="max")
        assert max_result == 81.0
        mock_om.assert_not_called()

        with (
            patch("weather_markets._NBM_CACHE", shared_cache),
            patch("mos.fetch_nbm_iem", return_value=None),
            patch("weather_markets._om_request") as mock_om,
        ):
            mock_om.return_value.json.return_value = om_response
            mock_om.return_value.raise_for_status.return_value = None
            min_result = fetch_temperature_nbm("NYC", target, var="min")
        # The Open-Meteo fallback's own requested var must still populate.
        assert min_result == pytest.approx(50.0, abs=0.01)

        # The real IEM max, cached by the first call, must survive untouched
        # -- not overwritten by the second call's Open-Meteo best_match max.
        # Both fetch paths are mocked to raise if called at all: a cache hit
        # must answer this without touching either -- if the cache WAS
        # clobbered, this fails loudly instead of silently hitting a real
        # network call.
        def _fail(*_a, **_kw):
            raise AssertionError("must be a cache hit — no fetch expected")

        with (
            patch("weather_markets._NBM_CACHE", shared_cache),
            patch("mos.fetch_nbm_iem", side_effect=_fail),
            patch("weather_markets._om_request", side_effect=_fail),
        ):
            max_after = fetch_temperature_nbm("NYC", target, var="max")
        assert max_after == 81.0


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
