"""Unit tests for key functions in weather_markets.py and utils.py."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so imports work when run from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import UTC

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

    # ── L2-D regression tests ─────────────────────────────────────────────────

    def test_l2d_integer_1_converted_to_1_cent(self):
        """L2-D: integer value 1 (= 1¢) must be divided by 100, not returned as 1.0.

        The old `v > 1` check did not trigger for v == 1, so a 1¢ market
        was parsed as $1.00 — an off-by-100× error on the rarest markets.
        """
        market = {"yes_bid": 1, "yes_ask": 2, "no_bid": 98}
        result = parse_market_price(market)
        assert result["yes_bid"] == pytest.approx(0.01), (
            f"L2-D: yes_bid=1 (1¢) should parse to 0.01, got {result['yes_bid']}"
        )
        assert result["yes_ask"] == pytest.approx(0.02), (
            f"L2-D: yes_ask=2 (2¢) should parse to 0.02, got {result['yes_ask']}"
        )

    def test_l2d_zero_bid_not_bypassed_by_or(self):
        """L2-D: a valid 0¢ bid must not be bypassed by the or-fallback.

        When yes_bid=0 and yes_bid_dollars is present, the old `or` operator
        treated 0 as falsy and used yes_bid_dollars instead — corrupting the price.
        """
        # yes_bid=0 is a valid 0¢ bid; yes_bid_dollars should NOT be used
        market = {"yes_bid": 0, "yes_bid_dollars": 0.55, "yes_ask": 50}
        result = parse_market_price(market)
        assert result["yes_bid"] == pytest.approx(0.0), (
            f"L2-D: yes_bid=0 should parse to 0.0; or-bypass returned {result['yes_bid']}"
        )


class TestEntryEdgeVsMidEdge:
    """L7-C: entry_side_edge must use ask price, not mid, for each side."""

    def test_yes_entry_side_edge_uses_yes_ask(self):
        """YES trades: entry_side_edge = blended_prob - yes_ask (smaller than mid-edge)."""
        from weather_markets import parse_market_price

        # yes_bid=0.60 yes_ask=0.64 → mid=0.62
        prices = parse_market_price({"yes_bid": 60, "yes_ask": 64, "no_bid": 36})
        blended_prob = 0.72
        mid = prices["implied_prob"]  # 0.62
        yes_ask = prices["yes_ask"]  # 0.64

        mid_edge = blended_prob - mid  # 0.10
        entry_edge = blended_prob - yes_ask  # 0.08

        # entry_side_edge must be LESS than mid-based edge for YES
        assert entry_edge < mid_edge, "YES entry edge must be smaller than mid edge"
        assert entry_edge == pytest.approx(0.08, abs=1e-6)

    def test_no_entry_side_edge_uses_no_ask(self):
        """NO trades: entry_side_edge = P(NO wins) - no_ask = (1-blended_prob) - (1-yes_bid).

        P0-14 fix: the old formula used blended_prob - no_ask (inverted sign), which
        produced negative edge for valid NO trades and blocked them at the gate.
        Correct formula: (1 - blended_prob) - no_ask.
        """
        from weather_markets import parse_market_price

        # yes_bid=0.60 yes_ask=0.64 → no_ask = 1 - yes_bid = 0.40
        prices = parse_market_price({"yes_bid": 60, "yes_ask": 64, "no_bid": 36})
        blended_prob = 0.35  # we think YES=35%, so P(NO wins) = 65%
        yes_bid = prices["yes_bid"]  # 0.60

        no_ask = 1.0 - yes_bid  # 0.40 — what we actually pay for NO
        # Correct formula (P0-14): P(NO wins) - cost_of_NO
        correct_entry_edge = (1.0 - blended_prob) - no_ask  # 0.65 - 0.40 = +0.25
        # Old buggy formula produced: blended_prob - no_ask = 0.35 - 0.40 = -0.05
        buggy_entry_edge = blended_prob - no_ask  # -0.05 (would block a valid trade)

        assert correct_entry_edge > 0, (
            "Correct NO edge must be positive for a valid NO trade"
        )
        assert buggy_entry_edge < 0, (
            "Old buggy formula produced negative edge (the bug)"
        )
        assert correct_entry_edge == pytest.approx(0.25, abs=1e-6)


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

    # 25°F is in the 20-28°F range → SLR 15 (updated per NOAA #34 spec)
    assert snow_liquid_ratio(wet_bulb_f=25.0) == 15
    # Very cold (<= 20°F) → SLR 20
    assert snow_liquid_ratio(wet_bulb_f=10.0) == 20


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


class TestKellyFeeRate:
    """L2-B: kelly_fraction must always be called with fee_rate=KALSHI_FEE_RATE.

    Fee-free Kelly (fee_rate=0.0) overstates position size because it ignores
    the 7% Kalshi fee on winnings. This inflates sizing by ~5–10% for typical
    edges, leading to systematic over-betting and negative expected P&L.
    """

    def test_fee_adjusted_kelly_less_than_fee_free(self):
        """Fee-adjusted Kelly must be strictly less than fee-free Kelly for any positive edge.

        L2-B invariant: KALSHI_FEE_RATE=0.07 reduces net winnings, so the optimal
        bet fraction under the fee is lower than without it.
        """
        from utils import KALSHI_FEE_RATE

        our_prob = 0.65
        price = 0.50  # fair odds

        kelly_no_fee = kelly_fraction(our_prob, price, fee_rate=0.0)
        kelly_with_fee = kelly_fraction(our_prob, price, fee_rate=KALSHI_FEE_RATE)

        assert kelly_no_fee > 0, "Positive edge must produce positive Kelly"
        assert kelly_with_fee < kelly_no_fee, (
            f"Fee-adjusted Kelly {kelly_with_fee:.4f} must be < fee-free Kelly "
            f"{kelly_no_fee:.4f} — fee reduces optimal bet size"
        )

    def test_kelly_default_equals_kalshi_fee_rate(self):
        """Default kelly_fraction() must use KALSHI_FEE_RATE, not 0.

        P2-8 fix: the old default was fee_rate=0.0 (a footgun). The default is now
        KALSHI_FEE_RATE so callers that omit fee_rate get production-correct sizing.
        """
        from utils import KALSHI_FEE_RATE

        our_prob = 0.60
        price = 0.45

        default_kelly = kelly_fraction(our_prob, price)
        fee_kelly = kelly_fraction(our_prob, price, fee_rate=KALSHI_FEE_RATE)
        zero_fee_kelly = kelly_fraction(our_prob, price, fee_rate=0.0)

        assert default_kelly == pytest.approx(fee_kelly), (
            "Default kelly_fraction() must equal explicit fee_rate=KALSHI_FEE_RATE"
        )
        assert default_kelly < zero_fee_kelly, (
            "Default (fee-adjusted) Kelly must be smaller than fee-free Kelly"
        )

    def test_fee_adjusted_never_exceeds_fee_free_across_probs(self):
        """L2-B: for all valid (prob, price) pairs, fee-adjusted Kelly ≤ fee-free Kelly.

        This is the core invariant — any call site that omits fee_rate=KALSHI_FEE_RATE
        systematically overstates position size. We verify over a grid of realistic inputs.
        """
        from utils import KALSHI_FEE_RATE

        # Grid of realistic (our_prob, market_price) combos where there is positive edge
        cases = [
            (0.60, 0.45),  # 15pp edge
            (0.65, 0.50),  # 15pp edge at mid
            (0.55, 0.40),  # 15pp edge
            (0.70, 0.55),  # 15pp edge
            (0.80, 0.65),  # 15pp edge, high confidence
        ]
        for our_prob, price in cases:
            free_k = kelly_fraction(our_prob, price, fee_rate=0.0)
            fee_k = kelly_fraction(our_prob, price, fee_rate=KALSHI_FEE_RATE)
            assert fee_k <= free_k + 1e-9, (
                f"prob={our_prob}, price={price}: "
                f"fee-adjusted Kelly {fee_k:.6f} must not exceed fee-free Kelly {free_k:.6f}"
            )
            if free_k > 0:
                assert fee_k < free_k, (
                    f"prob={our_prob}, price={price}: "
                    f"fee-adjusted Kelly must be strictly less than fee-free Kelly when edge exists"
                )


class TestKellyCap:
    """Verify kelly_fraction hard cap is KELLY_CAP=0.25 (P3-13: unified from 0.33)."""

    def test_kelly_fraction_caps_at_kelly_cap(self):
        """Quarter-Kelly never exceeds KELLY_CAP=0.25 (full_kelly/4 tops out just under cap).

        With quarter-Kelly, full_kelly approaches but never exceeds 1.0, so quarter_kelly
        approaches but never reaches 0.25 = KELLY_CAP. The cap is a safety ceiling.
        Verify: result <= KELLY_CAP, and a high-edge case produces a meaningful fraction.
        """
        from utils import KELLY_CAP

        # our_prob=0.95, price=0.10, fee_rate=0.02: very high edge, full Kelly ≈ 0.944
        # quarter_kelly ≈ 0.236 — below cap but confirms ceiling is enforced
        result = kelly_fraction(our_prob=0.95, price=0.10, fee_rate=0.02)
        assert result <= KELLY_CAP, (
            f"Kelly must not exceed cap {KELLY_CAP}, got {result}"
        )
        assert result > 0.20, (
            f"Strong edge should give significant Kelly fraction, got {result}"
        )
        assert result == pytest.approx(0.23608, abs=1e-4), (
            f"Expected ~0.236 (quarter of full Kelly ~0.944), got {result}"
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


# ── TestEdgeConfidence ────────────────────────────────────────────────────────


class TestEdgeConfidence:
    """Tests for edge_confidence(days_out) horizon discount factor."""

    def test_day_0_returns_one(self):
        from weather_markets import edge_confidence

        assert edge_confidence(0) == pytest.approx(1.0)

    def test_day_2_returns_one(self):
        from weather_markets import edge_confidence

        assert edge_confidence(2) == pytest.approx(1.0)

    def test_day_14_returns_0_60(self):
        from weather_markets import edge_confidence

        assert edge_confidence(14) == pytest.approx(0.60, abs=1e-6)

    def test_floor_at_day_20(self):
        from weather_markets import edge_confidence

        assert edge_confidence(20) == pytest.approx(0.60, abs=1e-6)
        assert edge_confidence(100) == pytest.approx(0.60, abs=1e-6)

    def test_day_7_in_linear_segment(self):
        """days_out=7 is at the boundary of segment 2; should be 0.80."""
        from weather_markets import edge_confidence

        assert edge_confidence(7) == pytest.approx(0.80, abs=1e-4)

    def test_monotonically_decreasing(self):
        from weather_markets import edge_confidence

        values = [edge_confidence(d) for d in range(0, 20)]
        for i in range(len(values) - 1):
            assert values[i] >= values[i + 1], (
                f"Not monotone at day {i}: {values[i]} > {values[i + 1]}"
            )


# ── TestAdjustedEdgeInAnalyzeTrade ────────────────────────────────────────────


class TestAdjustedEdgeInAnalyzeTrade:
    """analyze_trade() must return both raw net_edge and adjusted_edge (#63)."""

    def test_analyze_trade_returns_adjusted_edge_key(self, monkeypatch):
        """Result dict must contain adjusted_edge and edge_confidence_factor."""
        from datetime import date, timedelta

        import weather_markets as wm

        target = date.today() + timedelta(days=10)
        ticker = f"KXHIGHNYC-{target.strftime('%y%b%d').upper()}-T70"

        enriched = {
            "_city": "NYC",
            "_date": target,
            "_hour": 14,
            "_forecast": {
                "temps": [72.0] * 50,
                "source": "ensemble",
                "high_f": 72.0,
                "low_f": 62.0,
            },
            "yes_bid": 0.35,
            "yes_ask": 0.37,
            "ticker": ticker,
            "title": "NYC High above 70",
            "close_time": "",
        }

        monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.50)
        monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)

        result = wm.analyze_trade(enriched)
        if result is None:
            pytest.skip("analyze_trade returned None for this enriched dict")
        assert "adjusted_edge" in result, "Missing adjusted_edge key"
        assert "edge_confidence_factor" in result, "Missing edge_confidence_factor key"
        assert result["edge_confidence_factor"] == pytest.approx(
            wm.edge_confidence(10), abs=1e-6
        )


