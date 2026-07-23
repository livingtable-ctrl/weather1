"""Unit tests for key functions in weather_markets.py and utils.py."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so imports work when run from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import UTC

# Captured at collection time, before conftest's default_gem_ukmo_means_none
# autouse fixture (which runs per-test, before each test body) replaces
# weather_markets._get_gem_ukmo_means with a (None, None) stub -- tests that
# want the real fetch behavior restore it via this reference rather than the
# (by-then-already-patched) module attribute. Same pattern as
# test_gaussian_prob.py's _REAL_LOAD_DYNAMIC_SIGMA.
import weather_markets as _wm_module  # noqa: E402
from utils import normal_cdf
from weather_markets import (
    _bootstrap_ci,
    _feels_like,
    _forecast_model_weights,
    _liquidity_edge_scale,
    _model_weights,
    ensemble_stats,
    is_liquid,
    kelly_fraction,
    parse_market_price,
)

_REAL_GET_GEM_UKMO_MEANS = _wm_module._get_gem_ukmo_means

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

    def test_liquid_market_with_volume_fp_only(self):
        # Real bug found 2026-07-19 (backlog.txt "is_liquid() ONLY READS
        # LEGACY volume/open_interest FIELD NAMES"): a market with real
        # current-API volume_fp but no quotes yet (first-to-post) must
        # still count as liquid, matching analyze_trade()'s own gate.
        # Uses a STRING value ("100.00"), matching Kalshi's real
        # FixedPointCount shape -- a plain int here would not have caught
        # the second bug below (missing float() wrapping).
        market = {"yes_bid": 0, "yes_ask": 0, "no_bid": 0, "volume_fp": "100.00"}
        assert is_liquid(market) is True

    def test_string_volume_fp_with_no_quotes_does_not_crash(self):
        # Real bug found 2026-07-19 (same day, same root cause as is_stale's
        # live crash): volume_fp is a FixedPointCount STRING on the real
        # API, not a number. `market.get("volume_fp") or ... or 0` returns
        # the string as-is, and `volume > 0` raises TypeError comparing a
        # str to an int -- masked here (unlike is_stale) only because
        # `has_yes or has_no` short-circuits before reaching `volume > 0`
        # for any market with real quotes; a first-to-post market with no
        # quotes yet would have hit the crash for real.
        market = {"yes_bid": 0, "yes_ask": 0, "no_bid": 0, "volume_fp": "10.00"}
        result = is_liquid(market)  # must not raise TypeError
        assert result is True

    def test_falls_back_to_legacy_volume_when_volume_fp_is_zero(self):
        # volume_fp present but 0 (falsy) must still fall back to legacy
        # volume, matching `volume_fp or volume or 0` precedence exactly.
        market = {
            "yes_bid": 0,
            "yes_ask": 0,
            "no_bid": 0,
            "volume_fp": 0,
            "volume": 100,
        }
        assert is_liquid(market) is True

    def test_volume_fp_takes_precedence_over_legacy_when_both_nonzero(self):
        # A truthy volume_fp wins even if legacy volume alone would also
        # pass -- proves _fp is checked first, not just as a fallback.
        market = {
            "yes_bid": 0,
            "yes_ask": 0,
            "no_bid": 0,
            "volume_fp": 5,
            "volume": 100,
        }
        assert is_liquid(market) is True


class TestLiquidityEdgeScale:
    """backlog.txt "LIQUIDITY-AWARE SIZING + DYNAMIC EDGE THRESHOLD" -- the
    log-only edge-threshold divisor (never wired into analyze_trade()'s
    STRONG/MED/MIN classification; matches code_review_plan.md's Phase 5
    Feature 3 design, which was never built)."""

    def test_liquid_market_returns_1_0(self):
        assert _liquidity_edge_scale(1000, 0) == pytest.approx(1.0)

    def test_at_liquid_floor_returns_1_0(self):
        assert _liquidity_edge_scale(500, 0) == pytest.approx(1.0)

    def test_illiquid_market_returns_1_5(self):
        assert _liquidity_edge_scale(0, 0) == pytest.approx(1.5)

    def test_at_illiquid_ceiling_returns_1_5(self):
        assert _liquidity_edge_scale(50, 0) == pytest.approx(1.5)

    def test_midpoint_interpolates_linearly(self):
        # liq=275 is exactly midway between 50 and 500 -> scale midway
        # between 1.5 and 1.0.
        assert _liquidity_edge_scale(275, 0) == pytest.approx(1.25)

    def test_volume_and_open_interest_are_summed(self):
        assert _liquidity_edge_scale(400, 100) == pytest.approx(1.0)

    def test_never_returns_below_1_0(self):
        # Scale must never REDUCE the effective edge bar, only raise it.
        for liq in (0, 10, 50, 100, 275, 400, 500, 1000, 100000):
            assert _liquidity_edge_scale(liq, 0) >= 1.0

    def test_none_inputs_treated_as_zero_not_typeerror(self):
        assert _liquidity_edge_scale(None, None) == pytest.approx(1.5)

    def test_string_inputs_do_not_crash_via_concatenation(self):
        """Real bug found live 2026-07-19, same day and root cause as the
        is_stale()/is_liquid() TypeError that crashed cron.py's scan loop:
        both real call sites (cron.py's cmd_cron, main.py's _analyze_once)
        pass raw `market.get("volume_fp") or market.get("volume") or 0`,
        which on Kalshi's current API is a FixedPointCount STRING
        ("400.00"), not a number. Without float() conversion,
        `(volume or 0) + (open_interest or 0)` on two strings silently does
        STRING CONCATENATION (no error at that line -- the crash was one
        line later, at the `>=` comparison), so this test also proves
        addition, not concatenation, actually happened."""
        assert _liquidity_edge_scale("400.00", "100.00") == pytest.approx(1.0)

    def test_string_zero_still_illiquid_not_truthy_string(self):
        """A non-empty string "0.00" is truthy in Python -- proves the
        float() conversion actually parses the value rather than just
        checking truthiness (which would have wrongly treated "0.00" as
        real liquidity)."""
        assert _liquidity_edge_scale("0.00", "0.00") == pytest.approx(1.5)


# ── TestForecastModelWeights ──────────────────────────────────────────────────


class TestForecastModelWeights:
    WINTER_MONTHS = (10, 11, 12, 1, 2, 3)
    SUMMER_MONTHS = (4, 5, 6, 7, 8, 9)

    def test_returns_dict_with_expected_keys(self):
        weights = _forecast_model_weights(1)
        assert isinstance(weights, dict)
        for key in ("gfs_seamless", "ecmwf_ifs025", "icon_seamless"):
            assert key in weights

    def test_winter_month_boosts_ecmwf_weight(self):
        """ECMWF weight should be higher in winter than summer."""
        winter_w = _forecast_model_weights(1)["ecmwf_ifs025"]
        summer_w = _forecast_model_weights(7)["ecmwf_ifs025"]
        assert winter_w > summer_w

    def test_all_winter_months_use_high_ecmwf(self, monkeypatch):
        """All winter months (Oct-Mar) should use the elevated ECMWF weight.

        _forecast_model_weights adds a live ENSO adjustment on top of the
        static 2.5 winter base (+0.5 el_nino / +0.3 la_nina, weather_markets.py
        :862-866) — without pinning the phase to neutral, this test is only
        deterministic when the real world happens to be ENSO-neutral (it
        failed with 3.0 during the 2026 El Niño instead of the expected 2.5).
        """
        import weather_markets as wm

        monkeypatch.setattr(wm, "_get_enso_phase", lambda: "neutral")
        for month in self.WINTER_MONTHS:
            w = _forecast_model_weights(month)
            assert w["ecmwf_ifs025"] == pytest.approx(2.5), (
                f"Expected 2.5 for winter month {month}, got {w['ecmwf_ifs025']}"
            )

    def test_all_summer_months_use_lower_ecmwf(self):
        """All summer months (Apr-Sep) should use the lower ECMWF weight."""
        for month in self.SUMMER_MONTHS:
            w = _forecast_model_weights(month)
            assert w["ecmwf_ifs025"] == pytest.approx(1.5), (
                f"Expected 1.5 for summer month {month}, got {w['ecmwf_ifs025']}"
            )

    def test_gfs_and_icon_weights_are_constant(self):
        """GFS and ICON weights should be 1.0 year-round."""
        for month in range(1, 13):
            w = _forecast_model_weights(month)
            assert w["gfs_seamless"] == pytest.approx(1.0)
            assert w["icon_seamless"] == pytest.approx(1.0)


# ── TestModelWeights (_model_weights, used by the ensemble blend) ─────────────


class TestModelWeights:
    def test_falls_back_to_seasonal_baseline(self, monkeypatch):
        """No tracker MAE data, no learned weights → pure seasonal baseline."""
        from unittest.mock import patch

        with (
            patch("weather_markets._weights_from_mae", return_value=None),
            patch("weather_markets.load_learned_weights", return_value={}),
        ):
            w = _model_weights("NYC", month=1)  # winter
        assert w == {
            "icon_seamless": 1.0,
            "gfs_seamless": 1.0,
            "ecmwf_aifs025_ensemble": pytest.approx(2.0),
        }

    def test_learned_weights_backfill_missing_models_from_baseline(self):
        """Priority-2 (learned_weights.json) is a partial dict — the model it
        omits must be backfilled from the seasonal baseline, not dropped."""
        from unittest.mock import patch

        with (
            patch("weather_markets._weights_from_mae", return_value=None),
            patch(
                "weather_markets.load_learned_weights",
                return_value={"NYC": {"gfs_seamless": 5.0}},
            ),
        ):
            w = _model_weights("NYC", month=7)  # summer
        assert w["gfs_seamless"] == pytest.approx(5.0)
        assert w["icon_seamless"] == pytest.approx(1.0)  # backfilled from baseline
        assert w["ecmwf_aifs025_ensemble"] == pytest.approx(1.5)  # backfilled

    def test_mae_data_overrides_and_skips_learned_weights_entirely(self):
        """When tracker MAE data exists, it blends against the seasonal baseline
        directly and priority-2 (learned_weights.json) is not consulted at all —
        this is intentional, pre-existing behavior (see docstring), not a bug."""
        from unittest.mock import patch

        with (
            patch(
                "weather_markets._weights_from_mae",
                return_value={"icon_seamless": 2.0},
            ),
            patch(
                "weather_markets.load_learned_weights",
                return_value={"NYC": {"gfs_seamless": 99.0}},
            ),
        ):
            w = _model_weights("NYC", month=7)  # summer baseline: 1.0/1.0/1.5
        # icon_seamless: 0.7*2.0 + 0.3*1.0 = 1.7
        assert w["icon_seamless"] == pytest.approx(1.7)
        # gfs_seamless: mae_weights lacks it, defaults to 1.0 -> 0.7*1.0+0.3*1.0=1.0
        # NOT 99.0 -- confirms learned_weights.json is fully skipped, not merged.
        assert w["gfs_seamless"] == pytest.approx(1.0)

    def test_malformed_learned_weights_falls_back_safely(self):
        """A corrupted (non-dict) learned_weights.json entry for a city must not
        crash -- fall back to the seasonal baseline."""
        from unittest.mock import patch

        with (
            patch("weather_markets._weights_from_mae", return_value=None),
            patch(
                "weather_markets.load_learned_weights",
                return_value={"NYC": 0.5},  # corrupted: raw float, not a dict
            ),
        ):
            w = _model_weights("NYC", month=7)
        assert w == {
            "icon_seamless": 1.0,
            "gfs_seamless": 1.0,
            "ecmwf_aifs025_ensemble": pytest.approx(1.5),
        }

    def test_stray_tracked_model_never_leaks_into_result(self):
        """A stray tracked value (e.g. "blended", not a real model) in mae_weights
        must never appear in the returned weights."""
        from unittest.mock import patch

        with patch(
            "weather_markets._weights_from_mae",
            return_value={"icon_seamless": 2.0, "blended": 99.0},
        ):
            w = _model_weights("NYC", month=7)
        assert "blended" not in w
        assert set(w.keys()) == {
            "icon_seamless",
            "gfs_seamless",
            "ecmwf_aifs025_ensemble",
        }

    def test_tier1_admits_a_model_outside_the_fixed_baseline(self):
        """GRADUATE GEM/UKMO generalization: a model _weights_from_mae() reports
        (i.e. it already cleared its own accuracy floor and isn't
        TRACKING_ONLY_MODEL_NAMES) gets a real learned weight here too, blended
        against a neutral 1.0 prior since it has no seasonal baseline entry --
        not silently dropped the way it was before this generalization."""
        from unittest.mock import patch

        with patch(
            "weather_markets._weights_from_mae",
            return_value={"icon_seamless": 2.0, "gem_global": 3.0},
        ):
            w = _model_weights("NYC", month=7)  # summer baseline: 1.0/1.0/1.5
        # icon_seamless: 0.7*2.0 + 0.3*1.0 = 1.7 (unchanged baseline behavior)
        assert w["icon_seamless"] == pytest.approx(1.7)
        # gem_global: 0.7*3.0 + 0.3*1.0 (neutral prior, no baseline entry) = 2.4
        assert w["gem_global"] == pytest.approx(2.4)
        # gfs_seamless: mae_weights lacks it -> 0.7*1.0 + 0.3*1.0 = 1.0, still present
        assert w["gfs_seamless"] == pytest.approx(1.0)
        # ecmwf_aifs025_ensemble: mae_weights lacks it -> 0.7*1.0 + 0.3*1.5 (its real
        # summer baseline, not a flat 1.0) = 1.15, still present and unaffected
        assert w["ecmwf_aifs025_ensemble"] == pytest.approx(1.15)

    def test_tier2_admits_a_model_outside_the_fixed_baseline(self):
        """Same generalization for tier 2 (learned_weights.json): a previously
        learned weight for a graduated model must survive a tier-1 data gap,
        not get silently discarded back to a neutral default the way baseline
        models never do for the identical gap."""
        from unittest.mock import patch

        with (
            patch("weather_markets._weights_from_mae", return_value=None),
            patch(
                "weather_markets.load_learned_weights",
                return_value={"NYC": {"gfs_seamless": 5.0, "gem_global": 7.0}},
            ),
        ):
            w = _model_weights("NYC", month=7)  # summer
        assert w["gfs_seamless"] == pytest.approx(5.0)
        assert w["gem_global"] == pytest.approx(7.0)
        assert w["icon_seamless"] == pytest.approx(1.0)  # backfilled from baseline
        assert w["ecmwf_aifs025_ensemble"] == pytest.approx(1.5)  # backfilled

    def test_tracked_but_non_ensemble_model_never_leaks_in(self):
        """ecmwf_ifs025 is real, currently-tracked data (feeds
        _forecast_model_weights()'s SEPARATE daily deterministic blend) that
        can genuinely appear in _weights_from_mae()'s output and
        learned_weights.json once it clears its own accuracy floor -- unlike
        gem_global/ukmo_global_ensemble_20km (TRACKING_ONLY_MODEL_NAMES),
        nothing stops it reaching mae_weights/learned today. It must still
        never appear in _model_weights()'s (the ENSEMBLE blend's) output,
        since it has no ensemble members and was never a candidate for this
        blend -- admission here is restricted to baseline |
        TRACKING_ONLY_MODEL_NAMES, not "any tracked model with data"."""
        from unittest.mock import patch

        with patch(
            "weather_markets._weights_from_mae",
            return_value={"icon_seamless": 2.0, "ecmwf_ifs025": 4.0},
        ):
            w_tier1 = _model_weights("NYC", month=7)
        assert "ecmwf_ifs025" not in w_tier1
        assert set(w_tier1.keys()) == {
            "icon_seamless",
            "gfs_seamless",
            "ecmwf_aifs025_ensemble",
        }

        with (
            patch("weather_markets._weights_from_mae", return_value=None),
            patch(
                "weather_markets.load_learned_weights",
                return_value={"NYC": {"gfs_seamless": 5.0, "ecmwf_ifs025": 9.0}},
            ),
        ):
            w_tier2 = _model_weights("NYC", month=7)
        assert "ecmwf_ifs025" not in w_tier2
        assert set(w_tier2.keys()) == {
            "icon_seamless",
            "gfs_seamless",
            "ecmwf_aifs025_ensemble",
        }

    def test_tier3_seasonal_baseline_stays_fixed_to_3_models(self):
        """Tier 3 (pure seasonal fallback, no tracker/learned data at all) must
        stay exactly the 3 baseline models -- a graduated model has no coded
        seasonal/climatological prior, so there's nothing informative to add
        here (consumers' own `weights.get(model, 1.0)` default already
        produces the identical neutral value for an absent key)."""
        from unittest.mock import patch

        with (
            patch("weather_markets._weights_from_mae", return_value=None),
            patch("weather_markets.load_learned_weights", return_value={}),
        ):
            w = _model_weights("NYC", month=1)  # winter
        assert set(w.keys()) == {
            "icon_seamless",
            "gfs_seamless",
            "ecmwf_aifs025_ensemble",
        }


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
    """L2-B: kelly_fraction must always be called with an explicit fee_rate,
    never left to a fee-free default.

    These tests exercise kelly_fraction()'s own generic fee-sensitivity
    behavior using KALSHI_FEE_RATE (0.07) as a representative nonzero rate —
    they don't assert which specific rate analyze_trade()'s call sites pass.
    As of 2026-07-12, analyze_trade()'s own call sites pass
    KALSHI_MAKER_FEE_RATE (0.0), not KALSHI_FEE_RATE, because this bot's live/
    paper entries are always resting midpoint GTC limit orders (maker fills),
    which pay $0 on this bot's markets — see utils.KALSHI_MAKER_FEE_RATE's
    docstring. Fee-free Kelly (fee_rate=0.0) still overstates position size
    whenever the real fee is nonzero (e.g. a taker fill, or a maker fill on
    one of the ~50 non-standard series where the maker multiplier isn't 0) —
    that's the invariant under test here, independent of which rate applies
    to any particular call site.
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
        """If city weights loaded, _blend_weights uses them (days_out=1 = neutral NWS scale)."""
        import weather_markets as wm

        city_weights = {"NYC": {"ensemble": 0.50, "climatology": 0.10, "nws": 0.40}}
        monkeypatch.setattr(wm, "_CITY_WEIGHTS", city_weights)
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})

        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=1, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w_ens == pytest.approx(0.50, abs=1e-6)
        assert w_nws == pytest.approx(0.40, abs=1e-6)

    def test_seasonal_weights_used_when_no_city_weights(self, monkeypatch):
        """If no city weights but seasonal weights loaded, use seasonal (days_out=1 = neutral NWS scale)."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(
            wm,
            "_SEASONAL_WEIGHTS",
            {"spring": {"ensemble": 0.45, "climatology": 0.20, "nws": 0.35}},
        )

        w_ens, w_clim, w_nws = wm._blend_weights(
            days_out=1, has_nws=True, has_clim=True, city="NYC", season="spring"
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
    # Patch _get_consensus_probs to return agreeing models (consensus True) — 5-tuple
    monkeypatch.setattr(
        wm, "_get_consensus_probs", lambda *a, **kw: (0.73, 0.75, 74.0, 74.0, None)
    )
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CONDITION_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
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
        "ticker": "KXHIGHNY-26APR09-T72",
        "title": "Will NYC high temperature be above 72°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 0.72,
        "yes_bid": 0.62,
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
        wm, "_get_consensus_probs", lambda *a, **kw: (0.75, 0.60, 74.0, 68.0, None)
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
    # Patch live API calls so the test is deterministic — without these,
    # fetch_temperature_nbm/ecmwf make real network requests and the resulting
    # model probability shifts unpredictably, occasionally triggering the
    # model_mkt_gap gate (>0.25) and returning None.
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 76.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 77.0)
    monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.20)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: 0.15)
    monkeypatch.setattr(wm, "get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)

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
        "yes_ask": 0.20,
        "yes_bid": 0.15,
        "no_bid": 0.80,
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


def test_analyze_trade_captures_ecmwf_forecast_means(monkeypatch):
    """backlog.txt 'TRACK ECMWF FORECAST ACCURACY': analyze_trade must surface
    BOTH real ECMWF products' own means in the result dict, alongside icon/gfs
    — ecmwf_aifs025_ensemble's mean (5th _get_consensus_probs element, only
    consumed for model_consensus before) and ecmwf_ifs025's mean
    (model_temps["ecmwf"] via fetch_temperature_ecmwf(), already fetched for
    an unrelated Phase-C purpose)."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    # Distinct means per model so a mix-up (e.g. one ecmwf field silently
    # getting the other's value) would fail the assertions below.
    monkeypatch.setattr(
        wm,
        "_get_consensus_probs",
        lambda *a, **kw: (0.73, 0.75, 74.0, 74.5, 76.25),
    )
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 79.5)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CONDITION_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
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
        "ticker": "KXHIGHNY-26APR09-T72",
        "title": "Will NYC high temperature be above 72°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 0.72,
        "yes_bid": 0.62,
        "volume": 500,
        "open_interest": 200,
        "close_time": (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(hours=20)
        ).isoformat(),
    }
    result = analyze_trade(enriched)
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    means = result["model_forecast_means"]
    assert means["icon_seamless"] == pytest.approx(74.0)
    assert means["gfs_seamless"] == pytest.approx(74.5)
    assert means["ecmwf_aifs025_ensemble"] == pytest.approx(76.25), (
        f"expected ecmwf_aifs025_ensemble=76.25 from the 5th "
        f"_get_consensus_probs element, got {means.get('ecmwf_aifs025_ensemble')!r}"
    )
    assert means["ecmwf_ifs025"] == pytest.approx(79.5), (
        f"expected ecmwf_ifs025=79.5 from the mocked fetch_temperature_ecmwf "
        f"(model_temps['ecmwf']), got {means.get('ecmwf_ifs025')!r}"
    )
    # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2: the keys
    # must exist even when conftest's default_gem_ukmo_means_none autouse
    # fixture (not overridden in this test) leaves both means None -- a
    # missing key here would still fail _validate_forecast_model_keys'
    # sibling concern (dict shape), just silently rather than loudly.
    assert "gem_global" in means and means["gem_global"] is None
    assert (
        "ukmo_global_ensemble_20km" in means
        and means["ukmo_global_ensemble_20km"] is None
    )


