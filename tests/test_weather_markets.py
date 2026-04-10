"""Unit tests for key functions in weather_markets.py and utils.py."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so imports work when run from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import normal_cdf
from weather_markets import (
    _feels_like,
    _forecast_model_weights,
    is_liquid,
    parse_market_price,
)

# ── TestFeelsLike ─────────────────────────────────────────────────────────────


class TestFeelsLike:
    def test_hot_humid_returns_higher_than_actual(self):
        """Heat index should raise apparent temperature above actual."""
        # 95°F, high humidity → heat index exceeds 95°F
        result = _feels_like(temp_f=95.0, wind_mph=5.0, humidity_pct=80.0)
        assert result > 95.0

    def test_cold_windy_returns_lower_than_actual(self):
        """Wind chill should lower apparent temperature below actual."""
        # 30°F, 20 mph wind → feels colder than 30°F
        result = _feels_like(temp_f=30.0, wind_mph=20.0, humidity_pct=50.0)
        assert result < 30.0

    def test_moderate_conditions_returns_near_actual(self):
        """Moderate temp/wind/humidity falls through to actual temperature."""
        # 65°F is above 50 (no wind chill) and below 80 (no heat index)
        result = _feels_like(temp_f=65.0, wind_mph=10.0, humidity_pct=50.0)
        assert result == pytest.approx(65.0)

    def test_boundary_wind_chill_threshold(self):
        """Wind chill only applies when temp <= 50 and wind >= 3 mph."""
        # Exactly at boundary: 50°F, 3 mph
        result = _feels_like(temp_f=50.0, wind_mph=3.0, humidity_pct=40.0)
        assert result < 50.0  # wind chill kicks in at exactly <=50 and >=3

    def test_default_params_used(self):
        """Function uses sane defaults (wind_mph=10, humidity_pct=50)."""
        # 65°F with defaults: no wind chill, no heat index
        result = _feels_like(65.0)
        assert result == pytest.approx(65.0)


# ── TestParseMarketPrice ──────────────────────────────────────────────────────


class TestParseMarketPrice:
    def test_returns_dict_with_expected_keys(self):
        """Result must be a dict containing the standard price keys."""
        market = {"yes_bid": 55, "yes_ask": 60, "no_bid": 40}
        result = parse_market_price(market)
        assert isinstance(result, dict)
        for key in ("yes_bid", "yes_ask", "no_bid", "mid", "implied_prob"):
            assert key in result, f"Missing key: {key}"

    def test_cents_converted_to_decimal(self):
        """Integer values > 1 are treated as cents and divided by 100."""
        market = {"yes_bid": 55, "yes_ask": 65, "no_bid": 35}
        result = parse_market_price(market)
        assert result["yes_bid"] == pytest.approx(0.55)
        assert result["yes_ask"] == pytest.approx(0.65)
        assert result["no_bid"] == pytest.approx(0.35)

    def test_implied_prob_is_midpoint(self):
        """implied_prob equals the mid-price of yes_bid and yes_ask."""
        market = {"yes_bid": 40, "yes_ask": 60, "no_bid": 40}
        result = parse_market_price(market)
        # mid = (0.40 + 0.60) / 2 = 0.50
        assert result["implied_prob"] == pytest.approx(0.50)
        assert result["mid"] == pytest.approx(0.50)

    def test_string_prices_parsed(self):
        """String-format prices (e.g. '0.55') are parsed correctly."""
        market = {"yes_bid": "0.55", "yes_ask": "0.65", "no_bid": "0.35"}
        result = parse_market_price(market)
        assert result["yes_bid"] == pytest.approx(0.55)
        assert result["yes_ask"] == pytest.approx(0.65)

    def test_missing_fields_fall_back_to_zero(self):
        """Missing price fields default to 0.0 without raising."""
        result = parse_market_price({})
        assert result["yes_bid"] == pytest.approx(0.0)
        assert result["yes_ask"] == pytest.approx(0.0)
        assert result["no_bid"] == pytest.approx(0.0)
        assert result["implied_prob"] == pytest.approx(0.0)

    def test_mid_falls_back_to_yes_bid_when_no_ask(self):
        """When yes_ask is 0 the mid falls back to yes_bid."""
        market = {"yes_bid": 40, "yes_ask": 0, "no_bid": 0}
        result = parse_market_price(market)
        assert result["mid"] == pytest.approx(0.40)


# ── TestIsLiquid ──────────────────────────────────────────────────────────────


class TestIsLiquid:
    def test_liquid_market_with_quotes_and_volume(self):
        """A market with both-sided quotes and volume is liquid."""
        market = {"yes_bid": 55, "yes_ask": 60, "no_bid": 40, "volume": 5000}
        assert is_liquid(market) is True

    def test_liquid_market_with_yes_bid_only(self):
        """Market with only a yes_bid > 0 qualifies as liquid."""
        market = {"yes_bid": 30, "yes_ask": 0, "no_bid": 0, "volume": 0}
        assert is_liquid(market) is True

    def test_liquid_market_with_volume_only(self):
        """Market with no quotes but nonzero volume counts as liquid."""
        market = {"yes_bid": 0, "yes_ask": 0, "no_bid": 0, "volume": 100}
        assert is_liquid(market) is True

    def test_liquid_market_with_no_bid_only(self):
        """Market with only a no_bid > 0 qualifies as liquid."""
        market = {"yes_bid": 0, "yes_ask": 0, "no_bid": 40, "volume": 0}
        assert is_liquid(market) is True

    def test_illiquid_market_all_zeros(self):
        """Market with no quotes and zero volume is not liquid."""
        market = {"yes_bid": 0, "yes_ask": 0, "no_bid": 0, "volume": 0}
        assert is_liquid(market) is False

    def test_illiquid_market_empty_dict(self):
        """Empty market dict has no liquidity."""
        assert is_liquid({}) is False


# ── TestForecastModelWeights ──────────────────────────────────────────────────


class TestForecastModelWeights:
    WINTER_MONTHS = (10, 11, 12, 1, 2, 3)
    SUMMER_MONTHS = (4, 5, 6, 7, 8, 9)

    def test_returns_dict_with_expected_keys(self):
        weights = _forecast_model_weights(1)
        assert isinstance(weights, dict)
        for key in ("gfs_seamless", "ecmwf_ifs04", "icon_seamless"):
            assert key in weights

    def test_winter_month_boosts_ecmwf_weight(self):
        """ECMWF weight should be higher in winter than summer."""
        winter_w = _forecast_model_weights(1)["ecmwf_ifs04"]
        summer_w = _forecast_model_weights(7)["ecmwf_ifs04"]
        assert winter_w > summer_w

    def test_all_winter_months_use_high_ecmwf(self):
        """All winter months (Oct-Mar) should use the elevated ECMWF weight."""
        for month in self.WINTER_MONTHS:
            w = _forecast_model_weights(month)
            assert w["ecmwf_ifs04"] == pytest.approx(2.5), (
                f"Expected 2.5 for winter month {month}, got {w['ecmwf_ifs04']}"
            )

    def test_all_summer_months_use_lower_ecmwf(self):
        """All summer months (Apr-Sep) should use the lower ECMWF weight."""
        for month in self.SUMMER_MONTHS:
            w = _forecast_model_weights(month)
            assert w["ecmwf_ifs04"] == pytest.approx(1.5), (
                f"Expected 1.5 for summer month {month}, got {w['ecmwf_ifs04']}"
            )

    def test_gfs_and_icon_weights_are_constant(self):
        """GFS and ICON weights should be 1.0 year-round."""
        for month in range(1, 13):
            w = _forecast_model_weights(month)
            assert w["gfs_seamless"] == pytest.approx(1.0)
            assert w["icon_seamless"] == pytest.approx(1.0)


# ── TestNormalCdf ─────────────────────────────────────────────────────────────


class TestNormalCdf:
    def test_mean_returns_half(self):
        """CDF at the mean of a standard normal is 0.5."""
        assert normal_cdf(0.0, 0.0, 1.0) == pytest.approx(0.5, abs=1e-6)

    def test_one_sigma_above_mean(self):
        """CDF at +1 sigma ≈ 0.8413."""
        assert normal_cdf(1.0, 0.0, 1.0) == pytest.approx(0.8413, abs=1e-4)

    def test_symmetry(self):
        """CDF(-x, 0, 1) == 1 - CDF(x, 0, 1) for all x."""
        for x in (0.5, 1.0, 2.0, 3.0):
            assert normal_cdf(-x, 0.0, 1.0) == pytest.approx(
                1.0 - normal_cdf(x, 0.0, 1.0), abs=1e-10
            )

    def test_shifted_mean(self):
        """CDF at mu with non-zero mu returns 0.5."""
        assert normal_cdf(5.0, 5.0, 2.0) == pytest.approx(0.5, abs=1e-6)

    def test_two_sigma_above_mean(self):
        """CDF at +2 sigma ≈ 0.9772."""
        assert normal_cdf(2.0, 0.0, 1.0) == pytest.approx(0.9772, abs=1e-4)

    def test_zero_sigma_returns_step(self):
        """Degenerate sigma=0: returns 1.0 when x >= mu, 0.0 otherwise."""
        assert normal_cdf(5.0, 5.0, 0.0) == pytest.approx(1.0)
        assert normal_cdf(4.9, 5.0, 0.0) == pytest.approx(0.0)
