"""Unit tests for key functions in weather_markets.py and utils.py."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so imports work when run from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import normal_cdf
from weather_markets import (
    _bootstrap_ci,
    _feels_like,
    _forecast_model_weights,
    ensemble_stats,
    is_liquid,
    kelly_fraction,
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


# ── Task 4: Inverse-variance ensemble confidence weighting (#31) ──────────────


def test_ensemble_confidence_scale_high_std_reduces_ens_weight():
    from weather_markets import _confidence_scaled_blend_weights

    w_ens_tight, w_clim_tight, w_nws_tight = _confidence_scaled_blend_weights(
        days_out=3, has_nws=True, has_clim=True, ens_std=2.0
    )
    w_ens_wide, w_clim_wide, w_nws_wide = _confidence_scaled_blend_weights(
        days_out=3, has_nws=True, has_clim=True, ens_std=12.0
    )
    assert w_ens_wide < w_ens_tight
    assert abs(w_ens_wide + w_clim_wide + w_nws_wide - 1.0) < 1e-6


def test_ensemble_confidence_scale_no_std_unchanged():
    import pytest

    from weather_markets import _blend_weights, _confidence_scaled_blend_weights

    w1 = _blend_weights(5, has_nws=True, has_clim=True)
    w2 = _confidence_scaled_blend_weights(5, has_nws=True, has_clim=True, ens_std=None)
    assert w1 == pytest.approx(w2, abs=1e-6)


def test_ensemble_confidence_scale_clamped():
    from weather_markets import _blend_weights, _confidence_scaled_blend_weights

    base_ens, _, _ = _blend_weights(3, has_nws=True, has_clim=True)
    scaled_ens, _, _ = _confidence_scaled_blend_weights(
        3, has_nws=True, has_clim=True, ens_std=0.01
    )
    assert scaled_ens <= 1.0


# ── Task 5: Wet-bulb snow-to-liquid ratio (#34) ───────────────────────────────


def test_wet_bulb_temp_approximation():
    from weather_markets import wet_bulb_temp

    wb = wet_bulb_temp(temp_f=32.0, rh_pct=100.0)
    assert 30.0 <= wb <= 34.0
    wb2 = wet_bulb_temp(temp_f=50.0, rh_pct=50.0)
    assert wb2 < 50.0
    assert wb2 > 30.0


def test_snow_to_liquid_ratio_dry_cold():
    from weather_markets import snow_liquid_ratio

    assert snow_liquid_ratio(wet_bulb_f=25.0) == 20


def test_snow_to_liquid_ratio_borderline():
    from weather_markets import snow_liquid_ratio

    assert snow_liquid_ratio(wet_bulb_f=31.0) == 10


def test_snow_to_liquid_ratio_above_freezing():
    from weather_markets import snow_liquid_ratio

    assert snow_liquid_ratio(wet_bulb_f=33.0) == 0


def test_snow_prob_uses_slr_not_1_to_10():
    import pytest

    from weather_markets import liquid_equiv_of_snow_threshold

    liq_20 = liquid_equiv_of_snow_threshold(snow_inches=1.0, slr=20)
    liq_10 = liquid_equiv_of_snow_threshold(snow_inches=1.0, slr=10)
    assert liq_20 == pytest.approx(0.05)
    assert liq_10 == pytest.approx(0.10)


# ── TestKellyCap ──────────────────────────────────────────────────────────────


class TestKellyCap:
    """Verify kelly_fraction hard cap is 33% (raised from 25%)."""

    def test_kelly_fraction_caps_at_33_pct(self):
        """Very high edge → fraction is capped at 0.33, not 0.25."""
        # our_prob=0.95, price=0.10: full Kelly would be enormous
        result = kelly_fraction(our_prob=0.95, price=0.10, fee_rate=0.02)
        assert result == pytest.approx(0.33, abs=1e-6), (
            f"Expected Kelly cap 0.33, got {result}"
        )


# ── TestEnsembleStats ─────────────────────────────────────────────────────────


class TestEnsembleStats:
    def test_empty_list_returns_empty_dict(self):
        """ensemble_stats([]) must return {} not raise."""
        result = ensemble_stats([])
        assert result == {}

    def test_single_element_std_is_zero(self):
        """Single-element ensemble: std=0, min=max=mean=the value."""
        result = ensemble_stats([75.0])
        assert result["n"] == 1
        assert result["mean"] == pytest.approx(75.0)
        assert result["std"] == pytest.approx(0.0)
        assert result["min"] == pytest.approx(75.0)
        assert result["max"] == pytest.approx(75.0)
        assert result["p10"] == pytest.approx(75.0)
        assert result["p90"] == pytest.approx(75.0)

    def test_returns_all_required_keys(self):
        """Result must contain n, mean, std, min, max, p10, p90."""
        result = ensemble_stats([60.0, 65.0, 70.0, 75.0, 80.0])
        for key in ("n", "mean", "std", "min", "max", "p10", "p90"):
            assert key in result, f"Missing key: {key}"

    def test_mean_std_correct(self):
        """Verify mean and std match statistics module on known data."""
        import statistics

        temps = [68.0, 70.0, 72.0, 74.0, 76.0]
        result = ensemble_stats(temps)
        assert result["mean"] == pytest.approx(statistics.mean(temps))
        # ensemble_stats uses sample std (statistics.stdev, denominator n-1)
        assert result["std"] == pytest.approx(statistics.stdev(temps), rel=1e-6)

    def test_min_max_correct(self):
        """min and max match the actual extremes."""
        temps = [55.0, 70.0, 80.0, 63.0, 71.0]
        result = ensemble_stats(temps)
        assert result["min"] == pytest.approx(55.0)
        assert result["max"] == pytest.approx(80.0)

    def test_p10_less_than_p90(self):
        """p10 <= mean <= p90 for a non-degenerate ensemble."""
        temps = list(range(60, 80))  # [60, 61, ..., 79], 20 values
        result = ensemble_stats(temps)
        assert result["p10"] <= result["mean"]
        assert result["mean"] <= result["p90"]
        assert result["p10"] < result["p90"]


# ── TestBootstrapCI ───────────────────────────────────────────────────────────


class TestBootstrapCI:
    """Tests for _bootstrap_ci — bootstrap 90% CI on ensemble probability."""

    def test_too_few_members_returns_wide_ci(self):
        """N < 5 → maximally uncertain (0.0, 1.0)."""
        temps = [70.0, 71.0, 72.0]  # only 3 members
        condition = {"type": "above", "threshold": 68.0}
        lo, hi = _bootstrap_ci(temps, condition)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(1.0)

    def test_small_n_under_30_returns_wide_ci(self):
        """N < 30 but >= 5 → also returns (0.0, 1.0) per #114."""
        temps = list(range(60, 75))  # 15 members
        condition = {"type": "above", "threshold": 68.0}
        lo, hi = _bootstrap_ci(temps, condition)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(1.0)

    def test_above_condition_clear_outcome(self):
        """N >= 30, all temps above threshold → CI near (1.0, 1.0)."""
        temps = [80.0] * 40  # 40 members all above 70
        condition = {"type": "above", "threshold": 70.0}
        lo, hi = _bootstrap_ci(temps, condition, n=200)
        assert lo >= 0.9, f"Expected lo near 1.0, got {lo}"
        assert hi == pytest.approx(1.0, abs=1e-9)

    def test_below_condition_returns_valid_tuple(self):
        """'below' condition: returns (lo, hi) with 0 <= lo <= hi <= 1."""
        temps = list(range(50, 90))  # 40 members spanning 50–89°F
        condition = {"type": "below", "threshold": 70.0}
        lo, hi = _bootstrap_ci(temps, condition, n=200)
        assert 0.0 <= lo <= hi <= 1.0

    def test_between_condition_returns_valid_tuple(self):
        """'between' condition: returns (lo, hi) with 0 <= lo <= hi <= 1."""
        temps = list(range(60, 100))  # 40 members spanning 60–99°F
        condition = {"type": "between", "lower": 70.0, "upper": 80.0}
        lo, hi = _bootstrap_ci(temps, condition, n=200)
        assert 0.0 <= lo <= hi <= 1.0