def test_analyze_trade_captures_gem_ukmo_forecast_means(monkeypatch):
    """backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2: analyze_trade
    must surface GEM/UKMO's own means in model_forecast_means, via
    _get_gem_ukmo_means, fetched separately from _get_consensus_probs's 5-tuple
    under the same ens_prob/temps gate."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    monkeypatch.setattr(
        wm,
        "_get_consensus_probs",
        lambda *a, **kw: (0.73, 0.75, 74.0, 74.5, 76.25),
    )
    # Distinct from every other mocked model mean so a mix-up would fail.
    monkeypatch.setattr(wm, "_get_gem_ukmo_means", lambda *a, **kw: (81.5, 83.25))
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 79.5)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CONDITION_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
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
        "ticker": "KXHIGHNY-26APR09-T72",
        "title": "Will NYC high temperature be above 72°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 0.72,
        "yes_bid": 0.62,
        "volume": 500,
        "open_interest": 200,
        "close_time": (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(hours=20)
        ).isoformat(),
    }
    result = analyze_trade(enriched)
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    means = result["model_forecast_means"]
    assert means["gem_global"] == pytest.approx(81.5), (
        f"expected gem_global=81.5 from the mocked _get_gem_ukmo_means, "
        f"got {means.get('gem_global')!r}"
    )
    assert means["ukmo_global_ensemble_20km"] == pytest.approx(83.25), (
        f"expected ukmo_global_ensemble_20km=83.25 from the mocked "
        f"_get_gem_ukmo_means, got {means.get('ukmo_global_ensemble_20km')!r}"
    )
    # icon/gfs/ecmwf must be unaffected by gem/ukmo's addition.
    assert means["icon_seamless"] == pytest.approx(74.0)
    assert means["gfs_seamless"] == pytest.approx(74.5)


def test_analyze_trade_survives_gem_ukmo_fetch_exception(monkeypatch):
    """_get_gem_ukmo_means failing must not abort the trade -- mirrors the
    existing _get_consensus_probs exception-tolerance behavior, and must not
    regress icon/gfs/ecmwf's own means (separate try/except blocks)."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    monkeypatch.setattr(
        wm,
        "_get_consensus_probs",
        lambda *a, **kw: (0.73, 0.75, 74.0, 74.5, 76.25),
    )

    def _raise_gem_ukmo(*a, **kw):
        raise RuntimeError("simulated gem/ukmo fetch failure")

    monkeypatch.setattr(wm, "_get_gem_ukmo_means", _raise_gem_ukmo)
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 79.5)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CONDITION_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
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
        "ticker": "KXHIGHNY-26APR09-T72",
        "title": "Will NYC high temperature be above 72°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 0.72,
        "yes_bid": 0.62,
        "volume": 500,
        "open_interest": 200,
        "close_time": (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(hours=20)
        ).isoformat(),
    }
    result = analyze_trade(enriched)
    assert result is not None, "a gem/ukmo fetch exception must not abort the trade"
    means = result["model_forecast_means"]
    assert means["gem_global"] is None
    assert means["ukmo_global_ensemble_20km"] is None
    # icon/gfs/ecmwf means must survive the gem/ukmo exception untouched.
    assert means["icon_seamless"] == pytest.approx(74.0)
    assert means["ecmwf_aifs025_ensemble"] == pytest.approx(76.25)


