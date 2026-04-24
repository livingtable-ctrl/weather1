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