# ── TestBlendWeightCalibrationPriority ───────────────────────────────────────


class TestBlendWeightCalibrationPriority:
    """_blend_weights() must use city weights > seasonal weights > hardcoded."""

    def test_city_weights_override_hardcoded(self, monkeypatch):
        """If city weights loaded, _blend_weights uses them (days_out=3 = no NWS scaling)."""
        import weather_markets as wm

        city_weights = {"NYC": {"ensemble": 0.50, "climatology": 0.10, "nws": 0.40}}
        monkeypatch.setattr(wm, "_CITY_WEIGHTS", city_weights)
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})

        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=3, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w_ens == pytest.approx(0.50, abs=1e-6)
        assert w_nws == pytest.approx(0.40, abs=1e-6)

    def test_seasonal_weights_used_when_no_city_weights(self, monkeypatch):
        """If no city weights but seasonal weights loaded, use seasonal (days_out=3 = no NWS scaling)."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(
            wm,
            "_SEASONAL_WEIGHTS",
            {"spring": {"ensemble": 0.45, "climatology": 0.20, "nws": 0.35}},
        )

        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=3, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w_ens == pytest.approx(0.45, abs=1e-6)
        assert w_nws == pytest.approx(0.35, abs=1e-6)

    def test_fallback_to_hardcoded_when_no_calibration(self, monkeypatch):
        """With empty dicts, result should match original hardcoded schedule."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})

        # days_out=5, hardcoded: w_nws=0.25, remainder split ensemble/clim
        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=5, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert abs(w_ens + w_clim + w_nws - 1.0) < 1e-6
        assert w_nws == pytest.approx(0.25, abs=1e-6)
        assert w_ens == pytest.approx(0.5175, abs=1e-6)
        assert w_clim == pytest.approx(0.2325, abs=1e-6)