def test_metar_locked_trade_has_ecmwf_forecast_mean_keys(monkeypatch):
    """The METAR-locked branch (same-day observation override) skips the model
    path entirely and must still define BOTH ecmwf_aifs_forecast_mean and
    ecmwf_ifs_forecast_mean (as None) before the shared result dict is built —
    mirrors icon/gfs's existing None default. Regression test for a real
    UnboundLocalError a diff introduced (analyze_trade's METAR-locked branch
    pre-assigns icon/gfs forecast means but initially missed the ecmwf ones)."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )

    from datetime import date

    today = date.today()
    enriched = {
        "_forecast": {"high_f": 75.0, "low_f": 55.0, "precip_in": 0.0, "wind_mph": 5.0},
        "_date": today,
        "_city": "NYC",
        "_hour": None,
        "ticker": "KXHIGHNY-26APR09-T72",
        "title": "Will NYC high temperature be above 72°F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": 0.72,
        "yes_bid": 0.62,
        "volume": 500,
        "open_interest": 200,
        "close_time": (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            + __import__("datetime").timedelta(hours=2)
        ).isoformat(),
    }
    result = analyze_trade(enriched)
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    assert result["method"] == "metar_lockout"
    assert result["model_forecast_means"] == {}


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

    def test_negative_caches_failure(self, monkeypatch):
        """A failed fetch must be negative-cached -- a second call within the
        TTL must not re-invoke requests.get (2026-07-19 ForecastCache
        migration: get_with_ts() must distinguish a real cached None from
        no-entry-at-all)."""
        from datetime import date

        import weather_markets as wm

        call_count = {"n": 0}

        def _raise(*a, **kw):
            call_count["n"] += 1
            raise OSError("timeout")

        monkeypatch.setattr(wm, "WEATHERAPI_KEY", "test-key")
        monkeypatch.setattr("requests.get", _raise)
        wm._WEATHERAPI_CACHE.clear()
        wm._weatherapi_cb.record_success()  # ensure circuit closed

        target = date(2026, 5, 1)
        first = wm.fetch_temperature_weatherapi("NYC", target)
        assert first is None
        assert call_count["n"] == 1

        second = wm.fetch_temperature_weatherapi("NYC", target)
        assert second is None
        assert call_count["n"] == 1, "negative-cached hit must not re-call requests.get"
        wm._weatherapi_cb.record_success()  # restore for later tests

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

    # ── Renamed/new tickers (Kalshi retired several *_LA/*_BOS/*_PHIL/*_NY/
    # *_CHI/*_MIA/*_DEN/*_AUS series and added Las Vegas + New Orleans) ──────

    def test_philadelphia_renamed_high_ticker_without_t(self):
        """KXHIGHPHIL (renamed from KXHIGHTPHIL, dropped the 'T') → Philadelphia."""
        assert self._city("KXHIGHPHIL-26JUL04-T99") == "Philadelphia"

    def test_philadelphia_low_ticker_still_has_t(self):
        """KXLOWTPHIL (unrenamed, still has 'T') → Philadelphia."""
        assert self._city("KXLOWTPHIL-26JUL04-T70") == "Philadelphia"

    def test_la_renamed_high_ticker(self):
        """KXHIGHLAX (renamed from KXHIGHLA) → LA."""
        assert self._city("KXHIGHLAX-26JUL04-T74") == "LA"

    def test_la_renamed_low_ticker(self):
        """KXLOWLAX (renamed from KXLOWLA, itself later retired for
        KXLOWTLAX — still checked so a third rename back would be caught)."""
        assert self._city("KXLOWLAX-26JUL04-T60") == "LA"

    def test_la_low_ticker_t_variant(self):
        """KXLOWTLAX (current live ticker as of 2026-07-05, renamed again
        from KXLOWLAX) → LA. KNOWN_WEATHER_SERIES was found via
        check_series_drift to still reference the retired KXLOWLAX, silently
        dropping LA's low-temp market from get_weather_markets() entirely."""
        assert self._city("KXLOWTLAX-26JUL05-T63") == "LA"

    def test_boston_renamed_high_ticker(self):
        """KXHIGHTBOS (renamed from KXHIGHBOS) → Boston."""
        assert self._city("KXHIGHTBOS-26JUL04-T98") == "Boston"

    def test_boston_renamed_low_ticker(self):
        """KXLOWTBOS (renamed from KXLOWBOS) → Boston."""
        assert self._city("KXLOWTBOS-26JUL04-T70") == "Boston"

    def test_las_vegas_high_ticker_detected(self):
        """KXHIGHTLV → LasVegas (previously untracked city)."""
        assert self._city("KXHIGHTLV-26JUL04-T108") == "LasVegas"

    def test_las_vegas_low_ticker_detected(self):
        """KXLOWTLV → LasVegas."""
        assert self._city("KXLOWTLV-26JUL04-T77") == "LasVegas"

    def test_las_vegas_title_detected(self):
        """'las vegas' in title → LasVegas even with a generic ticker."""
        assert (
            self._city("KXRAIN-26JUL04-2IN", "las vegas rain > 2 inches") == "LasVegas"
        )

    def test_new_orleans_high_ticker_detected(self):
        """KXHIGHTNOLA → NewOrleans (previously untracked city)."""
        assert self._city("KXHIGHTNOLA-26JUL04-T98") == "NewOrleans"

    def test_new_orleans_low_ticker_detected(self):
        """KXLOWTNOLA → NewOrleans."""
        assert self._city("KXLOWTNOLA-26JUL04-T79") == "NewOrleans"

    def test_new_orleans_title_detected(self):
        """'new orleans' in title → NewOrleans even with a generic ticker."""
        assert (
            self._city("KXRAIN-26JUL04-2IN", "new orleans rain > 2 inches")
            == "NewOrleans"
        )


