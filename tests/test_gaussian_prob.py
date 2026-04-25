"""Tests for Gaussian probability distribution method."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGaussianProbability:
    def test_50pct_at_mean(self):
        """P(T > threshold) = 50% when threshold equals the forecast mean."""
        from weather_markets import gaussian_probability

        prob = gaussian_probability(
            forecast_mean=70.0,
            threshold=70.0,
            sigma=5.0,
            direction="above",
        )
        assert prob == pytest.approx(0.50, abs=0.01)

    def test_high_prob_when_mean_well_above_threshold(self):
        """P(T > 65) ≈ 84% when mean=70, sigma=5 (1 sigma above)."""
        from weather_markets import gaussian_probability

        prob = gaussian_probability(
            forecast_mean=70.0,
            threshold=65.0,
            sigma=5.0,
            direction="above",
        )
        # ~84% → CDF at z=1
        assert prob == pytest.approx(0.841, abs=0.01)

    def test_below_direction(self):
        """P(T < threshold) is complement of above."""
        from weather_markets import gaussian_probability

        above = gaussian_probability(70.0, 65.0, 5.0, "above")
        below = gaussian_probability(70.0, 65.0, 5.0, "below")
        assert above + below == pytest.approx(1.0, abs=0.001)

    def test_wider_sigma_flattens_probability(self):
        """Higher sigma → probability closer to 0.5."""
        from weather_markets import gaussian_probability

        tight = gaussian_probability(72.0, 65.0, 3.0, "above")
        wide = gaussian_probability(72.0, 65.0, 10.0, "above")
        assert tight > wide
        assert wide > 0.5  # still above 0.5 since mean > threshold

    def test_get_historical_sigma_returns_float(self):
        """get_historical_sigma returns a positive float in the NWS RMSE range (2-5°F)."""
        from weather_markets import get_historical_sigma

        # L8-C: NYC spring (April = season 2) now returns calibrated RMSE, not clim std
        sigma = get_historical_sigma("NYC", month=4)
        assert 2.0 <= sigma <= 5.0, f"NYC spring sigma {sigma} outside NWS RMSE range"
        assert sigma == pytest.approx(3.5)  # calibrated Day-3 RMSE

    def test_get_historical_sigma_unknown_city_default(self):
        """Unknown city returns the default sigma in the NWS RMSE range."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("XYZ", month=6)
        assert 2.0 <= sigma <= 5.0, f"Default sigma {sigma} outside NWS RMSE range"

    # ── L8-C regression: city-name key mismatch ──────────────────────────────

    def test_chicago_returns_calibrated_not_default(self):
        """Chicago must return its calibrated sigma, not the 3.5°F default.

        L8-C bug: _HISTORICAL_SIGMA was keyed 'CHI' but enrich_with_forecast
        stores 'Chicago', so Chicago always silently fell through to default.
        """
        from weather_markets import _DEFAULT_SIGMA, get_historical_sigma

        sigma = get_historical_sigma("Chicago", month=1)  # Winter
        assert sigma != _DEFAULT_SIGMA, (
            "Chicago returned default sigma — city-name key mismatch not fixed"
        )
        assert sigma == pytest.approx(4.0)  # higher than default (continental winter)

    def test_la_returns_calibrated_not_default(self):
        """LA must return its calibrated sigma (was keyed 'LAX', city is 'LA')."""
        from weather_markets import _DEFAULT_SIGMA, get_historical_sigma

        sigma = get_historical_sigma("LA", month=7)  # Summer
        assert sigma != _DEFAULT_SIGMA, (
            "LA returned default sigma — city-name key mismatch not fixed"
        )
        assert sigma == pytest.approx(2.5)  # marine layer, low variability

    def test_miami_returns_calibrated_not_default(self):
        """Miami must return its calibrated sigma (was keyed 'MIA', city is 'Miami')."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("Miami", month=8)  # Summer
        assert sigma == pytest.approx(2.0)  # tropical, very stable

    def test_dallas_returns_calibrated_not_default(self):
        """Dallas must return its calibrated sigma (was keyed 'DAL', city is 'Dallas')."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("Dallas", month=3)  # Spring
        assert sigma == pytest.approx(3.5)

    def test_denver_returns_calibrated_not_default(self):
        """Denver must return its calibrated sigma (was keyed 'DEN', city is 'Denver')."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("Denver", month=1)  # Winter — most volatile
        assert sigma == pytest.approx(4.5)

    def test_all_calibrated_sigmas_in_rmse_range(self):
        """Every calibrated sigma must be in the NWS Day-3 RMSE range (1.5–5°F)."""
        from weather_markets import _HISTORICAL_SIGMA

        for city, seasons in _HISTORICAL_SIGMA.items():
            for season, val in seasons.items():
                assert 1.5 <= val <= 5.0, (
                    f"{city} season {season}: sigma={val} outside NWS RMSE range 1.5-5°F"
                )

    def test_probability_clamped_to_unit_interval(self):
        """gaussian_probability always returns a value in [0, 1]."""
        from weather_markets import gaussian_probability

        extreme_above = gaussian_probability(100.0, 65.0, 5.0, "above")
        extreme_below = gaussian_probability(30.0, 65.0, 5.0, "above")
        assert 0.0 <= extreme_above <= 1.0
        assert 0.0 <= extreme_below <= 1.0


# ── L6-B regression: Gaussian blend must be a separate named source ──────────


class TestGaussianBlendSeparateSource:
    """Regression tests for L6-B: Gaussian contribution must appear in
    blend_sources as its own key ('gaussian') rather than being silently
    embedded inside 'ensemble' by overwriting ens_prob in-place."""

    _ENRICHED_TEMPLATE = {
        "title": "NYC high > 70°F",
        "_city": "NYC",
        "_hour": None,
        "_forecast": {
            "high_f": 72.0,
            "low_f": 60.0,
            "precip_in": 0.0,
            "city": "NYC",
            "models_used": 3,
            "high_range": (70.0, 74.0),
        },
        "yes_bid": 0.45,
        "yes_ask": 0.55,
        "no_bid": 0.45,
        "close_time": "",
        "series_ticker": "KXHIGHNY",
        "volume": 500,
        "open_interest": 200,
    }

    def _make_enriched(self):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=2)
        e = dict(self._ENRICHED_TEMPLATE)
        e["_date"] = target
        e["_forecast"] = dict(self._ENRICHED_TEMPLATE["_forecast"])
        e["_forecast"]["date"] = target.isoformat()
        e["ticker"] = f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70"
        return e

    def test_blend_sources_reports_gaussian_separately(self):
        """Regression for L6-B: blend_sources must contain 'gaussian' as its
        own key when model_temps (NBM/ECMWF) are available and condition is
        'above'/'below'.  Previously the Gaussian contribution was baked into
        ens_prob in-place, so blend_sources would only show 'ensemble'.
        """
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_enriched()

        with (
            patch.object(
                wm, "get_ensemble_temps", return_value=[75.0] * 14 + [65.0] * 6
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=73.0),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=74.0),
            patch("climatology.climatological_prob", return_value=0.55),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        assert "gaussian" in blend, (
            f"blend_sources must include 'gaussian' as a separate source; got {blend}"
        )
        assert blend["gaussian"] > 0.0, (
            f"blend_sources['gaussian'] must be positive; got {blend['gaussian']}"
        )

    def test_ensemble_prob_is_raw_member_fraction(self):
        """Regression for L6-B: result['ensemble_prob'] must be the raw
        member-count fraction, not the Gaussian-blended value.

        With 14/20 ensemble members above threshold 70, ensemble_prob must
        equal exactly 0.70.  Before the fix, the in-place overwrite produced
        ~0.735 (blended with Gaussian).
        """
        from unittest.mock import patch

        import pytest

        import weather_markets as wm

        enriched = self._make_enriched()
        # Exactly 14 of 20 members above threshold 70 → raw fraction = 0.70
        ensemble_temps = [75.0] * 14 + [65.0] * 6

        with (
            patch.object(wm, "get_ensemble_temps", return_value=ensemble_temps),
            patch.object(wm, "fetch_temperature_nbm", return_value=73.0),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=74.0),
            patch("climatology.climatological_prob", return_value=0.55),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        raw_frac = 14 / 20  # 0.70
        assert result["ensemble_prob"] == pytest.approx(raw_frac), (
            f"ensemble_prob={result['ensemble_prob']:.4f} should be the raw member "
            f"fraction {raw_frac:.4f}, not the Gaussian-blended value"
        )