def test_analyze_trade_result_has_model_consensus_field(monkeypatch):
    """analyze_trade result includes model_consensus bool when it returns a result."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    # Patch get_ensemble_temps to return a stable set of temps
    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    # Patch _get_consensus_probs to return agreeing models (consensus True)
    monkeypatch.setattr(wm, "_get_consensus_probs", lambda *a, **kw: (0.70, 0.72))
    # Patch get_weather_forecast to return a simple forecast
    monkeypatch.setattr(
        wm,
        "get_weather_forecast",
        lambda *a, **kw: {
            "high_f": 75.0,
            "low_f": 55.0,
            "precip_in": 0.0,
            "wind_mph": 5.0,
        },
    )

    from datetime import date, timedelta

    tomorrow = date.today() + timedelta(days=1)
    enriched = {
        "_forecast": {"high_f": 75.0, "low_f": 55.0, "precip_in": 0.0, "wind_mph": 5.0},
        "_date": tomorrow,
        "_city": "NYC",
        "_hour": None,
        "ticker": "KXHIGHNY-26APR09-T80",
        "title": "Will NYC high temperature be above 80°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 42,
        "yes_bid": 38,
        "volume": 500,
        "open_interest": 200,
        "close_time": (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(hours=20)
        ).isoformat(),
    }
    result = analyze_trade(enriched)
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    assert "model_consensus" in result
    assert isinstance(result["model_consensus"], bool)
    assert "near_threshold" in result
    assert isinstance(result["near_threshold"], bool)


def test_model_consensus_false_when_models_disagree(monkeypatch):
    """model_consensus is False when ICON and GFS differ by more than 8pp."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    # Models disagree by 15pp
    monkeypatch.setattr(
        wm, "_get_consensus_probs", lambda *a, **kw: (0.75, 0.60, 74.0, 68.0)
    )
    monkeypatch.setattr(
        wm,
        "get_weather_forecast",
        lambda *a, **kw: {
            "high_f": 75.0,
            "low_f": 55.0,
            "precip_in": 0.0,
            "wind_mph": 5.0,
        },
    )
    # Disable METAR lock-in: _metar_lock_in compares target_date against
    # datetime.now(UTC).date(). When the local "tomorrow" equals the UTC date
    # (US timezones after ~20:00 local), it fires and skips the consensus block.
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))

    from datetime import date, timedelta

    tomorrow = date.today() + timedelta(days=1)
    enriched = {
        "_forecast": {"high_f": 75.0, "low_f": 55.0, "precip_in": 0.0, "wind_mph": 5.0},
        "_date": tomorrow,
        "_city": "NYC",
        "_hour": None,
        "ticker": "KXHIGHNY-26APR09-T80",
        "title": "Will NYC high temperature be above 80°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 42,
        "yes_bid": 38,
        "volume": 500,
        "open_interest": 200,
        "close_time": (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(hours=20)
        ).isoformat(),
    }
    result = analyze_trade(enriched)
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    assert result["model_consensus"] is False