# ── TestCensoringCorrection (#23) ─────────────────────────────────────────────


class TestCensoringCorrection:
    """Tests for censoring_correction() in weather_markets (#23)."""

    def test_no_censoring_returns_mean_unchanged(self):
        """Probs spread across (0, 1) with no censoring → corrected == raw mean."""
        from weather_markets import censoring_correction

        probs = [0.1, 0.3, 0.5, 0.7, 0.9]
        condition = {"type": "above", "threshold": 70.0}
        result = censoring_correction(probs, condition)
        raw_mean = sum(probs) / len(probs)
        assert abs(result - raw_mean) < 1e-9

    def test_censoring_at_zero_shrinks_toward_half(self):
        """Many zeros (>5% censored at 0) → result > raw mean (pulled toward 0.5)."""
        from weather_markets import censoring_correction

        probs = [0.0] * 80 + [0.8] * 20
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)
        result = censoring_correction(probs, condition)
        assert result > raw_mean

    def test_censoring_at_one_shrinks_toward_half(self):
        """Many ones (>5% censored at 1) → result < raw mean (pulled toward 0.5)."""
        from weather_markets import censoring_correction

        probs = [1.0] * 80 + [0.2] * 20
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)
        result = censoring_correction(probs, condition)
        assert result < raw_mean

    def test_exactly_at_threshold_applies_correction(self):
        """5% zeros > 1% censor_pct threshold → correction applies (result != raw mean)."""
        from weather_markets import censoring_correction

        probs = [0.0] * 5 + [0.6] * 95
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(
            probs
        )  # 0.57, zeros pull toward 0.5 → result < raw_mean
        result = censoring_correction(probs, condition, censor_pct=0.01)
        assert result != raw_mean  # correction was applied
        assert result < raw_mean  # zeros pull mean of 0.57 down toward 0.5

    def test_result_clamped_between_zero_and_one(self):
        """Corrected probability must always be in [0, 1]."""
        from weather_markets import censoring_correction

        probs = [0.0] * 99 + [0.01]
        condition = {"type": "above", "threshold": 70.0}
        result = censoring_correction(probs, condition)
        assert 0.0 <= result <= 1.0

    def test_empty_list_returns_half(self):
        """Empty prob list returns 0.5 (maximally uncertain)."""
        from weather_markets import censoring_correction

        result = censoring_correction([], {"type": "above", "threshold": 70.0})
        assert result == 0.5

    def test_correction_formula_values(self):
        """Verify the Tobit-style formula numerically."""
        from weather_markets import censoring_correction

        probs = [0.0] * 60 + [0.9] * 40
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)  # 0.36
        censored_fraction = 60 / 100  # 0.60
        blend = censored_fraction * 0.5  # 0.30
        expected = raw_mean * (1 - blend) + 0.5 * blend  # 0.402
        result = censoring_correction(probs, condition, censor_pct=0.01)
        assert abs(result - expected) < 1e-9