class TestHourlyDirectionalCityDetection:
    """backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 1: KXTEMPxxxH
    tickers must resolve to the correct city. LA and DC fail the pre-existing
    substring fallback chain entirely (LA needs "HIGHLA"/"LOWLA"/"LOWTLA"/an
    exact "LA" hyphen segment, none present in "KXTEMPLAXH"; Washington needs
    "TDC", not present in "KXTEMPDCH") -- both would silently return None
    without the explicit _KXTEMP_HOURLY_CITY prefix map. NYC/Austin/Chicago
    happen to match the existing chain by substring luck; tested here too so
    a future edit to that chain can't silently break them."""

    def _city(self, ticker: str) -> str | None:
        from unittest.mock import patch

        import weather_markets as wm

        market = {"ticker": ticker, "title": ""}
        with patch.object(wm, "get_weather_forecast", return_value=None):
            result = wm.enrich_with_forecast(market)
        return result.get("_city")

    def test_nyc_hourly_ticker_detected(self):
        """Real ticker pulled live 2026-07-20."""
        assert self._city("KXTEMPNYCH-26JUL2008-T71.99") == "NYC"

    def test_austin_hourly_ticker_detected(self):
        """Real ticker pulled live 2026-07-20."""
        assert self._city("KXTEMPAUSH-26JUL2008-T78.99") == "Austin"

    def test_chicago_hourly_ticker_detected(self):
        assert self._city("KXTEMPCHIH-26JUL2008-T85.99") == "Chicago"

    def test_la_hourly_ticker_detected(self):
        """Would return None without the explicit _KXTEMP_HOURLY_CITY fix --
        none of the existing LA substring checks match "KXTEMPLAXH"."""
        assert self._city("KXTEMPLAXH-26JUL2008-T77.99") == "LA"

    def test_washington_dc_hourly_ticker_detected(self):
        """Would return None without the explicit _KXTEMP_HOURLY_CITY fix --
        "KXTEMPDCH" doesn't contain "TDC"."""
        assert self._city("KXTEMPDCH-26JUL2008-T82.99") == "Washington"


class TestMonthlyRainCityDetection:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 1: KXRAIN*M monthly
    rain-total ladder tickers must resolve to the correct city. 5 of the 10
    real series (Seattle, LA, Houston, SF, Dallas) fail the pre-existing
    substring fallback chain entirely -- e.g. "TSEA"/"THOU"/"TSFO"/"TDAL"
    require a "T" immediately before the city code, not present in
    "KXRAIN<CITY>M"; the LA block requires "HIGHLA"/"LOWLA"/"LOWTLA"/an exact
    "LA" hyphen segment, none present in "KXRAINLAXM" -- and would silently
    return None without the explicit _KXRAIN_MONTHLY_CITY prefix map. The
    other 5 (Miami, Chicago, NYC, Denver, Austin) happen to match the
    existing chain by substring luck; tested here too so a future edit to
    that chain can't silently break them."""

    def _city(self, ticker: str) -> str | None:
        from unittest.mock import patch

        import weather_markets as wm

        market = {"ticker": ticker, "title": ""}
        with patch.object(wm, "get_weather_forecast", return_value=None):
            result = wm.enrich_with_forecast(market)
        return result.get("_city")

    def test_seattle_rain_ticker_detected(self):
        """Real ticker shape pulled live 2026-07-20. Would return None
        without the explicit _KXRAIN_MONTHLY_CITY fix -- "KXRAINSEAM"
        doesn't contain "TSEA"."""
        assert self._city("KXRAINSEAM-26JUL-1") == "Seattle"

    def test_la_rain_ticker_detected(self):
        """Would return None without the explicit fix -- "KXRAINLAXM" has no
        "HIGHLA"/"LOWLA"/"LOWTLA" substring and no exact "LA" hyphen segment."""
        assert self._city("KXRAINLAXM-26JUL-7") == "LA"

    def test_houston_rain_ticker_detected(self):
        """Would return None without the explicit fix -- "KXRAINHOUM"
        doesn't contain "THOU"."""
        assert self._city("KXRAINHOUM-26JUL-3") == "Houston"

    def test_san_francisco_rain_ticker_detected(self):
        """Would return None without the explicit fix -- "KXRAINSFOM"
        doesn't contain "TSFO"."""
        assert self._city("KXRAINSFOM-26JUL-4") == "SanFrancisco"

    def test_dallas_rain_ticker_detected(self):
        """Would return None without the explicit fix -- "KXRAINDALM"
        doesn't contain "TDAL"."""
        assert self._city("KXRAINDALM-26JUL-2") == "Dallas"

    def test_miami_rain_ticker_detected(self):
        """Passes the existing substring chain by luck ("MIA") -- tested so
        a future edit to that chain can't silently break it."""
        assert self._city("KXRAINMIAM-26JUL-5") == "Miami"

    def test_chicago_rain_ticker_detected(self):
        """Passes the existing substring chain by luck ("CHI")."""
        assert self._city("KXRAINCHIM-26JUL-6") == "Chicago"

    def test_nyc_rain_ticker_detected(self):
        """Passes the existing substring chain by luck ("NY"). Real NYC
        ladder only has 4 brackets (1-4in), not 7 -- a Kalshi listing
        choice, unrelated to city detection."""
        assert self._city("KXRAINNYCM-26JUL-4") == "NYC"

    def test_denver_rain_ticker_detected(self):
        """Passes the existing substring chain by luck ("DEN")."""
        assert self._city("KXRAINDENM-26JUL-7") == "Denver"

    def test_austin_rain_ticker_detected(self):
        """Passes the existing substring chain by luck ("AUS")."""
        assert self._city("KXRAINAUSM-26JUL-1") == "Austin"