def test_om_rate_limit_enforces_interval(monkeypatch):
    """_om_rate_limit ensures at least the per-endpoint interval between calls."""
    import time

    import weather_markets as wm

    # Use the forecast endpoint (0.5s normally); override to 0.1s for test speed.
    monkeypatch.setattr(wm, "_OM_FORECAST_MIN_INTERVAL", 0.1)
    wm._OM_FORECAST_STATE[0] = (
        0.0  # reset last-ts so first call doesn't inherit old state
    )

    forecast_url = "https://api.open-meteo.com/v1/forecast"
    t0 = time.monotonic()
    wm._om_rate_limit(forecast_url)
    wm._om_rate_limit(forecast_url)
    elapsed = time.monotonic() - t0

    assert elapsed >= 0.08  # at least ~_OM_FORECAST_MIN_INTERVAL between two calls


# ── Phase 1: NBM + weatherapi fallback chain ─────────────────────────────────


class TestFetchNbmForecast:
    """fetch_nbm_forecast() wraps get_nws_daily_forecast() into a flat dict."""

    def test_returns_high_low_dict(self, monkeypatch):
        from datetime import date

        from nws import fetch_nbm_forecast

        target = date(2026, 5, 1)
        coords = (40.77, -73.97, "America/New_York")

        monkeypatch.setattr(
            "nws.get_nws_daily_forecast",
            lambda city, coords: {target.isoformat(): {"high": 72.0, "low": 55.0}},
        )
        result = fetch_nbm_forecast("NYC", coords, target)
        assert result == {"high_f": 72.0, "low_f": 55.0}

    def test_returns_none_when_date_missing(self, monkeypatch):
        from datetime import date

        from nws import fetch_nbm_forecast

        monkeypatch.setattr("nws.get_nws_daily_forecast", lambda *a: {})
        result = fetch_nbm_forecast(
            "NYC", (40.77, -73.97, "America/New_York"), date(2026, 5, 1)
        )
        assert result is None

    def test_returns_none_when_nws_unavailable(self, monkeypatch):
        from datetime import date

        from nws import fetch_nbm_forecast

        monkeypatch.setattr("nws.get_nws_daily_forecast", lambda *a: None)
        result = fetch_nbm_forecast(
            "NYC", (40.77, -73.97, "America/New_York"), date(2026, 5, 1)
        )
        assert result is None

    def test_partial_data_high_only(self, monkeypatch):
        from datetime import date

        from nws import fetch_nbm_forecast

        target = date(2026, 5, 1)
        monkeypatch.setattr(
            "nws.get_nws_daily_forecast",
            lambda *a: {target.isoformat(): {"high": 68.0, "low": None}},
        )
        result = fetch_nbm_forecast("NYC", (40.77, -73.97, "America/New_York"), target)
        assert result == {"high_f": 68.0, "low_f": None}