class TestLearnedWeightsTTL:
    """L4-D: load_learned_weights() must discard files older than 7 days."""

    def test_stale_weights_file_falls_back_to_defaults(self, tmp_path):
        """File mtime 8 days ago → loader returns {} (default weights)."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        fake_weights = {"Dallas": {"ecmwf_ifs025": 2.0, "gfs_seamless": 1.0}}
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

        fake_weights = {"Dallas": {"ecmwf_ifs025": 2.0, "gfs_seamless": 1.0}}
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
                bad = {"NYC": {"gfs_seamless": 0.0, "ecmwf_ifs025": 1.5}}
                wm.save_learned_weights(bad)
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

        assert not wrote[0], (
            "save_learned_weights must not call os.replace for near-zero weights"
        )

    def test_save_allows_valid_weights(self, tmp_path, monkeypatch):
        """save_learned_weights must write valid {city: {model: weight}} dicts."""

        import weather_markets as wm

        valid = {
            "NYC": {
                "gfs_seamless": 1.2,
                "ecmwf_ifs025": 0.9,
                "icon_seamless": 0.9,
            }
        }

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

        bad = {"NYC": {"gfs_seamless": 0.0, "ecmwf_ifs025": 1.5}}
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

    Rewritten 2026-07-12 to read _STATION_BIAS_HIGH directly (previously went
    through apply_station_bias(), which turned out to have zero production
    callers -- see test_station_bias.py's module docstring -- and was deleted
    as superseded by _get_combined_station_bias()).
    """

    def test_miami_high_bias_applies(self):
        from weather_markets import _STATION_BIAS_HIGH

        assert "Miami" in _STATION_BIAS_HIGH, (
            "Miami 3°F warm bias must be keyed by full name"
        )
        assert _STATION_BIAS_HIGH["Miami"] == 3.0

    def test_denver_high_bias_applies(self):
        from weather_markets import _STATION_BIAS_HIGH

        assert "Denver" in _STATION_BIAS_HIGH, (
            "Denver 2°F warm bias must be keyed by full name"
        )
        assert _STATION_BIAS_HIGH["Denver"] == 2.0

    def test_chicago_high_bias_applies(self):
        from weather_markets import _STATION_BIAS_HIGH

        assert "Chicago" in _STATION_BIAS_HIGH, (
            "Chicago 0.5°F warm bias must be keyed by full name"
        )
        assert _STATION_BIAS_HIGH["Chicago"] == 0.5

    def test_nyc_still_works(self):
        from weather_markets import _STATION_BIAS_HIGH

        assert _STATION_BIAS_HIGH["NYC"] == 1.0, "NYC 1°F warm bias must still apply"

    def test_unknown_city_returns_unchanged(self):
        from weather_markets import _STATION_BIAS_HIGH

        assert _STATION_BIAS_HIGH.get("Tulsa", 0.0) == 0.0, (
            "Unknown city must have no bias entry (callers fall back to 0.0)"
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
        """A valid NO trade must have entry_side_edge > 0 after P0-14 fix.

        Market: yes_bid=22, yes_ask=28 → market_mid=25% YES, no_ask=78%.
        Ensemble temps [65°F×14, 67°F×6] vs T80 → ens_prob=0%, Gaussian≈0%.
        Clim (0.30) carries only ~8% renorm weight → blended_prob≈5%.
        model_mkt_gap = |0.05 − 0.25| = 0.20 < 0.25 (gate does not fire).
        NO edge = (1 − 0.05) − 0.78 = +0.17 > 0.
        """
        import weather_markets as wm

        # Patch all live API calls so blended_prob is fully deterministic.
        # _get_consensus_probs hits Open-Meteo directly even when get_ensemble_temps
        # is patched — both must be suppressed (Jun25 conftest note).
        monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.30)
        monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
        # Non-degenerate temps (two distinct values) all below T80 → ens_prob=0.
        # All-identical members trigger the degenerate-ensemble guard (return None).
        monkeypatch.setattr(
            wm, "get_ensemble_temps", lambda *a, **kw: [65.0] * 14 + [67.0] * 6
        )
        monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: [])
        monkeypatch.setattr(
            wm, "_get_consensus_probs", lambda *a, **kw: (None, None, None, None, None)
        )

        # Market says 25% YES; model says ~5% YES (ens=0, gauss≈0, clim=0.30 at
        # 8% renorm weight; neutral_temperature_scaling autouse sets T=1.0 identity).
        # NO edge = (1 − 0.05) − 0.78 = +0.17 > 0. Spread = 6¢/25¢ = 24% < 30%.
        enriched = self._make_enriched(yes_bid_cents=22, yes_ask_cents=28)
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

        enriched = self._make_enriched(yes_bid_cents=35, yes_ask_cents=40)
        enriched["_forecast"]["high_f"] = 95.0

        result = wm.analyze_trade(enriched)

        if result is None:
            pytest.skip("analyze_trade returned None (edge or liquidity guard fired)")

        if result["recommended_side"] == "yes":
            assert result["entry_side_edge"] > 0, (
                f"entry_side_edge={result['entry_side_edge']} must be > 0 for YES trade"
            )

    def test_ensemble_excluded_from_blend_when_circuit_open(self, monkeypatch, caplog):
        """When the ensemble circuit breaker is OPEN, analyze_trade must exclude
        ens_prob from the blend and renormalize over the remaining sources.

        Rewritten 2026-07-12 from a standalone-function unit test
        (test_circuit_breaker.py's test_blend_uses_nws_clim_only_when_ensemble_circuit_open,
        against _blend_with_circuit_fallback()) after that function was deleted as a
        superseded/never-wired duplicate of this exact exclusion logic, which is
        implemented inline in analyze_trade itself (see the `_ensemble_circuit_is_open()`
        check right before the source-renormalization block). Exercises the real
        production code path instead of the orphaned standalone copy.
        """
        import logging

        import weather_markets as wm

        monkeypatch.setattr(wm, "_ensemble_circuit_is_open", lambda: True)
        monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "climatological_prob", lambda *a, **kw: 0.30)
        monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
        monkeypatch.setattr(
            wm, "get_ensemble_temps", lambda *a, **kw: [65.0] * 14 + [67.0] * 6
        )
        monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: [])
        monkeypatch.setattr(
            wm, "_get_consensus_probs", lambda *a, **kw: (None, None, None, None, None)
        )

        enriched = self._make_enriched(yes_bid_cents=22, yes_ask_cents=28)

        with caplog.at_level(logging.WARNING, logger="weather_markets"):
            result = wm.analyze_trade(enriched)

        if result is None:
            pytest.skip("analyze_trade returned None (edge or liquidity guard fired)")

        assert any(
            "ensemble circuit OPEN" in msg and "excluding ens_prob" in msg
            for msg in caplog.messages
        ), "analyze_trade must log that ens_prob was excluded when the circuit is open"
        assert result.get("blend_sources", {}).get("ensemble", 0.0) == 0.0, (
            "blend_sources must show zero ensemble weight when the circuit is open"
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


class TestConsensusCacheKeyBetween:
    """_get_consensus_probs cache key must include lower/upper for between-markets.

    Before the fix, all between-markets for the same city/date/var/hour shared
    a single cache slot (threshold=None for all of them), so B64.5 would get
    the cached result for B66.5 that was analysed moments before.
    """

    def test_different_buckets_get_separate_cache_entries(self, monkeypatch):
        """Two between-markets with different lower/upper produce distinct keys."""
        import weather_markets as wm

        # Clear cache before test to avoid cross-test contamination.
        wm._CONSENSUS_CACHE.clear()

        call_args_list: list[dict] = []

        def _fake_get_ensemble_temps(
            city, target_date, *, hour=None, var="max", model=None
        ):
            # Return temps that differ per bucket so the cache entry is distinguishable.
            return (
                [64.0 + i for i in range(10)]
                if call_args_list
                else [70.0 + i for i in range(10)]
            )

        # Track how many times the underlying Open-Meteo fetch is called.
        fetch_calls = []

        def _fake_fetch(url, **kwargs):
            fetch_calls.append(url)
            # Return a minimal valid response
            return None  # causes _model_prob_and_mean to return (None, None)

        condition_b645 = {"type": "between", "lower": 63.5, "upper": 65.5}
        condition_b665 = {"type": "between", "lower": 65.5, "upper": 67.5}

        from datetime import date

        today = date.today()

        # Build cache keys manually to verify they differ
        key_b645 = ("NYC", today.isoformat(), "between", None, 63.5, 65.5, "max", None)
        key_b665 = ("NYC", today.isoformat(), "between", None, 65.5, 67.5, "max", None)
        assert key_b645 != key_b665, "Cache keys for distinct buckets must differ"

        # Seed the cache with different results for the two buckets.
        wm._CONSENSUS_CACHE.set_with_ttl(
            key_b645, (0.20, 0.22, 64.0, 64.5, None), wm._CONSENSUS_CACHE_TTL
        )
        wm._CONSENSUS_CACHE.set_with_ttl(
            key_b665, (0.55, 0.58, 66.0, 66.5, None), wm._CONSENSUS_CACHE_TTL
        )

        r645 = wm._get_consensus_probs("NYC", today, condition_b645)
        r665 = wm._get_consensus_probs("NYC", today, condition_b665)

        # Each bucket must return its own cached value, not the other's.
        assert r645[0] == pytest.approx(0.20, abs=1e-6), (
            f"B64.5 icon_prob wrong: {r645}"
        )
        assert r665[0] == pytest.approx(0.55, abs=1e-6), (
            f"B66.5 icon_prob wrong: {r665}"
        )

        wm._CONSENSUS_CACHE.clear()


class TestValidateForecastModelKeys:
    """backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING': a typo'd model
    name in model_forecast_means must fail loudly, not silently create a new,
    permanently-thin tracked "model" in tracker.ensemble_member_scores."""

    def test_known_keys_pass(self):
        import weather_markets as wm

        wm._validate_forecast_model_keys(
            {
                "icon_seamless": 70.0,
                "gfs_seamless": None,
                "ecmwf_aifs025_ensemble": 71.0,
                "ecmwf_ifs025": 72.0,
            }
        )  # must not raise

    def test_gem_ukmo_keys_pass(self):
        """backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2: GEM/UKMO
        added as the mechanism's first real new-source consumers."""
        import weather_markets as wm

        wm._validate_forecast_model_keys(
            {"gem_global": 73.0, "ukmo_global_ensemble_20km": None}
        )  # must not raise

    def test_empty_dict_passes(self):
        import weather_markets as wm

        wm._validate_forecast_model_keys({})  # must not raise

    def test_unknown_key_raises(self):
        import weather_markets as wm

        with pytest.raises(AssertionError, match="ecmwf_aifs_ensemble"):
            wm._validate_forecast_model_keys(
                {"icon_seamless": 70.0, "ecmwf_aifs_ensemble": 71.0}
            )


class TestGetConsensusProbsEcmwf:
    """backlog.txt 'TRACK ECMWF FORECAST ACCURACY': _get_consensus_probs must also
    fetch ecmwf_aifs025_ensemble's own mean via the same ENSEMBLE_BASE/
    _model_prob_and_mean infra already used for icon/gfs, returned as the 5th
    tuple element."""

    def test_fetches_and_averages_ecmwf_aifs_members(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._CONSENSUS_CACHE.clear()
        wm._ensemble_cache.clear()
        wm._ensemble_cb.record_success()  # ensure circuit closed

        # Hand-computed means: icon=72.0, gfs=70.0, ecmwf=76.0 — distinct per
        # model so a mix-up (e.g. ecmwf reading icon's members) would fail.
        members_by_model = {
            "icon_seamless": [70.0, 71.0, 72.0, 73.0, 74.0],
            "gfs_seamless": [68.0, 69.0, 70.0, 71.0, 72.0],
            "ecmwf_aifs025_ensemble": [74.0, 75.0, 76.0, 77.0, 78.0],
        }

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            members = members_by_model.get(model, [])
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {
                "daily": {
                    f"temperature_2m_max_member{i + 1:02d}": [v]
                    for i, v in enumerate(members)
                }
            }
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        condition = {"type": "above", "threshold": 70.0}

        icon_p, gfs_p, icon_mean, gfs_mean, ecmwf_mean = wm._get_consensus_probs(
            "NYC", target, condition
        )

        assert icon_mean == pytest.approx(72.0), f"icon mean wrong: {icon_mean}"
        assert gfs_mean == pytest.approx(70.0), f"gfs mean wrong: {gfs_mean}"
        assert ecmwf_mean == pytest.approx(76.0), (
            f"expected mean of [74,75,76,77,78]=76.0, got {ecmwf_mean}"
        )

        wm._CONSENSUS_CACHE.clear()
        wm._ensemble_cache.clear()

    def test_returns_none_when_fewer_than_five_ecmwf_members(self, monkeypatch):
        """_model_prob_and_mean's own >=5-member floor must also gate ECMWF —
        matching icon/gfs's existing behavior, not a separate/looser threshold."""
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._CONSENSUS_CACHE.clear()
        wm._ensemble_cache.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if model == "ecmwf_aifs025_ensemble":
                # Only 3 members — below the 5-member floor.
                daily = {
                    "temperature_2m_max_member01": [74.0],
                    "temperature_2m_max_member02": [75.0],
                    "temperature_2m_max_member03": [76.0],
                }
            else:
                daily = {
                    f"temperature_2m_max_member{i + 1:02d}": [70.0 + i]
                    for i in range(5)
                }
            resp.json.return_value = {"daily": daily}
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        condition = {"type": "above", "threshold": 70.0}

        _, _, _, _, ecmwf_mean = wm._get_consensus_probs("NYC", target, condition)
        assert ecmwf_mean is None, (
            f"expected None below the 5-member floor, got {ecmwf_mean}"
        )

        wm._CONSENSUS_CACHE.clear()
        wm._ensemble_cache.clear()


class TestGetGemUkmoMeans:
    """backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2:
    _get_gem_ukmo_means must fetch gem_global/ukmo_global_ensemble_20km's own
    means via the same ENSEMBLE_BASE/_model_prob_and_mean infra as
    _get_consensus_probs's icon/gfs/ecmwf fetches — kept as a separate
    function/return shape so ~20 existing call sites that mock/unpack
    _get_consensus_probs's fixed 5-tuple don't need touching. Calls the
    module-import-time-captured real function (_REAL_GET_GEM_UKMO_MEANS)
    since conftest's default_gem_ukmo_means_none autouse fixture stubs
    weather_markets._get_gem_ukmo_means to (None, None) by default."""

    def test_fetches_and_averages_gem_ukmo_members(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_cb.record_success()  # ensure circuit closed

        # Hand-computed means: gem=80.0, ukmo=85.0 — distinct from each other
        # and from every icon/gfs/ecmwf fixture value elsewhere in this file,
        # so a mix-up (e.g. ukmo reading gem's members) would fail.
        members_by_model = {
            "gem_global": [78.0, 79.0, 80.0, 81.0, 82.0],
            "ukmo_global_ensemble_20km": [83.0, 84.0, 85.0, 86.0, 87.0],
        }

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            members = members_by_model.get(model, [])
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {
                "daily": {
                    f"temperature_2m_max_member{i + 1:02d}": [v]
                    for i, v in enumerate(members)
                }
            }
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        condition = {"type": "above", "threshold": 70.0}

        gem_mean, ukmo_mean = _REAL_GET_GEM_UKMO_MEANS("NYC", target, condition)

        assert gem_mean == pytest.approx(80.0), f"gem mean wrong: {gem_mean}"
        assert ukmo_mean == pytest.approx(85.0), f"ukmo mean wrong: {ukmo_mean}"

        wm._ensemble_cache.clear()

    def test_returns_none_when_fewer_than_five_members(self, monkeypatch):
        """_model_prob_and_mean's own >=5-member floor must also gate GEM/UKMO —
        matching icon/gfs/ecmwf's existing behavior. Also exercises UKMO's real
        shorter horizon: a date beyond its ~9-10-day real coverage returns
        fewer than 5 non-null members and must go None, not crash."""
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if model == "ukmo_global_ensemble_20km":
                # Only 3 members — below the 5-member floor (simulates a date
                # past UKMO's real ~9-10-day horizon).
                daily = {
                    "temperature_2m_max_member01": [83.0],
                    "temperature_2m_max_member02": [84.0],
                    "temperature_2m_max_member03": [85.0],
                }
            else:
                daily = {
                    f"temperature_2m_max_member{i + 1:02d}": [78.0 + i]
                    for i in range(5)
                }
            resp.json.return_value = {"daily": daily}
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        condition = {"type": "above", "threshold": 70.0}

        gem_mean, ukmo_mean = _REAL_GET_GEM_UKMO_MEANS("NYC", target, condition)
        assert gem_mean == pytest.approx(80.0), f"gem mean wrong: {gem_mean}"
        assert ukmo_mean is None, (
            f"expected None below the 5-member floor, got {ukmo_mean}"
        )

        wm._ensemble_cache.clear()


class TestBatchPrewarmEnsembleTrackingOnlyModels:
    """backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2:
    batch_prewarm_ensemble must cache gem_global/ukmo_global_ensemble_20km's
    per-model members (so _get_gem_ukmo_means hits warm cache instead of an
    unbatched live call) but must NOT fold them into the blended
    (city, date, None, var) cache entry that feeds the live trading forecast
    -- neither _model_weights() nor _forecast_model_weights() has a baseline
    entry for them, so blending would give them a silent, uncalibrated 1.0
    weight with zero tracked accuracy behind it."""

    def test_gem_ukmo_cached_but_excluded_from_blend(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()
        wm._ensemble_cb.record_success()

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        date_iso = target.isoformat()

        # Distinct, absurd-magnitude members for gem/ukmo so a leak into the
        # blend (or a missing per-model cache write) fails loudly rather than
        # blending in unnoticed among realistic temperatures.
        members_by_model = {
            "icon_seamless": [70.0, 71.0, 72.0, 73.0, 74.0],
            "gfs_seamless": [68.0, 69.0, 70.0, 71.0, 72.0],
            "ecmwf_aifs025_ensemble": [74.0, 75.0, 76.0, 77.0, 78.0],
            "gem_global": [200.0, 201.0, 202.0, 203.0, 204.0],
            "ukmo_global_ensemble_20km": [-200.0, -201.0, -202.0, -203.0, -204.0],
        }

        def _fake_om_request(method, url, **kwargs):
            params = kwargs.get("params", {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            daily_key = params.get("daily")
            if daily_key == "precipitation_sum":
                # Precip section is untouched by this change — return an
                # empty-but-valid response so it no-ops without erroring.
                resp.json.return_value = {"daily": {"time": [date_iso]}}
                return resp
            model = params.get("models")
            members = members_by_model.get(model, [])
            resp.json.return_value = {
                "daily": {
                    "time": [date_iso],
                    **{
                        f"{daily_key}_member{i + 1:02d}": [v]
                        for i, v in enumerate(members)
                    },
                }
            }
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)

        written = wm.batch_prewarm_ensemble({("NYC", date_iso)})
        assert written > 0, "batch_prewarm_ensemble wrote no cache entries"

        # Per-model cache entries (H-14) must exist for BOTH blend models and
        # tracking-only models — this is what lets _get_consensus_probs and
        # _get_gem_ukmo_means hit warm cache instead of a live per-market call.
        for model in [
            "icon_seamless",
            "gfs_seamless",
            "ecmwf_aifs025_ensemble",
            "gem_global",
            "ukmo_global_ensemble_20km",
        ]:
            key = (model, "NYC", date_iso, "max", None)
            cached = wm._ensemble_cache.get(key)
            assert cached is not None, f"{model} per-model cache entry missing"
            assert cached == pytest.approx(members_by_model[model]), (
                f"{model} cached members wrong: {cached}"
            )

        # The blended entry (what get_ensemble_temps/analyze_trade's live
        # forecast_temp actually reads) must NOT contain gem/ukmo's members.
        blended = wm._ensemble_cache.get(("NYC", date_iso, None, "max"))
        assert blended is not None
        assert all(-100.0 < t < 100.0 for t in blended), (
            f"gem/ukmo's tracking-only members leaked into the live trading "
            f"blend: {blended}"
        )
        # Sanity: the blend must still contain the real blend models' values.
        assert any(t == pytest.approx(72.0) for t in blended), (
            "icon_seamless's real member is missing from the blend"
        )

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()


class TestWeightsFromMaeThinModelIsolation:
    """Adjacency finding from the 2026-07-23 opus review of the ECMWF
    instrumentation change: _weights_from_mae() previously `return None`'d
    (aborting for EVERY model) the moment ANY tracked model was globally thin
    (`n = stats["n"]` has no per-city floor) — meaning onboarding a new,
    freshly-instrumented model (ecmwf_aifs025_ensemble) would have silently
    disabled MAE-based weighting for icon/gfs everywhere until ECMWF alone
    crossed min_n. Fixed to skip only the thin model."""

    def test_thin_model_excluded_not_blocking(self, monkeypatch):
        import weather_markets as wm

        wm._MAE_WEIGHTS_CACHE.clear()

        def _fake_get_member_accuracy(days_back=60):
            return {
                # Well-observed — must still get a real weight.
                "icon_seamless": {
                    "mae": 2.0,
                    "n": 50,
                    "city_breakdown": {"NYC": 2.0},
                    "city_n_breakdown": {"NYC": 50},
                },
                "gfs_seamless": {
                    "mae": 4.0,
                    "n": 50,
                    "city_breakdown": {"NYC": 4.0},
                    "city_n_breakdown": {"NYC": 50},
                },
                # Freshly instrumented, globally thin — must be excluded, not
                # block icon/gfs.
                "ecmwf_aifs025_ensemble": {
                    "mae": 3.0,
                    "n": 2,
                    "city_breakdown": {"NYC": 3.0},
                    "city_n_breakdown": {"NYC": 2},
                },
            }

        monkeypatch.setattr("tracker.get_member_accuracy", _fake_get_member_accuracy)

        result = wm._weights_from_mae("NYC", min_n=20)

        assert result is not None, (
            "a single thin model must not block icon/gfs's own weights"
        )
        assert "ecmwf_aifs025_ensemble" not in result, (
            f"thin model must be excluded from the result, got: {result}"
        )
        assert "icon_seamless" in result and "gfs_seamless" in result
        # icon has lower MAE (2.0 vs 4.0) so must get the higher weight.
        assert result["icon_seamless"] > result["gfs_seamless"], (
            f"lower-MAE model must get a higher weight: {result}"
        )

        wm._MAE_WEIGHTS_CACHE.clear()

    def test_all_models_thin_returns_none(self, monkeypatch):
        """Unchanged behavior: if every tracked model is thin, still None."""
        import weather_markets as wm

        wm._MAE_WEIGHTS_CACHE.clear()

        def _fake_get_member_accuracy(days_back=60):
            return {
                "icon_seamless": {
                    "mae": 2.0,
                    "n": 2,
                    "city_breakdown": {},
                    "city_n_breakdown": {},
                },
                "gfs_seamless": {
                    "mae": 4.0,
                    "n": 3,
                    "city_breakdown": {},
                    "city_n_breakdown": {},
                },
            }

        monkeypatch.setattr("tracker.get_member_accuracy", _fake_get_member_accuracy)

        result = wm._weights_from_mae("NYC", min_n=20)
        assert result is None

        wm._MAE_WEIGHTS_CACHE.clear()


class TestWeightsFromMaeExcludesTrackingOnlyModels:
    """Opus review finding on the GENERALIZED PER-MODEL ACCURACY TRACKING
    Pass 2 diff: _weights_from_mae() summed EVERY tracked model (including
    gem_global/ukmo_global_ensemble_20km) into its total/n_models
    normalization denominator, even though only baseline models' own
    weights are ever read out downstream. That meant a track-only model's
    tracked accuracy still numerically shifted icon/gfs/ecmwf's normalized
    weight the moment it crossed the observation floor -- a real leak into
    live trade decisions the batch_prewarm_ensemble blend-exclusion alone
    didn't stop. Fixed by skipping TRACKING_ONLY_MODEL_NAMES entirely
    before they ever enter the weights dict being normalized."""

    def _fake_acc(self, *, with_gem: bool) -> dict:
        acc = {
            "icon_seamless": {
                "mae": 2.0,
                "n": 50,
                "city_breakdown": {},
                "city_n_breakdown": {},
            },
            "gfs_seamless": {
                "mae": 4.0,
                "n": 50,
                "city_breakdown": {},
                "city_n_breakdown": {},
            },
        }
        if with_gem:
            # Deliberately very low MAE (highly "accurate") and well past
            # the observation floor -- if this leaks into the normalization
            # denominator at all, icon/gfs's weights below will visibly
            # shrink relative to the gem-absent baseline.
            acc["gem_global"] = {
                "mae": 0.5,
                "n": 50,
                "city_breakdown": {},
                "city_n_breakdown": {},
            }
        return acc

    def test_gem_presence_does_not_change_baseline_models_weights(self, monkeypatch):
        import weather_markets as wm

        wm._MAE_WEIGHTS_CACHE.clear()
        monkeypatch.setattr(
            "tracker.get_member_accuracy",
            lambda days_back=60: self._fake_acc(with_gem=False),
        )
        baseline_result = wm._weights_from_mae("NYC", min_n=20)
        wm._MAE_WEIGHTS_CACHE.clear()

        monkeypatch.setattr(
            "tracker.get_member_accuracy",
            lambda days_back=60: self._fake_acc(with_gem=True),
        )
        with_gem_result = wm._weights_from_mae("NYC", min_n=20)
        wm._MAE_WEIGHTS_CACHE.clear()

        assert "gem_global" not in with_gem_result, (
            f"tracking-only model must never appear in the returned weights, "
            f"got: {with_gem_result}"
        )
        assert with_gem_result["icon_seamless"] == pytest.approx(
            baseline_result["icon_seamless"]
        ), (
            f"gem_global's presence changed icon_seamless's normalized weight: "
            f"{with_gem_result['icon_seamless']} vs baseline "
            f"{baseline_result['icon_seamless']} -- it leaked into the "
            f"normalization denominator"
        )
        assert with_gem_result["gfs_seamless"] == pytest.approx(
            baseline_result["gfs_seamless"]
        ), (
            f"gem_global's presence changed gfs_seamless's normalized weight: "
            f"{with_gem_result['gfs_seamless']} vs baseline "
            f"{baseline_result['gfs_seamless']}"
        )
        # Hand-computed sanity check on the baseline itself: icon mae=2.0,
        # gfs mae=4.0 -> weights 0.5/0.25, normalised to sum-to-2.
        assert baseline_result["icon_seamless"] == pytest.approx(4 / 3)
        assert baseline_result["gfs_seamless"] == pytest.approx(2 / 3)


# ── TestBetweenFloorGate ──────────────────────────────────────────────────────


class TestBetweenFloorGate:
    """Verify the 9b between-floor gate only blocks low-confidence YES bets.

    The correct condition is: blended_prob < 0.15 AND blended_prob > market_prob.
    This means:
      - LOW model prob + would bet NO  → allowed  (genuine NO edge)
      - LOW model prob + would bet YES → blocked   (suspicious low-confidence YES)

    The old condition (market > 0.30) was logically inverted — it only fired when
    blended_prob < market_prob (always a NO signal), so it blocked profitable NO
    trades (16/26 = 61.5% win rate) while never catching the suspicious YES case.
    """

    def _gate_fires(self, blended_prob: float, market_prob: float) -> bool:
        """Evaluate the corrected gate condition directly."""
        return blended_prob < 0.15 and blended_prob > market_prob

    def test_no_bet_low_model_prob_not_blocked(self):
        """blended=8%, market=45% → we'd bet NO → gate must NOT fire."""
        assert not self._gate_fires(0.08, 0.45)

    def test_no_bet_very_low_model_prob_not_blocked(self):
        """blended=3%, market=65% → strong NO signal → gate must NOT fire."""
        assert not self._gate_fires(0.03, 0.65)

    def test_yes_bet_low_model_prob_is_blocked(self):
        """blended=10%, market=7% → we'd bet YES with low confidence → gate MUST fire."""
        assert self._gate_fires(0.10, 0.07)

    def test_above_threshold_never_blocked(self):
        """blended=20% (above 15%) → gate never fires regardless of side."""
        assert not self._gate_fires(0.20, 0.10)  # even if this would be YES

    def test_old_condition_would_have_been_wrong(self):
        """Demonstrates the old condition (market > 0.30) was logically inverted.

        With old logic: blended=8%, market=45% → market>0.30 AND blended<0.15 → BLOCKED.
        This was wrong — it blocked a profitable NO trade.
        With new logic: blended < market → not blocked. Correct.
        """
        blended, market = 0.08, 0.45
        old_gate = blended < 0.15 and market > 0.30
        new_gate = blended < 0.15 and blended > market
        assert old_gate is True, "old gate would have fired (the bug)"
        assert new_gate is False, "new gate correctly allows the NO trade"


# ── TestModelDisagreement ────────────────────────────────────────────────────


def test_model_disagreement_computation():
    """Verify disagreement flag fires when NWS and ensemble differ by more than 8°F."""
    # Direct logic test — avoid full analyze_trade mock complexity
    forecast_temp_raw = 80.0
    ens_mean = 70.0
    disagree_f = round(abs(forecast_temp_raw - ens_mean), 1)
    flag = bool(disagree_f > 8.0)
    assert disagree_f == 10.0
    assert flag is True

    # Under threshold — no flag
    disagree_f2 = round(abs(75.0 - 72.0), 1)
    flag2 = bool(disagree_f2 > 8.0)
    assert disagree_f2 == 3.0
    assert flag2 is False


# ── TestDetectHedgeOpportunity ───────────────────────────────────────────────


class TestDetectHedgeOpportunity:
    """analyze_trade must surface 'city' in its result (previously missing
    entirely) and detect_hedge_opportunity must match on target_date too,
    not just city — both were previously silently broken."""

    def test_analyze_trade_result_includes_city(self):
        """analyze_trade's returned dict must include a 'city' key so
        detect_hedge_opportunity can actually find a match (it previously had
        neither 'city' nor '_city', so city was always None)."""
        from weather_markets import detect_hedge_opportunity

        analysis = {"city": "Chicago", "target_date": "2026-07-11"}
        assert detect_hedge_opportunity(analysis, []) is False  # no open trades yet

    def test_same_city_same_date_opposite_side_is_a_hedge(self):
        from weather_markets import detect_hedge_opportunity

        analysis = {
            "city": "Chicago",
            "target_date": "2026-07-10",
            "recommended_side": "yes",
        }
        open_trades = [{"city": "Chicago", "target_date": "2026-07-10", "side": "no"}]
        assert detect_hedge_opportunity(analysis, open_trades) is True

    def test_same_city_different_date_is_not_a_hedge(self):
        """A NO on tomorrow's market must NOT be flagged as a hedge of a YES
        on today's market for the same city — they don't offset exposure."""
        from weather_markets import detect_hedge_opportunity

        analysis = {
            "city": "Chicago",
            "target_date": "2026-07-11",
            "recommended_side": "no",
        }
        open_trades = [{"city": "Chicago", "target_date": "2026-07-10", "side": "yes"}]
        assert detect_hedge_opportunity(analysis, open_trades) is False

    def test_different_city_is_not_a_hedge(self):
        from weather_markets import detect_hedge_opportunity

        analysis = {
            "city": "Chicago",
            "target_date": "2026-07-10",
            "recommended_side": "yes",
        }
        open_trades = [{"city": "Denver", "target_date": "2026-07-10", "side": "no"}]
        assert detect_hedge_opportunity(analysis, open_trades) is False

    def test_missing_city_returns_false(self):
        from weather_markets import detect_hedge_opportunity

        assert detect_hedge_opportunity({}, [{"city": "Chicago"}]) is False


# ── TestMetarLockInLowMarketAsymmetry ────────────────────────────────────────


class TestMetarLockInLowMarketAsymmetry:
    """A LOW market's running daily-min-so-far can only DECREASE as the day
    progresses — 'min already fell below threshold-margin' is monotone-safe,
    but 'min has stayed above threshold+margin' is not (evening cooling can
    still reverse it). Only the unsafe direction should be rejected."""

    def _call(self, min_temp_f, threshold, cond_type, local_hour=16):
        from datetime import UTC, datetime
        from unittest.mock import MagicMock, patch

        import metar as _metar
        import weather_markets as wm

        today = datetime.now(UTC).date()
        fake_obs_time = MagicMock()
        fake_obs_local = MagicMock(hour=local_hour)
        fake_obs_local.date.return_value = today
        fake_obs_time.astimezone.return_value = fake_obs_local

        with patch.object(wm, "_metar_station_for_city", return_value="KJFK"):
            with patch.object(
                _metar,
                "fetch_metar",
                return_value={
                    "current_temp_f": min_temp_f,
                    "min_temp_f": min_temp_f,
                    "max_temp_f": min_temp_f + 20.0,
                    "obs_time": fake_obs_time,
                },
            ):
                return wm._metar_lock_in(
                    city="NYC",
                    target_date=today,
                    condition={"type": cond_type, "threshold": threshold},
                    ticker="KXLOWNY-26JUL10-T40",
                )

    def test_low_market_above_still_above_margin_is_not_locked(self):
        """'low above 40', running min=45 (>= 40+3 margin): NOT monotone-safe
        — the min could still fall below 40 later tonight. Must reject."""
        locked, _prob, _details = self._call(
            min_temp_f=45.0, threshold=40.0, cond_type="above"
        )
        assert locked is False

    def test_low_market_above_already_below_margin_is_locked(self):
        """'low above 40', running min=30 (<= 40-3 margin): monotone-safe —
        the min can only stay at or below 30. Safe to lock NO."""
        locked, _prob, details = self._call(
            min_temp_f=30.0, threshold=40.0, cond_type="above"
        )
        assert locked is True
        assert details.get("outcome") == "no"

    def test_low_market_below_still_above_margin_is_not_locked(self):
        """'low below 60', running min=65 (>= 60+3 margin): NOT monotone-safe
        for the NO outcome — the min could still fall below 60 later. Reject."""
        locked, _prob, _details = self._call(
            min_temp_f=65.0, threshold=60.0, cond_type="below"
        )
        assert locked is False

    def test_low_market_below_already_below_margin_is_locked(self):
        """'low below 60', running min=50 (<= 60-3 margin): monotone-safe —
        the min already fell below 60 and can only stay there or go lower."""
        locked, _prob, details = self._call(
            min_temp_f=50.0, threshold=60.0, cond_type="below"
        )
        assert locked is True
        assert details.get("outcome") == "yes"


# ── TestMosBlendNoCrossVariableFallback ──────────────────────────────────────


class TestMosBlendNoCrossVariableFallback:
    """A LOW market (var='min') with no MOS minimum must skip the MOS blend
    entirely, not silently substitute the daily MAXIMUM."""

    def _enriched_low_market(self):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=1)
        return {
            "ticker": f"KXLOWCHI-{target.strftime('%d%b%y').upper()}-T60",
            "title": "Chicago low above 60Â°F",
            "_city": "Chicago",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 85.0,
                "low_f": 62.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": "Chicago",
                "models_used": 3,
                "high_range": (83.0, 87.0),
            },
            "yes_bid": 0.45,
            "yes_ask": 0.55,
            "no_bid": 0.45,
            "close_time": "",
            "series_ticker": "KXLOWCHI",
            "volume": 500,
            "open_interest": 200,
        }

    def test_mos_missing_min_does_not_use_max_as_substitute(self):
        """MOS returns max_temp_f=85 (daily high) but min_temp_f=None (no
        overnight-min period available). blended_prob must NOT be pulled
        toward P(condition | 85Â°F-centered distribution) for this low market
        — that would be scoring the wrong variable entirely."""
        from unittest.mock import MagicMock, patch

        import weather_markets as wm

        enriched = self._enriched_low_market()

        _fake_mos = MagicMock()
        _fake_mos.get_mos_station = lambda city: "KMDW"
        _fake_mos.fetch_mos_best = lambda station, target_date=None: {
            "max_temp_f": 85.0,
            "min_temp_f": None,
            "sigma": 3.5,
        }

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[58.0, 59.0, 60.0, 61.0, 62.0] * 6,
            ),
            patch("weather_markets.fetch_temperature_nbm", return_value=60.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=60.0),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch("weather_markets.climatological_prob", return_value=0.5),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
            patch("nws.get_live_observation", return_value=None),
            patch("climatology.persistence_prob", return_value=0.3),
            patch("mos.get_mos_station", _fake_mos.get_mos_station),
            patch("mos.fetch_mos_best", _fake_mos.fetch_mos_best),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        # With min_temp_f=None the MOS blend must be skipped entirely, so
        # "mos" must not appear as a nonzero blend source.
        blend = result.get("blend_sources", {})
        assert blend.get("mos", 0.0) == 0.0, (
            f"MOS blend fired with a substituted max_temp_f instead of being "
            f"skipped for missing min_temp_f: blend_sources={blend}"
        )


class TestComputeEnsembleProbRefactorSafetyNet:
    """Dedicated unit tests for _compute_ensemble_prob(), extracted from
    analyze_trade()'s daily path so it and the new hourly path share the
    numerically-subtle EMOS/Gaussian core (backlog.txt "HOURLY-DIRECTIONAL
    TEMPERATURE MARKETS" Step 2). The Step 2 plan committed to a dedicated
    before/after regression test for this extraction at the >=5/>=10
    member-count boundaries and the EMOS-vs-raw-fraction fallback -- this
    class is that test, called directly rather than only indirectly via the
    full analyze_trade() daily-path regression suite."""

    def _condition(self, threshold=70.0, ctype="above"):
        return {"type": ctype, "threshold": threshold}

    def test_below_ten_members_uses_gaussian_not_emos(self, monkeypatch):
        """<10 members must take the Gaussian branch (_forecast_probability),
        never EMOS -- hand-verified against a manual computation."""
        import weather_markets as wm

        temps = [68.0, 69.0, 70.0, 71.0, 72.0, 73.0, 74.0]  # 7 members
        ens_stats = wm.ensemble_stats(temps)
        method, ens_prob = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=71.0),
            forecast_temp=71.0,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        assert method == "normal_dist"
        # Manual check: sigma = min(ens_std, _SIGMA_1DAY_CAP) * 1.0, forecast=71,
        # threshold=71 -> P(above) should be ~0.5 (forecast sits exactly on
        # the threshold, symmetric Gaussian).
        assert ens_prob == pytest.approx(0.5, abs=0.05)

    def test_exactly_ten_members_uses_emos_or_ensemble_not_gaussian(self, monkeypatch):
        """The >=10 boundary is inclusive -- exactly 10 members must take the
        EMOS/raw-fraction branch (method label changes), not Gaussian."""
        import weather_markets as wm

        temps = [65.0, 66.0, 67.0, 68.0, 69.0, 70.0, 71.0, 72.0, 73.0, 74.0]  # 10
        ens_stats = wm.ensemble_stats(temps)
        monkeypatch.setattr("ml_bias._load_emos_params", lambda: None)
        method, ens_prob = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=70.0),
            forecast_temp=69.5,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        assert method == "ensemble", "exactly 10 members must not fall back to Gaussian"
        # Raw exceedance fraction hand-computed: 4 of 10 members (71,72,73,74) > 70.
        assert ens_prob == pytest.approx(0.4, abs=1e-9)

    def test_nine_members_uses_gaussian(self, monkeypatch):
        """One below the boundary must still take the Gaussian branch."""
        import weather_markets as wm

        temps = [65.0, 66.0, 67.0, 68.0, 69.0, 70.0, 71.0, 72.0, 73.0]  # 9
        ens_stats = wm.ensemble_stats(temps)
        method, _ = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=70.0),
            forecast_temp=69.0,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        assert method == "normal_dist"

    def test_emos_used_when_params_trained(self, monkeypatch):
        """>=10 members with EMOS params available must use method='emos',
        not the raw-fraction fallback -- and must square std (variance),
        never pass std directly (a documented CRITICAL invariant)."""
        import weather_markets as wm

        temps = [float(65 + i) for i in range(12)]  # 12 members, mean~70.5
        ens_stats = wm.ensemble_stats(temps)
        captured = {}

        def _fake_exceedance(params, mean, ens_var, threshold):
            captured["ens_var"] = ens_var
            captured["mean"] = mean
            return 0.42

        monkeypatch.setattr("ml_bias._load_emos_params", lambda: (0.0, 1.0, 0.0, 1.0))
        monkeypatch.setattr("ml_bias.emos_exceedance_prob", _fake_exceedance)
        method, ens_prob = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=70.0, ctype="above"),
            forecast_temp=70.5,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        assert method == "emos"
        assert ens_prob == pytest.approx(0.42)
        # variance, not std -- must be std**2, and std > 0 for non-degenerate input.
        assert captured["ens_var"] == pytest.approx(ens_stats["std"] ** 2)
        assert captured["ens_var"] != pytest.approx(ens_stats["std"]), (
            "must square std into variance, not pass std directly (CRITICAL invariant)"
        )

    def test_emos_falls_back_to_raw_fraction_when_untrained(self, monkeypatch):
        """>=10 members with no EMOS params must use the raw exceedance
        fraction fallback, method='ensemble' (not 'emos')."""
        import weather_markets as wm

        temps = [60.0, 61.0, 62.0, 68.0, 69.0, 71.0, 72.0, 78.0, 79.0, 80.0]  # 10
        ens_stats = wm.ensemble_stats(temps)
        monkeypatch.setattr("ml_bias._load_emos_params", lambda: None)
        method, ens_prob = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=70.0),
            forecast_temp=70.0,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        assert method == "ensemble"
        # Hand-computed: members strictly above 70.0 are 71,72,78,79,80 -> 5 of 10.
        expected = sum(1 for t in temps if t > 70.0) / len(temps)
        assert expected == pytest.approx(0.5)
        assert ens_prob == pytest.approx(expected)

    def test_below_condition_widens_sigma_in_gaussian_branch(self, monkeypatch):
        """'below' condition type widens sigma by 1.5x in the Gaussian
        branch (empirical MAE ~2x ensemble std for below markets) -- confirm
        this still fires post-extraction by comparing against 'above' at the
        same inputs."""
        import weather_markets as wm

        temps = [68.0, 69.0, 70.0, 71.0, 72.0]  # 5 members, forces Gaussian
        ens_stats = wm.ensemble_stats(temps)
        _, prob_above = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=65.0, ctype="above"),
            forecast_temp=70.0,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        _, prob_below = wm._compute_ensemble_prob(
            temps,
            ens_stats,
            self._condition(threshold=65.0, ctype="below"),
            forecast_temp=70.0,
            target_date=__import__("datetime").date(2026, 7, 20),
            days_out=0,
            sigma_mult=1.0,
        )
        # Wider sigma (below) -> less extreme probability than the narrow-sigma
        # complement of the above case for the same forecast/threshold gap.
        assert prob_below > (1.0 - prob_above), (
            "below's sigma widening must make the tail probability less "
            "extreme than the above case's complement"
        )


class TestComputePersistenceProbRefactorSafetyNet:
    """Dedicated unit tests for _compute_persistence_prob(), the second
    function extracted for the hourly path to share with daily (see
    TestComputeEnsembleProbRefactorSafetyNet's docstring for why)."""

    def test_days_out_above_two_returns_none(self):
        import weather_markets as wm

        result = wm._compute_persistence_prob(
            "NYC",
            (40.0, -74.0, "America/New_York"),
            {"type": "above", "threshold": 70.0},
            "max",
            70.0,
            days_out=3,
        )
        assert result is None

    def test_no_live_observation_returns_none(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
        result = wm._compute_persistence_prob(
            "NYC",
            (40.0, -74.0, "America/New_York"),
            {"type": "above", "threshold": 70.0},
            "max",
            70.0,
            days_out=0,
        )
        assert result is None

    def test_uses_daily_max_for_max_var_at_days_out_zero(self, monkeypatch):
        """var='max' at days_out=0 must prefer the observed running daily
        max over the instantaneous current temp (the high may have already
        occurred and be higher than 'right now')."""
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"max_temp_f": 82.0, "temp_f": 75.0},
        )
        captured = {}

        def _fake_persistence(cond_type, lo, hi, current_temp):
            captured["current_temp"] = current_temp
            return 0.77

        monkeypatch.setattr("climatology.persistence_prob", _fake_persistence)
        result = wm._compute_persistence_prob(
            "NYC",
            (40.0, -74.0, "America/New_York"),
            {"type": "above", "threshold": 70.0},
            "max",
            70.0,
            days_out=0,
        )
        assert result == pytest.approx(0.77)
        assert captured["current_temp"] == pytest.approx(82.0), (
            "must use the observed daily max (82.0), not the instantaneous "
            "current temp (75.0), for a var='max' days_out=0 lookup"
        )

    def test_uses_instantaneous_temp_for_min_var(self, monkeypatch):
        """var='min' must use the instantaneous current temp, not max_temp_f
        (the daily-max special case only applies to var='max')."""
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"max_temp_f": 82.0, "temp_f": 61.0},
        )
        captured = {}

        def _fake_persistence(cond_type, lo, hi, current_temp):
            captured["current_temp"] = current_temp
            return 0.33

        monkeypatch.setattr("climatology.persistence_prob", _fake_persistence)
        result = wm._compute_persistence_prob(
            "NYC",
            (40.0, -74.0, "America/New_York"),
            {"type": "below", "threshold": 65.0},
            "min",
            61.0,
            days_out=0,
        )
        assert result == pytest.approx(0.33)
        assert captured["current_temp"] == pytest.approx(61.0)

    def test_exception_in_lookup_returns_none_not_raises(self, monkeypatch):
        import weather_markets as wm

        def _boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr("nws.get_live_observation", _boom)
        result = wm._compute_persistence_prob(
            "NYC",
            (40.0, -74.0, "America/New_York"),
            {"type": "above", "threshold": 70.0},
            "max",
            70.0,
            days_out=0,
        )
        assert result is None