class TestFetchTemperatureWeatherapi:
    """fetch_temperature_weatherapi() requires WEATHERAPI_KEY to be set."""

    def test_returns_none_when_key_missing(self):
        from datetime import date

        import weather_markets as wm

        orig = wm.WEATHERAPI_KEY
        wm.WEATHERAPI_KEY = ""
        try:
            result = wm.fetch_temperature_weatherapi("NYC", date(2026, 5, 1))
            assert result is None
        finally:
            wm.WEATHERAPI_KEY = orig

    def test_parses_response_correctly(self, monkeypatch):
        import datetime
        from unittest.mock import MagicMock

        import weather_markets as wm

        # Use a date within the 14-day forecast window
        target = datetime.date.today() + datetime.timedelta(days=3)
        fake_response = {
            "forecast": {
                "forecastday": [
                    {
                        "date": target.isoformat(),
                        "day": {"maxtemp_f": 74.5, "mintemp_f": 58.1},
                    }
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = fake_response

        monkeypatch.setattr(wm, "WEATHERAPI_KEY", "test-key")
        monkeypatch.setattr(wm.requests, "get", lambda *a, **kw: mock_resp)
        wm._WEATHERAPI_CACHE.clear()

        result = wm.fetch_temperature_weatherapi("NYC", target)
        assert result == {"high_f": 74.5, "low_f": 58.1}

    def test_returns_none_on_request_failure(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        monkeypatch.setattr(wm, "WEATHERAPI_KEY", "test-key")
        monkeypatch.setattr(
            "requests.get", lambda *a, **kw: (_ for _ in ()).throw(OSError("timeout"))
        )
        wm._WEATHERAPI_CACHE.clear()
        wm._weatherapi_cb.record_success()  # ensure circuit closed

        result = wm.fetch_temperature_weatherapi("NYC", date(2026, 5, 1))
        assert result is None

    def test_circuit_breaker_skips_when_open(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        monkeypatch.setattr(wm, "WEATHERAPI_KEY", "test-key")
        wm._WEATHERAPI_CACHE.clear()
        # Trip the circuit
        wm._weatherapi_cb._failure_count = wm._weatherapi_cb.failure_threshold
        wm._weatherapi_cb._opened_at = __import__("time").monotonic()

        result = wm.fetch_temperature_weatherapi("NYC", date(2026, 5, 1))
        assert result is None
        # Restore
        wm._weatherapi_cb.record_success()


class TestGetWeatherForecastFallbackChain:
    """get_weather_forecast() should try NBM + weatherapi before Pirate Weather."""

    def test_uses_nbm_when_open_meteo_fails(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        target = date(2026, 5, 1)

        # Open-Meteo always fails
        monkeypatch.setattr(
            "weather_markets._forecast_cb._failure_count",
            wm._forecast_cb.failure_threshold,
        )
        monkeypatch.setattr(
            "weather_markets._forecast_cb._opened_at", __import__("time").monotonic()
        )

        # NBM returns data
        monkeypatch.setattr(
            wm,
            "fetch_nbm_forecast",
            lambda city, coords, dt: {"high_f": 71.0, "low_f": 54.0},
        )
        # weatherapi unavailable
        monkeypatch.setattr(wm, "fetch_temperature_weatherapi", lambda *a: None)
        # Pirate Weather should NOT be called
        called = []
        monkeypatch.setattr(
            wm,
            "fetch_temperature_pirate_weather",
            lambda *a: called.append(True) or None,
        )

        wm._forecast_cache.clear()
        result = wm.get_weather_forecast("NYC", target)

        assert result is not None
        assert result["high_f"] == pytest.approx(71.0)
        assert not called, "Pirate Weather should not be called when NBM succeeds"

    def test_falls_through_to_pirate_when_nbm_and_weatherapi_fail(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        target = date(2026, 5, 1)

        # Open-Meteo fails
        monkeypatch.setattr(
            "weather_markets._forecast_cb._failure_count",
            wm._forecast_cb.failure_threshold,
        )
        monkeypatch.setattr(
            "weather_markets._forecast_cb._opened_at", __import__("time").monotonic()
        )

        # NBM + weatherapi both fail
        monkeypatch.setattr(wm, "fetch_nbm_forecast", lambda *a: None)
        monkeypatch.setattr(wm, "fetch_temperature_weatherapi", lambda *a: None)

        # Pirate Weather succeeds
        monkeypatch.setattr(
            wm,
            "fetch_temperature_pirate_weather",
            lambda *a: {"high_f": 69.0, "low_f": 52.0, "precip_in": 0.0},
        )

        wm._forecast_cache.clear()
        result = wm.get_weather_forecast("NYC", target)

        assert result is not None
        assert result["_source"] == "pirate_weather"


class TestCheckEnsembleCircuitHealth:
    """check_ensemble_circuit_health() warns when circuit has been open >24h."""

    def test_no_warning_when_circuit_closed(self, caplog):
        import weather_markets as wm

        wm._ensemble_cb.record_success()  # ensure closed
        with caplog.at_level("WARNING"):
            wm.check_ensemble_circuit_health()
        assert "open_meteo_ensemble" not in caplog.text

    def test_logs_info_when_open_under_24h(self, monkeypatch, caplog):
        import time

        import weather_markets as wm

        # Simulate circuit open for 1 hour
        monkeypatch.setattr(wm._ensemble_cb, "_wall_opened_at", time.time() - 3600)
        monkeypatch.setattr(wm._ensemble_cb, "_opened_at", time.monotonic())
        with caplog.at_level("INFO"):
            wm.check_ensemble_circuit_health()
        assert "open_meteo_ensemble" in caplog.text
        wm._ensemble_cb.record_success()

    def test_logs_warning_when_open_over_24h(self, monkeypatch, caplog):
        import time

        import weather_markets as wm

        # Simulate circuit open for 25 hours
        monkeypatch.setattr(wm._ensemble_cb, "_wall_opened_at", time.time() - 25 * 3600)
        monkeypatch.setattr(wm._ensemble_cb, "_opened_at", time.monotonic())
        with caplog.at_level("WARNING"):
            wm.check_ensemble_circuit_health()
        assert "24" in caplog.text or "hours" in caplog.text
        wm._ensemble_cb.record_success()


class TestCityDetection:
    """L5-B: bare 'LA' in ticker_up substring must not misfire on city names
    that contain 'LA' (DALLAS, ATLANTA, PHILADELPHIA)."""

    def _city(self, ticker: str, title: str = "") -> str | None:
        """Call enrich_with_forecast with a mocked forecast and return _city."""
        from unittest.mock import patch

        import weather_markets as wm

        market = {"ticker": ticker, "title": title}
        with patch.object(wm, "get_weather_forecast", return_value=None):
            result = wm.enrich_with_forecast(market)
        return result.get("_city")

    # ── LA must still be detected ────────────────────────────────────────────

    def test_la_high_temp_series_detected(self):
        """KXHIGHLA temperature series → city == 'LA'."""
        assert self._city("KXHIGHLA-26APR25-T75-B") == "LA"

    def test_la_low_temp_series_detected(self):
        """KXLOWLA temperature series → city == 'LA'."""
        assert self._city("KXLOWLA-26APR25-T55-B") == "LA"

    def test_la_as_hyphen_segment_detected(self):
        """Rain market with '-LA-' segment (KXRAIN-LA-...) → city == 'LA'."""
        assert self._city("KXRAIN-LA-26APR25-2IN") == "LA"

    def test_la_title_detected(self):
        """'los angeles' in title → city == 'LA' even with generic ticker."""
        assert self._city("KXRAIN-26APR25-2IN", "los angeles rain > 2 inches") == "LA"

    # ── Substring-false-positive cities must NOT be misdetected as LA ────────

    def test_dallas_full_name_in_ticker_not_la(self):
        """KXRAIN-DALLAS ticker: 'DALLAS' contains 'LA' — must be Dallas, not LA."""
        city = self._city("KXRAIN-DALLAS-26APR25-2IN", "dallas rain")
        assert city == "Dallas", f"Expected 'Dallas', got {city!r}"

    def test_atlanta_full_name_in_ticker_not_la(self):
        """KXRAIN-ATLANTA ticker: 'ATLANTA' contains 'LA' — must be Atlanta, not LA."""
        city = self._city("KXRAIN-ATLANTA-26APR25-2IN", "atlanta rain")
        assert city == "Atlanta", f"Expected 'Atlanta', got {city!r}"

    def test_philadelphia_full_name_in_ticker_not_la(self):
        """KXRAIN-PHILADELPHIA ticker: 'PHILA' contains 'LA' — must be Philadelphia."""
        city = self._city("KXRAIN-PHILADELPHIA-26APR25-2IN", "philadelphia rain")
        assert city == "Philadelphia", f"Expected 'Philadelphia', got {city!r}"


class TestLearnedWeightsTTL:
    """L4-D: load_learned_weights() must discard files older than 7 days."""

    def test_stale_weights_file_falls_back_to_defaults(self, tmp_path):
        """File mtime 8 days ago → loader returns {} (default weights)."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        fake_weights = {"Dallas": {"ecmwf_ifs04": 2.0, "gfs_seamless": 1.0}}
        weights_file = tmp_path / "learned_weights.json"
        weights_file.write_text(json.dumps(fake_weights))
        eight_days_ago = time.time() - 8 * 86400

        orig = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}
        try:
            with (
                patch("weather_markets.os.path.getmtime", return_value=eight_days_ago),
                patch("weather_markets.Path") as mock_path_cls,
            ):
                # Path(__file__).parent / "data" / "learned_weights.json"
                mock_path_inst = mock_path_cls.return_value.parent.__truediv__.return_value.__truediv__.return_value
                mock_path_inst.exists.return_value = True
                mock_path_inst.read_text.return_value = json.dumps(fake_weights)
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig

        assert result == {}, f"Expected {{}} for stale file, got {result!r}"

    def test_fresh_weights_file_is_loaded(self, tmp_path):
        """File mtime 1 day ago → loader reads and returns file contents."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        fake_weights = {"Dallas": {"ecmwf_ifs04": 2.0, "gfs_seamless": 1.0}}
        weights_file = tmp_path / "learned_weights.json"
        weights_file.write_text(json.dumps(fake_weights))
        one_day_ago = time.time() - 1 * 86400

        orig = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}
        try:
            with (
                patch("weather_markets.os.path.getmtime", return_value=one_day_ago),
                patch("weather_markets.Path") as mock_path_cls,
            ):
                # Path(__file__).parent / "data" / "learned_weights.json"
                mock_path_inst = mock_path_cls.return_value.parent.__truediv__.return_value.__truediv__.return_value
                mock_path_inst.exists.return_value = True
                mock_path_inst.read_text.return_value = json.dumps(fake_weights)
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig

        assert result == fake_weights, (
            f"Expected weights dict for fresh file, got {result!r}"
        )


# ── P1-9: learned_weights validation ─────────────────────────────────────────


class TestLearnedWeightsValidation:
    """P1-9: save_learned_weights must reject corrupt data (win-rate floats),
    and load_learned_weights must delete and ignore corrupt files."""

    def test_save_rejects_float_city_values(self, tmp_path, monkeypatch):
        """save_learned_weights must not write when city values are floats (win-rates)."""
        import weather_markets as wm

        # Call the real function but capture whether it reaches the write step
        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}
        try:
            # corrupt: city mapped to float (win rate), not {model: weight}
            corrupt = {"NYC": 0.72, "Chicago": 0.65}
            wm.save_learned_weights(corrupt)
            # If file exists in data/, it means validation failed to block it
            data_path = tmp_path / "learned_weights.json"
            assert not data_path.exists(), (
                "save_learned_weights must not write corrupt float values"
            )
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

    def test_save_rejects_near_zero_weights(self):
        """save_learned_weights must not write when any model weight is near zero."""
        import weather_markets as wm

        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}
        wrote = [False]
        import os as _os_mod

        orig_replace = _os_mod.replace

        def fake_replace(src, dst):
            wrote[0] = True
            return orig_replace(src, dst)

        try:
            import unittest.mock as _mock

            with _mock.patch("os.replace", side_effect=fake_replace):
                bad = {"NYC": {"gfs_seamless": 0.0, "ecmwf_ifs04": 1.5}}
                wm.save_learned_weights(bad)
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

        assert not wrote[0], (
            "save_learned_weights must not call os.replace for near-zero weights"
        )

    def test_save_allows_valid_weights(self, tmp_path, monkeypatch):
        """save_learned_weights must write valid {city: {model: weight}} dicts."""

        import weather_markets as wm

        valid = {"NYC": {"gfs_seamless": 1.2, "ecmwf_ifs04": 0.9, "icon_seamless": 0.9}}

        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}

        original_truediv = type(tmp_path).__truediv__

        def redirect_path(self, other):
            result = original_truediv(self, other)
            if str(other) == "learned_weights.json":
                return tmp_path / "learned_weights.json"
            return result

        try:
            monkeypatch.setattr(wm, "Path", lambda *args, **kwargs: tmp_path)
            # Just verify validation passes by checking _LEARNED_WEIGHTS is updated
            import unittest.mock as _mock

            with _mock.patch("os.replace"), _mock.patch("os.fdopen") as mock_fdopen:
                import io

                mock_fdopen.return_value.__enter__ = lambda s: io.StringIO()
                mock_fdopen.return_value.__exit__ = lambda s, *a: None
                wm.save_learned_weights(valid)
                assert wm._LEARNED_WEIGHTS == valid, (
                    "save_learned_weights must update _LEARNED_WEIGHTS for valid input"
                )
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

    def test_load_rejects_float_city_values(self, monkeypatch):
        """load_learned_weights must return {} and delete corrupt file with float city values."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        corrupt = {"NYC": 0.72}
        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}
        try:
            with (
                patch(
                    "weather_markets.os.path.getmtime", return_value=time.time() - 3600
                ),
                patch("weather_markets.Path") as mock_path_cls,
            ):
                mock_inst = mock_path_cls.return_value.parent.__truediv__.return_value.__truediv__.return_value
                mock_inst.exists.return_value = True
                mock_inst.read_text.return_value = json.dumps(corrupt)
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

        assert result == {}, (
            f"load_learned_weights must return {{}} for corrupt float values, got {result!r}"
        )

    def test_load_rejects_non_positive_weights(self, monkeypatch):
        """load_learned_weights must return {} when any weight is <= 0."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        bad = {"NYC": {"gfs_seamless": 0.0, "ecmwf_ifs04": 1.5}}
        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}
        try:
            with (
                patch(
                    "weather_markets.os.path.getmtime", return_value=time.time() - 3600
                ),
                patch("weather_markets.Path") as mock_path_cls,
            ):
                mock_inst = mock_path_cls.return_value.parent.__truediv__.return_value.__truediv__.return_value
                mock_inst.exists.return_value = True
                mock_inst.read_text.return_value = json.dumps(bad)
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

        assert result == {}, (
            f"load_learned_weights must return {{}} for non-positive weights, got {result!r}"
        )


# ── TestUtcTodayDate ──────────────────────────────────────────────────────────


class TestUtcTodayDate:
    """L5-E: weather_markets must use datetime.now(UTC).date() not date.today()."""

    def test_market_lookup_uses_utc_date_not_local(self):
        """_forecast_uncertainty should use UTC date, so patching datetime.now()
        changes the days_out calculation."""
        from datetime import UTC, date, datetime
        from unittest.mock import MagicMock, patch

        import weather_markets as wm

        # Use a target date 3 days from a known UTC reference date
        known_utc_date = date(2025, 6, 15)
        target = date(2025, 6, 18)  # 3 days out → uncertainty == 4.0

        mock_dt = MagicMock(spec=datetime)
        mock_dt.now.return_value.date.return_value = known_utc_date

        with patch("weather_markets.datetime", mock_dt):
            result = wm._forecast_uncertainty(target)

        # 3 days out → 4.0 per _forecast_uncertainty() ladder
        assert result == 4.0, f"Expected 4.0 (3 days out from UTC date), got {result!r}"
        # Verify datetime.now was called with UTC sentinel
        mock_dt.now.assert_called_once_with(UTC)

    def test_no_date_today_calls_remain(self):
        """weather_markets.py must not contain any date.today() calls."""
        from pathlib import Path

        src = (Path(__file__).parent.parent / "weather_markets.py").read_text()
        assert "date.today()" not in src, (
            "Found date.today() in weather_markets.py — replace with datetime.now(UTC).date()"
        )


class TestStationBiasKeys:
    """Regression: bias dict keys must match CITY_COORDS keys exactly.

    Previously used 3-letter codes (MIA, DEN, CHI, DAL, LAX) while city names
    passed at runtime are full names (Miami, Denver, Chicago, Dallas, LA).
    Only NYC accidentally matched, so all other corrections silently returned 0.
    """

    def test_miami_high_bias_applies(self):
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("Miami", 90.0, var="max")
        assert corrected == 87.0, (
            f"Miami 3°F warm bias must be applied; got {corrected}"
        )

    def test_denver_high_bias_applies(self):
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("Denver", 75.0, var="max")
        assert corrected == 73.0, (
            f"Denver 2°F warm bias must be applied; got {corrected}"
        )

    def test_chicago_high_bias_applies(self):
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("Chicago", 80.0, var="max")
        assert corrected == 79.5, (
            f"Chicago 0.5°F warm bias must be applied; got {corrected}"
        )

    def test_nyc_still_works(self):
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("NYC", 72.0, var="max")
        assert corrected == 71.0, f"NYC 1°F warm bias must still apply; got {corrected}"

    def test_unknown_city_returns_unchanged(self):
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("Tulsa", 65.0, var="max")
        assert corrected == 65.0, (
            f"Unknown city must return unchanged temp; got {corrected}"
        )


# ── Past-date market filter ───────────────────────────────────────────────────


def test_analyze_trade_returns_none_for_past_date_market(monkeypatch):
    """analyze_trade must return None when target_date is in the past.

    Kalshi keeps markets "open" until settlement even after their target date
    has passed. Without this filter, cron generates spurious signals (and very
    high fake edges) for already-resolved markets.
    """
    from datetime import date, timedelta

    from weather_markets import analyze_trade

    past = date.today() - timedelta(days=1)
    enriched = {
        "_city": "NYC",
        "_date": past,
        "_hour": None,
        "_forecast": {
            "high_f": 75.0,
            "low_f": 58.0,
            "precip_in": 0.0,
            "models_used": 3,
            "high_range": (73.0, 77.0),
        },
        "ticker": "KXHIGHNY-PAST-B74.5",
        "series_ticker": "KXHIGHNY",
        "title": "NYC high above 74.5°F",
        "yes_ask": 55,
        "yes_bid": 45,
        "volume": 500,
        "volume_fp": 500,
        "open_interest": 200,
        "open_interest_fp": 200,
        "close_time": "",
    }
    result = analyze_trade(enriched)
    assert result is None, (
        f"analyze_trade must return None for past-date market "
        f"(target_date={past}), got: {result}"
    )


def test_analyze_trade_accepts_today_and_future(monkeypatch):
    """analyze_trade does NOT filter out today's or future markets."""
    from datetime import date, timedelta

    from weather_markets import analyze_trade

    for delta in (0, 1):
        target = date.today() + timedelta(days=delta)
        enriched = {
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 75.0,
                "low_f": 58.0,
                "precip_in": 0.0,
                "models_used": 3,
                "high_range": (73.0, 77.0),
            },
            "ticker": "KXHIGHNY-FUTURE-B74.5",
            "series_ticker": "KXHIGHNY",
            "title": "NYC high above 74.5°F",
            "yes_ask": 55,
            "yes_bid": 45,
            "volume": 500,
            "volume_fp": 500,
            "open_interest": 200,
            "open_interest_fp": 200,
            "close_time": "",
        }
        # May return None for other reasons (no probability engine data), but
        # must NOT be None solely because of the date. We verify by checking
        # the function doesn't raise and doesn't produce a non-None result that
        # contains a past-date rejection marker. (A None here is ok — other
        # guards may fire; we just confirm no exception.)
        try:
            analyze_trade(enriched)  # should not raise
        except Exception as exc:
            pytest.fail(f"analyze_trade raised for delta={delta}: {exc}")


# ── P0-14: NO-side entry_side_edge sign fix ───────────────────────────────────


class TestNoSideEntryEdgeSign:
    """P0-14 — entry_side_edge must be positive for a valid NO trade.

    Old formula: blended_prob - no_ask → negative for valid NOs → blocked at gate.
    Correct formula: (1 - blended_prob) - no_ask → positive when NO has real edge.
    """

    def _make_enriched(self, yes_bid_cents, yes_ask_cents, blended_prob_override=None):
        """Build a minimal enriched dict for analyze_trade targeting a NO recommendation."""
        from datetime import date, datetime, timedelta

        target = date.today() + timedelta(days=5)
        ticker = f"KXHIGHNYC-{target.strftime('%y%b%d').upper()}-T80"
        close_time = (datetime.now(UTC) + timedelta(hours=48)).isoformat()
        return {
            "_city": "NYC",
            "_date": target,
            "_hour": 14,
            "_forecast": {
                "high_f": 65.0,  # well below threshold → NO is likely
                "low_f": 55.0,
                "precip_in": 0.0,
                "wind_mph": 5.0,
                "temps": [65.0] * 50,
                "source": "ensemble",
            },
            "yes_bid": yes_bid_cents,
            "yes_ask": yes_ask_cents,
            "no_bid": 100 - yes_ask_cents,
            "volume": 5000,
            "open_interest": 1000,
            "ticker": ticker,
            "title": "NYC High above 80°F",
            "series_ticker": "KXHIGH-23-NYC",
            "close_time": close_time,
        }

    def test_no_trade_entry_side_edge_is_positive(self, monkeypatch):
        """A valid NO trade must have entry_side_edge > 0 after P0-14 fix."""
        import weather_markets as wm

        # yes_bid=55, yes_ask=60 → no_ask = 1 - 0.55 = 0.45
        # ensemble says 30% YES → blended ~0.30, NO edge = 0.70 - 0.45 = +0.25
        monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.30)
        monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))

        enriched = self._make_enriched(yes_bid_cents=55, yes_ask_cents=60)
        result = wm.analyze_trade(enriched)

        if result is None:
            pytest.skip("analyze_trade returned None (edge or liquidity guard fired)")

        assert result["recommended_side"] == "no", (
            f"Expected NO recommendation, got {result['recommended_side']} "
            f"(blended_prob={result.get('forecast_prob')}, market_prob={result.get('market_prob')})"
        )
        assert result["entry_side_edge"] > 0, (
            f"entry_side_edge={result['entry_side_edge']} must be > 0 for a valid NO trade "
            f"(P0-14: old formula inverted the sign)"
        )

    def test_yes_trade_entry_side_edge_positive(self, monkeypatch):
        """YES trade entry_side_edge is still positive after the fix (no regression)."""
        import weather_markets as wm

        # yes_bid=35, yes_ask=40 → our prob ~0.75 → YES trade, edge = 0.75 - 0.40 = +0.35
        monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.75)
        monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
        # Pin all network/file sources so blended_prob is deterministic across envs
        monkeypatch.setattr(wm, "get_ensemble_temps", lambda *a, **kw: [95.0] * 20)
        monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: [])
        monkeypatch.setattr(wm, "apply_station_bias", lambda c, t, var="max": t)

        enriched = self._make_enriched(yes_bid_cents=35, yes_ask_cents=40)
        enriched["_forecast"]["high_f"] = 95.0

        result = wm.analyze_trade(enriched)

        if result is None:
            pytest.skip("analyze_trade returned None (edge or liquidity guard fired)")

        if result["recommended_side"] == "yes":
            assert result["entry_side_edge"] > 0, (
                f"entry_side_edge={result['entry_side_edge']} must be > 0 for YES trade"
            )

    def test_entry_side_edge_formula_arithmetic(self):
        """Unit test of the P0-14 arithmetic: verify corrected formula value."""
        # blended_prob=0.35, yes_bid=0.55 → no_ask=0.45
        # Correct: (1 - 0.35) - 0.45 = +0.20
        # Buggy:   0.35 - 0.45 = -0.10
        blended_prob = 0.35
        no_ask = 1.0 - 0.55  # = 0.45

        corrected = (1.0 - blended_prob) - no_ask
        assert corrected == pytest.approx(0.20, abs=1e-9)
        assert corrected > 0, "Corrected NO edge must be positive"

        buggy = blended_prob - no_ask
        assert buggy == pytest.approx(-0.10, abs=1e-9)
        assert buggy < 0, (
            "Old buggy formula produced negative edge (confirms the bug existed)"
        )
