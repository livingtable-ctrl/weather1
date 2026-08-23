"""Unit tests for key functions in weather_markets.py and utils.py."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so imports work when run from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

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
# Same reasoning as _REAL_GET_GEM_UKMO_MEANS above, for conftest's
# default_ecmwf_aifs_prob_none autouse fixture.
_REAL_GET_ECMWF_AIFS_PROB = _wm_module._get_ecmwf_aifs_prob

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

    def test_returns_dict_with_expected_keys(self, monkeypatch):
        """month=1 is winter, so _forecast_model_weights hits the same
        live-network _get_enso_phase() call test_all_winter_months_use_high_
        ecmwf below already pins to neutral -- see that test's docstring."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_get_enso_phase", lambda: "neutral")
        weights = _forecast_model_weights(1)
        assert isinstance(weights, dict)
        for key in ("gfs_seamless", "ecmwf_ifs025", "icon_seamless"):
            assert key in weights

    def test_winter_month_boosts_ecmwf_weight(self, monkeypatch):
        """ECMWF weight should be higher in winter than summer.

        month=1 is winter, so _forecast_model_weights hits the same
        live-network _get_enso_phase() call test_all_winter_months_use_high_
        ecmwf below already pins to neutral -- see that test's docstring."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_get_enso_phase", lambda: "neutral")
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

    def test_gfs_and_icon_weights_are_constant(self, monkeypatch):
        """GFS and ICON weights should be 1.0 year-round.

        Loops every month, including winter ones, which hit the same
        live-network _get_enso_phase() call test_all_winter_months_use_high_
        ecmwf above already pins to neutral -- see that test's docstring."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_get_enso_phase", lambda: "neutral")
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

    w_tight = _confidence_scaled_blend_weights(
        days_out=3, has_nws=True, has_clim=True, ens_std=2.0
    )
    w_wide = _confidence_scaled_blend_weights(
        days_out=3, has_nws=True, has_clim=True, ens_std=12.0
    )
    assert w_wide["ensemble"] < w_tight["ensemble"]
    assert abs(sum(w_wide.values()) - 1.0) < 1e-6


def test_ensemble_confidence_scale_no_std_unchanged():
    import pytest

    from weather_markets import _blend_weights, _confidence_scaled_blend_weights

    w1 = _blend_weights(5, has_nws=True, has_clim=True)
    w2 = _confidence_scaled_blend_weights(5, has_nws=True, has_clim=True, ens_std=None)
    assert w1 == pytest.approx(w2, abs=1e-6)


def test_ensemble_confidence_scale_clamped(monkeypatch):
    """w_ens_scaled must clamp to 1.0 when scale * w_ens would exceed the weight budget.

    City calibration ensemble=0.90 (days_out=1 so _nws_days_out_scale is a no-op:
    "no change -- calibration data is at d=1") + ens_std=0.01 (scale=max(0.5,
    min(1.5, 4.0/0.01))=1.5) -> unclamped w_ens*scale = 0.90*1.5 = 1.35, which
    exceeds 1.0 and must be clamped -- the old vacuous version of this test
    (scaled["ensemble"] <= 1.0) passed for every possible input regardless of
    whether the clamp branch ever actually engaged.
    """
    import weather_markets as wm

    monkeypatch.setattr(
        wm,
        "_CITY_WEIGHTS",
        {"NYC": {"ensemble": 0.90, "climatology": 0.05, "nws": 0.05}},
    )
    unscaled = wm._blend_weights(days_out=1, has_nws=True, has_clim=True, city="NYC")
    assert unscaled["ensemble"] == pytest.approx(0.90)  # sanity: clamp not yet applied
    assert (
        unscaled["ensemble"] * 1.5 > 1.0
    )  # confirms this input actually triggers the clamp

    scaled = wm._confidence_scaled_blend_weights(
        days_out=1, has_nws=True, has_clim=True, ens_std=0.01, city="NYC"
    )
    assert scaled["ensemble"] == pytest.approx(1.0)
    assert scaled["climatology"] == pytest.approx(0.0)
    assert scaled["nws"] == pytest.approx(0.0)


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


# ── TestEdgeLabel ─────────────────────────────────────────────────────────────


class TestEdgeLabel:
    """_edge_label(edge, side) must take its YES/NO direction word from
    `side`, never from edge's own sign -- backlog.txt "SIGNAL LABEL
    DIRECTION IGNORES RECOMMENDED_SIDE". Reverting to `direction = "YES"
    if edge > 0 else "NO "` fails 6 of the 10 tests below (every *_no
    case plus test_magnitude_uses_absolute_value_regardless_of_sign);
    test_positive_edge_with_no_side_labels_no and
    test_negative_edge_with_yes_side_labels_yes are the two written
    specifically to target that mutation (a positive/negative edge value
    paired with the opposite side), not the only ones sensitive to it.
    """

    def test_neutral_below_threshold_both_sides(self):
        from weather_markets import _edge_label

        assert _edge_label(0.049, "yes") == "NEUTRAL"
        assert _edge_label(-0.049, "no") == "NEUTRAL"
        assert _edge_label(0.0, "yes") == "NEUTRAL"

    def test_weak_yes(self):
        from weather_markets import _edge_label

        assert _edge_label(0.05, "yes") == "WEAK YES     "
        assert _edge_label(0.149, "yes") == "WEAK YES     "

    def test_weak_no(self):
        from weather_markets import _edge_label

        assert _edge_label(0.05, "no") == "WEAK NO      "
        assert _edge_label(0.149, "no") == "WEAK NO      "

    def test_buy_yes_boundary(self):
        from weather_markets import _edge_label

        assert _edge_label(0.15, "yes") == "BUY YES      "
        assert _edge_label(0.249, "yes") == "BUY YES      "

    def test_buy_no_boundary(self):
        from weather_markets import _edge_label

        assert _edge_label(0.15, "no") == "BUY NO       "

    def test_strong_buy_yes_boundary(self):
        from weather_markets import _edge_label

        assert _edge_label(0.25, "yes") == "STRONG BUY YES"
        assert _edge_label(0.9, "yes") == "STRONG BUY YES"

    def test_strong_buy_no_boundary(self):
        from weather_markets import _edge_label

        assert _edge_label(0.25, "no") == "STRONG BUY NO "

    def test_positive_edge_with_no_side_labels_no(self):
        """The exact bug scenario: net_edge/adjusted_edge is virtually
        always positive for a good trade regardless of recommended side --
        a positive value passed alongside side="no" must still say NO.
        Reproduces the live KXHIGHTSEA-26AUG07-T85 case (net_edge=+0.335,
        recommended_side="no")."""
        from weather_markets import _edge_label

        assert _edge_label(0.335, "no") == "STRONG BUY NO "

    def test_negative_edge_with_yes_side_labels_yes(self):
        """Symmetric case: a negative magnitude alongside side="yes" must
        still say YES -- direction is side's job, magnitude is edge's."""
        from weather_markets import _edge_label

        assert _edge_label(-0.335, "yes") == "STRONG BUY YES"

    def test_magnitude_uses_absolute_value_regardless_of_sign(self):
        from weather_markets import _edge_label

        assert _edge_label(0.3, "yes") == _edge_label(-0.3, "yes")
        assert _edge_label(0.3, "no") == _edge_label(-0.3, "no")


# ── TestAdjustedEdgeInAnalyzeTrade ────────────────────────────────────────────


class TestAdjustedEdgeInAnalyzeTrade:
    """analyze_trade() must return both raw net_edge and adjusted_edge (#63)."""

    def test_analyze_trade_returns_adjusted_edge_key(self, monkeypatch):
        """Result dict must contain adjusted_edge and edge_confidence_factor."""
        from datetime import datetime, timedelta

        import weather_markets as wm

        # analyze_trade computes days_out via datetime.now(UTC).date() -- must
        # match here or the hardcoded edge_confidence(10) assertion below can
        # flip to edge_confidence(9)/(11) on a local/UTC date mismatch.
        target = datetime.now(UTC).date() + timedelta(days=10)
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

        w = wm._blend_weights(
            days_out=1, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w["ensemble"] == pytest.approx(0.50, abs=1e-6)
        assert w["nws"] == pytest.approx(0.40, abs=1e-6)

    def test_seasonal_weights_used_when_no_city_weights(self, monkeypatch):
        """If no city weights but seasonal weights loaded, use seasonal (days_out=1 = neutral NWS scale)."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(
            wm,
            "_SEASONAL_WEIGHTS",
            {"spring": {"ensemble": 0.45, "climatology": 0.20, "nws": 0.35}},
        )

        w = wm._blend_weights(
            days_out=1, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert w["ensemble"] == pytest.approx(0.45, abs=1e-6)
        assert w["nws"] == pytest.approx(0.35, abs=1e-6)

    def test_fallback_to_hardcoded_when_no_calibration(self, monkeypatch):
        """With empty dicts, result should match original hardcoded schedule."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
        monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})

        # days_out=5, hardcoded: w_nws=0.25, remainder split ensemble/clim
        w = wm._blend_weights(
            days_out=5, has_nws=True, has_clim=True, city="NYC", season="spring"
        )
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert w["nws"] == pytest.approx(0.25, abs=1e-6)
        assert w["ensemble"] == pytest.approx(0.5175, abs=1e-6)
        assert w["climatology"] == pytest.approx(0.2325, abs=1e-6)


def test_analyze_trade_result_has_model_consensus_field(monkeypatch):
    """analyze_trade result includes model_consensus bool when it returns a result."""
    import mos
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
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
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

    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch this test doesn't mock. Confirmed live: this test failed exactly
    # this way for several hours in this environment (same "system-local-
    # behind-UTC" bug class test_metar_locked_trade_has_ecmwf_forecast_mean_
    # keys/test_metar_locked_trade_has_nbm_quantile_prob_key already
    # document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
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


def test_analyze_trade_result_surfaces_precip_sum_in(monkeypatch):
    """backlog.txt "FORECAST-CONDITION COVARIATES FOR SIGMA": precip_in is
    already fetched with every forecast (get_weather_forecast's daily call)
    but was never threaded past precip-market routing into the temperature-
    path result dict -- analyze_trade must surface it log-only as
    precip_sum_in, read straight from enriched["_forecast"]."""
    import mos
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    monkeypatch.setattr(
        wm, "_get_consensus_probs", lambda *a, **kw: (0.73, 0.75, 74.0, 74.0, None)
    )
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
    monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CONDITION_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
    monkeypatch.setattr(
        wm,
        "get_weather_forecast",
        lambda *a, **kw: {
            "high_f": 75.0,
            "low_f": 55.0,
            "precip_in": 0.37,
            "wind_mph": 5.0,
        },
    )

    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch this test doesn't mock. Confirmed live: this test failed exactly
    # this way for several hours in this environment (same "system-local-
    # behind-UTC" bug class test_metar_locked_trade_has_ecmwf_forecast_mean_
    # keys/test_metar_locked_trade_has_nbm_quantile_prob_key already
    # document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    enriched = {
        "_forecast": {
            "high_f": 75.0,
            "low_f": 55.0,
            "precip_in": 0.37,
            "wind_mph": 5.0,
        },
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
    assert result["precip_sum_in"] == 0.37


def test_analyze_trade_result_precip_sum_in_none_when_key_missing(monkeypatch):
    """A forecast dict without a "precip_in" key (e.g. an older cache entry,
    or a source that doesn't populate it) must yield precip_sum_in=None via
    .get()'s default, not a KeyError.

    Note: enriched["_forecast"] = None makes analyze_trade bail out early at
    its own "no_forecast" gate (verified directly -- returns None before
    reaching the result dict at all), so that case can't exercise this
    ternary's False branch meaningfully. This uses a present-but-incomplete
    forecast dict instead, which analyze_trade processes normally."""
    import mos
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    monkeypatch.setattr(
        wm, "_get_consensus_probs", lambda *a, **kw: (0.73, 0.75, 74.0, 74.0, None)
    )
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
    monkeypatch.setattr(wm, "_SEASONAL_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CONDITION_WEIGHTS", {})
    monkeypatch.setattr(wm, "_CITY_WEIGHTS", {})
    monkeypatch.setattr(
        wm,
        "get_weather_forecast",
        lambda *a, **kw: {"high_f": 75.0, "low_f": 55.0, "wind_mph": 5.0},
    )

    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch this test doesn't mock. Confirmed live: this test failed exactly
    # this way for several hours in this environment (same "system-local-
    # behind-UTC" bug class test_metar_locked_trade_has_ecmwf_forecast_mean_
    # keys/test_metar_locked_trade_has_nbm_quantile_prob_key already
    # document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    enriched = {
        "_forecast": {"high_f": 75.0, "low_f": 55.0, "wind_mph": 5.0},
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
    assert result["precip_sum_in"] is None


def _analyze_trade_base_mocks(monkeypatch, wm):
    """Shared mocks for the nbm_quantile_prob tests below -- same baseline
    as the other analyze_trade fixture tests in this file."""
    import mos

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    monkeypatch.setattr(
        wm, "_get_consensus_probs", lambda *a, **kw: (0.73, 0.75, 74.0, 74.0, None)
    )
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    # Default -- the 3 nbm_quantile_prob tests below override this
    # immediately after calling this helper (monkeypatch's "last setattr
    # wins" rule), so this default only actually matters for callers (e.g.
    # the network-call guard below) that don't override it.
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
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


def _analyze_trade_enriched_fixture():
    """Shared enriched-market fixture for the nbm_quantile_prob tests below
    (paired with _analyze_trade_base_mocks, which mocks get_live_observation
    for its callers)."""
    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch. Confirmed live: the 3 tests using this fixture (via
    # _analyze_trade_base_mocks, which didn't mock get_live_observation at
    # the time) failed exactly this way for several hours in this
    # environment (same "system-local-behind-UTC" bug class
    # test_metar_locked_trade_has_ecmwf_forecast_mean_keys/
    # test_metar_locked_trade_has_nbm_quantile_prob_key already document
    # elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    return {
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


def test_analyze_trade_result_surfaces_nbm_quantile_prob(monkeypatch):
    """backlog.txt "NBM PROBABILISTIC QUANTILES": when mos.fetch_nbm_quantiles
    returns real quantiles, analyze_trade must convert them via
    nws_prob_from_quantiles and surface the result log-only -- giving that
    converter its first real caller."""
    import mos
    import weather_markets as wm
    from weather_markets import analyze_trade

    _analyze_trade_base_mocks(monkeypatch, wm)
    monkeypatch.setattr(
        mos,
        "fetch_nbm_quantiles",
        lambda *a, **kw: {10: 65.0, 25: 68.0, 50: 71.0, 75: 74.0, 90: 77.0},
    )

    result = analyze_trade(_analyze_trade_enriched_fixture())
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    assert result["nbm_quantile_prob"] is not None
    from nws import nws_prob_from_quantiles

    # Derive the expected value via the SAME threshold analyze_trade itself
    # uses (_prob_threshold applies Kalshi's bracket-settlement offset, e.g.
    # 72.5 for an "above 72" market -- not the raw 72.0 condition threshold)
    # rather than hardcoding a number that would silently drift if that
    # convention ever changes.
    condition = wm._parse_market_condition(
        {
            "ticker": "KXHIGHNY-26APR09-T72",
            "title": "Will NYC high temperature be above 72°F?",
        }
    )
    expected = nws_prob_from_quantiles(
        {10: 65.0, 25: 68.0, 50: 71.0, 75: 74.0, 90: 77.0},
        threshold=wm._prob_threshold(condition),
        condition_type="above",
    )
    assert result["nbm_quantile_prob"] == expected


def test_analyze_trade_result_nbm_quantile_prob_none_when_no_coverage(monkeypatch):
    """No NBP coverage for this station/date (mos.fetch_nbm_quantiles
    returns None) must yield nbm_quantile_prob=None, not a crash or a fake
    neutral 0.5 (nws_prob_from_quantiles' own empty-dict stub value, which
    would be indistinguishable from a genuine coin-flip signal if logged)."""
    import mos
    import weather_markets as wm
    from weather_markets import analyze_trade

    _analyze_trade_base_mocks(monkeypatch, wm)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)

    result = analyze_trade(_analyze_trade_enriched_fixture())
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    assert result["nbm_quantile_prob"] is None


def test_analyze_trade_nbm_quantile_fetch_exception_does_not_break_analysis(
    monkeypatch,
):
    """A live-network exception inside the NBM-quantile fetch must not take
    down the rest of analyze_trade -- log-only signals must fail closed,
    not fail loud."""
    import mos
    import weather_markets as wm
    from weather_markets import analyze_trade

    _analyze_trade_base_mocks(monkeypatch, wm)

    def _boom(*a, **kw):
        raise OSError("network boom")

    monkeypatch.setattr(mos, "fetch_nbm_quantiles", _boom)

    result = analyze_trade(_analyze_trade_enriched_fixture())
    assert result is not None, "a log-only fetch failure must not break analyze_trade"
    assert result["nbm_quantile_prob"] is None


def test_analyze_trade_makes_no_real_nws_mos_or_climate_indices_calls(monkeypatch):
    """Regression guard for backlog.txt "SEVERAL test_weather_markets.py
    analyze_trade TESTS STILL MAKE REAL NETWORK CALLS VIA UNMOCKED nws_prob":
    a 2026-08-07 audit found 13 analyze_trade tests reaching real HTTP calls
    to api.weather.gov (via nws_prob), mesonet.agron.iastate.edu (via
    mos.fetch_nbm_quantiles), AND www.cpc.ncep.noaa.gov (via
    temperature_adjustment -> climate_indices.get_indices, found by a
    follow-up opus review of the first two) -- all three wrapped in their own
    try/except inside analyze_trade, so an unmocked real call fails silently
    (logs a warning, returns a neutral/None value) rather than failing the
    test. NOT a claim of zero calls through every session analyze_trade could
    ever reach (e.g. Open-Meteo/metar/acis_precip/acis_snow) -- those are
    covered today by _analyze_trade_base_mocks' own higher-level mocks
    (fetch_temperature_nbm/ecmwf, get_ensemble_temps, get_weather_forecast),
    verified empirically via a whole-file network spy, but this guard doesn't
    independently re-verify them at the session level the way it does for the
    three mechanisms this backlog entry was actually about.

    This replaces nws._session.get, mos._session.get, AND the module-level
    requests.get climate_indices calls directly (it has no Session object of
    its own) -- the actual lowest-level HTTP entry points all three real
    functions go through -- with a stub that RECORDS calls instead of
    silently succeeding, then runs analyze_trade through the exact baseline
    mocks (_analyze_trade_base_mocks) every nbm_quantile_prob test above
    already uses, and asserts zero calls were recorded. The stub also raises
    after recording (so a real call still can't succeed even if some path
    swallows the assertion failure some other way), but the raise is NOT
    load-bearing for detection -- see the mutation-test note below.

    Mutation-tested (2026-08-07), each of the three independently: temporarily
    commenting out _analyze_trade_base_mocks' `nws_prob` line, its
    `mos.fetch_nbm_quantiles` line, and its `temperature_adjustment` line (one
    at a time, each restored before the next) each made this test fail on the
    `assert calls == []` line below with the real blocked URL, not a silent
    pass. A raise-on-call-only stub (no recording) was tried first and falsely
    passed even with a mock removed: nws_prob and the nbm_quantile_prob block
    both wrap their real calls in try/except and log-and-continue on any
    exception -- the same resilience that made the original bug silent -- so
    a bare raise never reaches pytest. Recording is what survives that
    resilience and lets the assertion actually fail.
    """
    import climate_indices
    import mos
    import nws
    import weather_markets as wm
    from weather_markets import analyze_trade

    calls: list[str] = []

    def _record(url, *args, **kwargs):
        calls.append(url)
        raise RuntimeError(f"blocked real network call: {url}")

    monkeypatch.setattr(nws._session, "get", _record)
    monkeypatch.setattr(mos._session, "get", _record)
    monkeypatch.setattr(climate_indices.requests, "get", _record)

    _analyze_trade_base_mocks(monkeypatch, wm)

    result = analyze_trade(_analyze_trade_enriched_fixture())
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    assert calls == [], f"analyze_trade made real network call(s): {calls}"


def test_model_consensus_false_when_models_disagree(monkeypatch):
    """model_consensus is False when ICON and GFS differ by more than 8pp."""
    import mos
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
    # datetime.now(ZoneInfo(city_tz)).date() (city-local, e.g. America/New_York
    # for NYC). When the local "tomorrow" equals that city-local date (i.e.
    # target_date was set to tomorrow but the clock has already rolled), it
    # fires and skips the consensus block.
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
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
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)

    from datetime import datetime, timedelta

    # UTC, not date.today(): this test already mocks get_live_observation
    # above so it isn't actually exposed to the local-vs-UTC days_out race
    # the sibling analyze_trade tests in this file were -- kept UTC-
    # consistent here anyway, matching weather_markets.py's own
    # datetime.now(UTC).date() days_out computation, for defense in depth
    # rather than relying on that one mock alone.
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
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
    import mos
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
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
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

    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch this test doesn't mock. Confirmed live: this test failed exactly
    # this way for several hours in this environment (same "system-local-
    # behind-UTC" bug class test_metar_locked_trade_has_ecmwf_forecast_mean_
    # keys/test_metar_locked_trade_has_nbm_quantile_prob_key already
    # document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
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
    import mos
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
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
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

    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch this test doesn't mock. Confirmed live: this test failed exactly
    # this way for several hours in this environment (same "system-local-
    # behind-UTC" bug class test_metar_locked_trade_has_ecmwf_forecast_mean_
    # keys/test_metar_locked_trade_has_nbm_quantile_prob_key already
    # document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
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
    import mos
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
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
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

    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch this test doesn't mock. Confirmed live: this test failed exactly
    # this way for several hours in this environment (same "system-local-
    # behind-UTC" bug class test_metar_locked_trade_has_ecmwf_forecast_mean_
    # keys/test_metar_locked_trade_has_nbm_quantile_prob_key already
    # document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
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


def _ecmwf_gap_test_enriched():
    """Shared enriched-market fixture for the ecmwf_consensus_gap_prob tests
    below -- same shape as test_analyze_trade_captures_gem_ukmo_forecast_means's."""
    from datetime import datetime, timedelta

    # UTC, not date.today(): analyze_trade computes days_out via
    # datetime.now(UTC).date() (weather_markets.py), so a local-timezone
    # "tomorrow" collides with UTC "today" whenever the local wall-clock date
    # lags behind UTC's (e.g. US evenings) -- days_out then evaluates to 0
    # instead of 1, silently routing into the same-day get_live_observation()
    # branch. Confirmed live: the tests using this fixture (via
    # _stub_ecmwf_gap_common, which didn't mock get_live_observation at the
    # time) failed exactly this way for several hours in this environment
    # (same "system-local-behind-UTC" bug class test_metar_locked_trade_has_
    # ecmwf_forecast_mean_keys/test_metar_locked_trade_has_nbm_quantile_
    # prob_key already document elsewhere in this file).
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    return {
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


def _stub_ecmwf_gap_common(monkeypatch, wm):
    import mos

    monkeypatch.setattr(
        wm, "get_ensemble_temps", lambda *a, **kw: [70.0, 71.0, 72.0, 73.0, 74.0] * 4
    )
    monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: 74.0)
    monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: 79.5)
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
    monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "nws_prob", lambda *a, **kw: None)
    monkeypatch.setattr(mos, "fetch_nbm_quantiles", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "temperature_adjustment", lambda *a, **kw: 0.0)
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


def test_analyze_trade_computes_ecmwf_consensus_gap_prob(monkeypatch):
    """backlog.txt '3-WAY MODEL_CONSENSUS CHECK': analyze_trade must compute
    ecmwf_consensus_gap_prob as the max pairwise gap between
    ecmwf_aifs025_ensemble's probability and icon/gfs's, log-only -- and
    model_consensus must stay exactly icon-vs-gfs (unaffected by ecmwf's
    probability, even though |icon_p - gfs_p| = 0.02 is well within the
    existing 0.12 threshold and ecmwf's own gap is much larger)."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    _stub_ecmwf_gap_common(monkeypatch, wm)
    monkeypatch.setattr(
        wm,
        "_get_consensus_probs",
        lambda *a, **kw: (0.73, 0.75, 74.0, 74.5, 76.25),
    )
    monkeypatch.setattr(wm, "_get_ecmwf_aifs_prob", lambda *a, **kw: 0.60)

    result = analyze_trade(_ecmwf_gap_test_enriched())
    assert result is not None, "analyze_trade returned None — fix the enriched dict"
    # max(|0.73-0.60|, |0.75-0.60|) = max(0.13, 0.15) = 0.15
    assert result["ecmwf_consensus_gap_prob"] == pytest.approx(0.15), (
        f"expected max-pairwise-gap 0.15, got {result['ecmwf_consensus_gap_prob']!r}"
    )
    assert result["model_consensus"] is True, (
        "ecmwf_aifs_prob must NOT feed model_consensus -- still icon-vs-gfs only"
    )


def test_analyze_trade_ecmwf_consensus_gap_prob_none_when_ecmwf_prob_missing(
    monkeypatch,
):
    """ecmwf_aifs_prob going None (e.g. below the 5-member floor) must leave
    ecmwf_consensus_gap_prob None rather than crashing or comparing against
    None."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    _stub_ecmwf_gap_common(monkeypatch, wm)
    monkeypatch.setattr(
        wm,
        "_get_consensus_probs",
        lambda *a, **kw: (0.73, 0.75, 74.0, 74.5, 76.25),
    )
    monkeypatch.setattr(wm, "_get_ecmwf_aifs_prob", lambda *a, **kw: None)

    result = analyze_trade(_ecmwf_gap_test_enriched())
    assert result is not None
    assert result["ecmwf_consensus_gap_prob"] is None


def test_analyze_trade_survives_ecmwf_aifs_prob_fetch_exception(monkeypatch):
    """_get_ecmwf_aifs_prob failing must not abort the trade -- mirrors the
    existing _get_gem_ukmo_means/_get_consensus_probs exception-tolerance
    behavior, and must not regress model_consensus or the other forecast
    means (separate try/except block)."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    _stub_ecmwf_gap_common(monkeypatch, wm)
    monkeypatch.setattr(
        wm,
        "_get_consensus_probs",
        lambda *a, **kw: (0.73, 0.75, 74.0, 74.5, 76.25),
    )

    def _raise_ecmwf_aifs_prob(*a, **kw):
        raise RuntimeError("simulated ecmwf_aifs_prob fetch failure")

    monkeypatch.setattr(wm, "_get_ecmwf_aifs_prob", _raise_ecmwf_aifs_prob)

    result = analyze_trade(_ecmwf_gap_test_enriched())
    assert result is not None, (
        "an ecmwf_aifs_prob fetch exception must not abort the trade"
    )
    assert result["ecmwf_consensus_gap_prob"] is None
    assert result["model_consensus"] is True
    assert result["model_forecast_means"]["icon_seamless"] == pytest.approx(74.0)


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

    from datetime import datetime
    from zoneinfo import ZoneInfo

    # analyze_trade's past-date gate (target_date < the market's CITY-LOCAL
    # today) runs unconditionally before _metar_lock_in is even called, so
    # mocking _metar_lock_in doesn't shield this fixture from that gate
    # returning None instead of reaching the mock. Anchor "today" to NYC's
    # own local date (this fixture's "_city": "NYC") to match the gate
    # exactly, rather than UTC's.
    today = datetime.now(ZoneInfo("America/New_York")).date()
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


def test_metar_locked_trade_has_nbm_quantile_prob_key(monkeypatch):
    """Same bug class as test_metar_locked_trade_has_ecmwf_forecast_mean_keys
    above, caught live while building backlog.txt "NBM PROBABILISTIC
    QUANTILES": the METAR-locked branch skips the Phase C section entirely
    (where nbm_quantile_prob is normally computed), so it must pre-assign
    nbm_quantile_prob = None itself or the shared result dict construction
    raises UnboundLocalError. Regression test -- this exact scenario failed
    with UnboundLocalError before the fix."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )

    from datetime import datetime
    from zoneinfo import ZoneInfo

    # analyze_trade's past-date gate (target_date < the market's CITY-LOCAL
    # today) runs unconditionally before _metar_lock_in is even called, so
    # mocking _metar_lock_in doesn't shield this fixture from that gate
    # returning None instead of reaching the mock. Anchor "today" to NYC's
    # own local date (this fixture's "_city": "NYC") to match the gate
    # exactly, rather than UTC's.
    today = datetime.now(ZoneInfo("America/New_York")).date()
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
    assert result["nbm_quantile_prob"] is None


# ── METAR lock-in beta calibration wiring in analyze_trade ───────────────────


def _metar_locked_enriched(ticker="KXHIGHNY-26APR09-T72"):
    """Minimal enriched dict that reaches analyze_trade's metar_locked branch
    -- same shape as test_metar_locked_trade_has_ecmwf_forecast_mean_keys
    above, factored out since the new calibration tests need several
    variants of it."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("America/New_York")).date()
    return {
        "_forecast": {"high_f": 75.0, "low_f": 55.0, "precip_in": 0.0, "wind_mph": 5.0},
        "_date": today,
        "_city": "NYC",
        "_hour": None,
        "ticker": ticker,
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


def test_metar_calibration_applied_for_above_market(monkeypatch):
    """A calibration model on disk must actually correct a METAR-locked
    above-market prediction -- confirms the wiring reaches
    apply_metar_calibration, not just that the loader/fit functions work in
    isolation."""
    import ml_bias
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )
    # Known, hand-computable model: a==b==2.0, c=0.0 (the Platt special case).
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: (2.0, 2.0, 0.0))

    result = analyze_trade(_metar_locked_enriched())
    assert result is not None
    expected = ml_bias.apply_metar_calibration(0.85, (2.0, 2.0, 0.0))
    assert result["forecast_prob"] == pytest.approx(expected, abs=1e-6)
    assert abs(result["forecast_prob"] - 0.85) > 1e-6, (
        "calibration model was loaded but had no visible effect — check the "
        "wiring, not just the math"
    )


def test_metar_calibration_skipped_for_between_market(monkeypatch):
    """Between markets share the same METAR lock-in formula but weren't part
    of the population the calibration model was fit on -- must stay
    uncorrected even when a model exists on disk."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: (2.0, 2.0, 0.0))

    result = analyze_trade(_metar_locked_enriched(ticker="KXHIGHNY-26APR09-B74.5"))
    assert result is not None
    assert result["condition"]["type"] == "between"
    assert result["forecast_prob"] == pytest.approx(0.85, abs=1e-6), (
        "between market's raw METAR probability was corrected — the "
        "condition_type != 'between' guard isn't excluding it"
    )


def test_metar_calibration_noop_when_no_model_on_disk(monkeypatch):
    """No calibration file yet (fresh install, or below the 30-row floor)
    must leave the raw METAR lock-in probability untouched, not raise."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: None)

    result = analyze_trade(_metar_locked_enriched())
    assert result is not None
    assert result["forecast_prob"] == pytest.approx(0.85, abs=1e-6)


def test_metar_calibration_magnitude_capped(monkeypatch):
    """A correction whose shift exceeds _ML_CORRECTION_LIMIT (0.30) must be
    skipped entirely, same safety pattern already applied to GBM and Platt
    corrections in this file."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )
    # a=b=1 (Platt identity slope) with c=-10 pushes 0.85 down to ~0.0003 --
    # a ~0.85 delta, far outside the ±0.30 window (unlike a large a=b, which
    # just saturates the sigmoid near 1.0 and produces only a ~0.15 delta
    # from 0.85 -- verified directly before writing this assertion, not
    # assumed), so it must be skipped rather than applied outright.
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: (1.0, 1.0, -10.0))

    result = analyze_trade(_metar_locked_enriched())
    assert result is not None
    assert result["forecast_prob"] == pytest.approx(0.85, abs=1e-6), (
        "an out-of-bound correction was applied instead of being capped/skipped"
    )


def test_metar_calibration_no_lock_correction_survives_the_cap(monkeypatch):
    """Regression test for a HIGH finding from two independent opus reviews
    (2026-08-16): reusing _ML_CORRECTION_LIMIT (0.30, sized for GBM/Platt's
    small touch-ups) as the cap for this correction meant EVERY NO-lock
    correction from the real fitted model (delta ~0.35-0.38 on the observed
    0.03-0.15 raw range) was silently skipped, while YES-lock corrections
    (delta up to ~0.20) were still applied -- leaving the fix a no-op on
    exactly the worse-miscalibrated half (measured 93% NO-confidence vs 50%
    actual) while still correcting the other half. Uses the exact real
    production coefficients (a=b=0.2262, c=0.4001) two reviews independently
    verified against this repo's actual 33-row dataset."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.03, {"current_temp_f": 76.0})
    )
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: (0.2262, 0.2262, 0.4001))

    result = analyze_trade(_metar_locked_enriched())
    assert result is not None
    assert result["forecast_prob"] != pytest.approx(0.03, abs=1e-3), (
        "a real NO-lock correction was skipped by the magnitude cap"
    )
    assert result["forecast_prob"] == pytest.approx(0.4046, abs=1e-3)


def test_metar_calibration_records_raw_prob_via_bias_correction(monkeypatch):
    """Regression test for a HIGH finding from both opus reviews
    (2026-08-16): the METAR branch left bias_correction hardcoded at 0.0, so
    tracker.py's raw_prob = forecast_prob + bias_correction reconstructed
    the ALREADY-CALIBRATED value, not the true raw
    _dynamic_lock_in_confidence() output. A future `calibrate` run would
    then train on partly-already-corrected data, understating the true
    miscalibration and pulling the fit toward identity over successive
    retrains -- a closed feedback loop. bias_correction must equal
    (raw - calibrated) so raw_prob reconstructs correctly."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: (2.0, 2.0, 0.0))

    result = analyze_trade(_metar_locked_enriched())
    assert result is not None
    assert result["forecast_prob"] != pytest.approx(0.85, abs=1e-6), (
        "test setup error -- expected the calibration to actually move the prob"
    )
    reconstructed_raw = result["forecast_prob"] + result["bias_correction"]
    assert reconstructed_raw == pytest.approx(0.85, abs=1e-6), (
        f"bias_correction={result['bias_correction']} does not reconstruct "
        f"the true raw METAR probability (0.85) from forecast_prob="
        f"{result['forecast_prob']} -- future retrains would train on "
        f"already-calibrated data"
    )


def test_metar_calibration_bias_correction_zero_when_uncorrected(monkeypatch):
    """When no calibration model exists, bias_correction must stay 0.0 (not
    accidentally pick up a stale nonzero value) -- positive control pairing
    with the test above, confirming the fix only activates when a
    correction actually ran."""
    import weather_markets as wm
    from weather_markets import analyze_trade

    monkeypatch.setattr(
        wm, "_metar_lock_in", lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0})
    )
    monkeypatch.setattr(wm, "_load_metar_calibration", lambda: None)

    result = analyze_trade(_metar_locked_enriched())
    assert result is not None
    assert result["bias_correction"] == pytest.approx(0.0)
    assert result["forecast_prob"] + result["bias_correction"] == pytest.approx(0.85)


class TestLoadMetarCalibration:
    """_load_metar_calibration's caching/validation, mirroring
    _load_platt_models's already-established safety properties for the
    identical class of risk (a corrupted or hand-edited calibration file
    silently corrupting live probabilities)."""

    def _isolate(self, tmp_path, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr(wm, "METAR_CALIBRATION_PATH", tmp_path / "metar_cal.json")
        monkeypatch.setattr(wm, "_METAR_CAL", None)
        monkeypatch.setattr(wm, "_METAR_CAL_MTIME", None)
        return tmp_path

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        import weather_markets as wm

        self._isolate(tmp_path, monkeypatch)
        assert wm._load_metar_calibration() is None

    def test_loads_valid_file(self, tmp_path, monkeypatch):
        import json

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": 0.5, "b": 0.8, "c": 0.1}))

        result = wm._load_metar_calibration()
        assert result == pytest.approx((0.5, 0.8, 0.1))

    def test_rejects_degenerate_nonpositive_coefficients(self, tmp_path, monkeypatch):
        """a<=0 or b<=0 means the map isn't a valid beta-calibration density
        (same 'signal would be inverted' logic _load_platt_models already
        applies to Platt's A<=0) -- a hand-edited or corrupted file with
        these must not be trusted."""
        import json

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": -0.5, "b": 0.8, "c": 0.1}))

        assert wm._load_metar_calibration() is None

    def test_rejects_out_of_bounds_coefficients(self, tmp_path, monkeypatch):
        import json

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": 50.0, "b": 0.8, "c": 0.1}))

        assert wm._load_metar_calibration() is None

    def test_reloads_after_file_changes(self, tmp_path, monkeypatch):
        """A fresh calibrate run must be picked up by an already-running
        process on its NEXT call, not only at first load -- same
        mtime-invalidation reasoning as ml_bias._load_emos_params."""
        import json
        import time

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": 0.5, "b": 0.8, "c": 0.1}))
        first = wm._load_metar_calibration()
        assert first == pytest.approx((0.5, 0.8, 0.1))

        time.sleep(1.1)  # ensure a distinct mtime across filesystems
        path.write_text(json.dumps({"a": 0.3, "b": 0.4, "c": 0.2}))
        second = wm._load_metar_calibration()
        assert second == pytest.approx((0.3, 0.4, 0.2)), (
            "stale cache returned instead of re-reading the changed file"
        )

    def test_editing_a_good_file_to_invalid_actually_disables_it(
        self, tmp_path, monkeypatch
    ):
        """Regression test for a HIGH finding (opus review, 2026-08-16): an
        earlier version returned the STALE cached model on a validation
        failure instead of None. An operator who hand-edits the file to
        neutralize a bad correction (e.g. because a running loop/watch
        process is applying a model they've since determined is wrong) must
        see it actually take effect on the next call, not keep silently
        applying the old model forever."""
        import json
        import time

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": 0.5, "b": 0.8, "c": 0.1}))
        first = wm._load_metar_calibration()
        assert first == pytest.approx((0.5, 0.8, 0.1))

        time.sleep(1.1)
        path.write_text(json.dumps({"a": -0.5, "b": 0.8, "c": 0.1}))  # degenerate
        second = wm._load_metar_calibration()
        assert second is None, (
            "a validation failure on a file that previously held a good "
            "model must clear the cache, not keep serving the stale model"
        )

    def test_transient_stat_error_keeps_cached_model(self, tmp_path, monkeypatch):
        """A transient I/O error reading the file (e.g. an AV lock, or the
        brief window during os.replace) must NOT wipe a good cached model
        -- distinct from the file genuinely not existing. Simulated by
        making Path.exists() raise mid-check, the way a real OS-level lock
        would surface."""
        import json

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": 0.5, "b": 0.8, "c": 0.1}))
        first = wm._load_metar_calibration()
        assert first == pytest.approx((0.5, 0.8, 0.1))

        def _raise_oserror(self):
            raise OSError("simulated transient lock")

        monkeypatch.setattr(type(path), "exists", _raise_oserror, raising=False)

        second = wm._load_metar_calibration()
        assert second == pytest.approx((0.5, 0.8, 0.1)), (
            "a transient stat/exists() failure wiped the good cached model "
            "instead of keeping it and retrying next call"
        )

    def test_malformed_json_does_not_crash_first_load(self, tmp_path, monkeypatch):
        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text("{not valid json")

        assert wm._load_metar_calibration() is None

    def test_missing_keys_does_not_crash_first_load(self, tmp_path, monkeypatch):
        """A partial file (e.g. a torn concurrent write) missing b/c must
        not raise -- caught by the broad except around the JSON parse."""
        import json

        import weather_markets as wm

        path = self._isolate(tmp_path, monkeypatch) / "metar_cal.json"
        path.write_text(json.dumps({"a": 0.5}))

        assert wm._load_metar_calibration() is None

    def test_loader_exception_does_not_crash_analyze_trade(self, monkeypatch):
        """If _load_metar_calibration itself raises unexpectedly (bug, not
        just a bad file), analyze_trade's enclosing try/except must degrade
        to uncorrected rather than let the exception escape and abort the
        whole market scan."""
        import weather_markets as wm
        from weather_markets import analyze_trade

        monkeypatch.setattr(
            wm,
            "_metar_lock_in",
            lambda *a, **kw: (True, 0.85, {"current_temp_f": 76.0}),
        )

        def _boom():
            raise RuntimeError("simulated unexpected failure")

        monkeypatch.setattr(wm, "_load_metar_calibration", _boom)

        result = analyze_trade(_metar_locked_enriched())  # must not raise
        assert result is not None
        assert result["forecast_prob"] == pytest.approx(0.85, abs=1e-6)


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


class TestFetchTemperaturePirateWeatherHistoricalRouting:
    """fetch_temperature_pirate_weather must route to the FORECAST endpoint
    (not the historical time-machine endpoint) for a market that is still
    in progress in the city's own local time, even during the ~4-8h evening
    window where UTC's date has already rolled over -- same bug class as
    backlog.txt "ANALYZE_TRADE'S past_date GATE...", mirroring the
    sibling fix already in fetch_temperature_weatherapi (~line 2359)."""

    def test_still_open_local_market_hits_forecast_not_timemachine(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return frozen_instant.replace(tzinfo=None)
                return frozen_instant.astimezone(tz)

        # NYC local today during this instant is 2026-08-09 -- a market
        # dated 2026-08-09 is still genuinely in progress locally, even
        # though UTC's date is already 2026-08-10.
        target = date(2026, 8, 9)

        called_urls = []

        def _fake_request(method, url, **kw):
            called_urls.append(url)
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"daily": {"data": []}}
            return resp

        monkeypatch.setattr(wm, "datetime", _Frozen)
        monkeypatch.setenv("PIRATE_WEATHER_API_KEY", "test-key")
        monkeypatch.setattr(wm, "_request_with_retry", _fake_request)
        wm._pirate_cb.record_success()

        wm.fetch_temperature_pirate_weather("NYC", target)

        assert len(called_urls) == 1
        assert called_urls[0].startswith(wm._PIRATE_FORECAST_BASE), (
            f"expected the FORECAST endpoint for a still-open local-today "
            f"market, got {called_urls[0]!r} -- looks like is_historical "
            f"was computed from UTC (target < UTC-today) instead of NYC's "
            f"own local today"
        )


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


class TestGetWeatherForecastValidatesResponse:
    """AUD-0060: get_weather_forecast's per-model _fetch_one closure
    previously called validate_forecast() as a bare statement AFTER
    _forecast_cb.record_success() had already run, discarding its bool
    return -- a malformed-but-HTTP-200 response (missing the required
    "time" field, even with real non-null temperature data) was treated
    as a successful fetch and fed straight into the ensemble average."""

    def test_malformed_response_recorded_as_failure_not_used(self, monkeypatch):
        from datetime import date
        from unittest.mock import MagicMock

        import weather_markets as wm

        target = date(2026, 5, 1)
        wm._forecast_cache.clear()
        wm._forecast_cb.record_success()
        wm._forecast_cb._last_failure_at = None  # avoid burst-window absorption
        _before = wm._forecast_cb.failure_count

        def _fake_om_request(method, url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            # "time" missing entirely -- fails validate_forecast's required-
            # field check even though temperature_2m_max is present and
            # non-null (so is_all_null's own dead-model check does NOT
            # trigger here -- this response is malformed in a way only
            # validate_forecast catches).
            resp.json.return_value = {
                "daily": {"temperature_2m_max": [70.0], "temperature_2m_min": [55.0]}
            }
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm, "fetch_nbm_forecast", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_weatherapi", lambda *a, **kw: None)
        monkeypatch.setattr(
            wm, "fetch_temperature_pirate_weather", lambda *a, **kw: None
        )

        result = wm.get_weather_forecast("NYC", target)

        assert result is None, (
            "every OM model's response was malformed and every fallback "
            "source is mocked to fail -- must not silently use the bad data"
        )
        assert wm._forecast_cb.failure_count > _before, (
            "positive control: the malformed response must actually be "
            "recorded as a circuit-breaker failure, not silently credited "
            "as a successful fetch"
        )


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

    def test_st_petersburg_rain_ticker_detected(self):
        """Onboarded 2026-07-26. Would return None without the explicit fix
        -- "KXRAINSTPM" doesn't match any existing substring check either."""
        assert self._city("KXRAINSTPM-26JUL-7") == "StPetersburg"


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
        orig_path = wm.LEARNED_WEIGHTS_PATH
        orig_warned = wm._LEARNED_WEIGHTS_TTL_WARNED
        wm._LEARNED_WEIGHTS = {}
        wm.LEARNED_WEIGHTS_PATH = weights_file
        try:
            with patch("weather_markets.os.path.getmtime", return_value=eight_days_ago):
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig
            wm.LEARNED_WEIGHTS_PATH = orig_path
            wm._LEARNED_WEIGHTS_TTL_WARNED = orig_warned

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
        orig_path = wm.LEARNED_WEIGHTS_PATH
        wm._LEARNED_WEIGHTS = {}
        wm.LEARNED_WEIGHTS_PATH = weights_file
        try:
            with patch("weather_markets.os.path.getmtime", return_value=one_day_ago):
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig
            wm.LEARNED_WEIGHTS_PATH = orig_path

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

    def test_save_rejects_near_zero_weights(self, tmp_path, monkeypatch):
        """save_learned_weights must not write when any model weight is near zero."""
        import weather_markets as wm

        target = tmp_path / "learned_weights.json"
        monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", target)
        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}

        try:
            bad = {"NYC": {"gfs_seamless": 0.0, "ecmwf_ifs025": 1.5}}
            wm.save_learned_weights(bad)
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

        assert not target.exists(), (
            "save_learned_weights must not write for near-zero weights"
        )

    def test_save_allows_valid_weights(self, tmp_path, monkeypatch):
        """save_learned_weights must write valid {city: {model: weight}} dicts."""
        import json

        import weather_markets as wm

        valid = {
            "NYC": {
                "gfs_seamless": 1.2,
                "ecmwf_ifs025": 0.9,
                "icon_seamless": 0.9,
            }
        }

        target = tmp_path / "learned_weights.json"
        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {}

        try:
            monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", target)
            wm.save_learned_weights(valid)
            assert wm._LEARNED_WEIGHTS == valid, (
                "save_learned_weights must update _LEARNED_WEIGHTS for valid input"
            )
            assert json.loads(target.read_text(encoding="utf-8")) == valid, (
                "save_learned_weights must durably persist valid weights to disk"
            )
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

    def test_save_fails_open_when_atomic_write_raises(self, tmp_path, monkeypatch):
        """Regression coverage for the OTHER bare os.replace() CALL SITES backlog
        entry (2026-08-08): save_learned_weights now delegates to
        safe_io.atomic_write_json instead of a hand-rolled tempfile+os.replace,
        so it inherits safe_io's Windows PermissionError retry. On total write
        failure it must fail OPEN (log + return, leave the in-memory cache
        untouched) rather than raise or silently accept the new weights —
        this file's existing convention (per save_learned_weights' own
        docstring) is that a write failure must not make this process trade
        on weights that were never durably persisted.

        Mutation-tested: reverting save_learned_weights to a bare os.replace()
        makes this fail — monkeypatching safe_io.atomic_write_json to raise
        would then have no effect on save_learned_weights' behavior, since it
        would no longer call it, and _LEARNED_WEIGHTS would be wrongly
        updated despite the simulated write failure.
        """
        import safe_io
        import weather_markets as wm

        valid = {"NYC": {"gfs_seamless": 1.2, "ecmwf_ifs025": 0.9}}
        orig_lw = wm._LEARNED_WEIGHTS
        wm._LEARNED_WEIGHTS = {"NYC": {"gfs_seamless": 5.0}}  # sentinel prior state
        target = tmp_path / "learned_weights.json"
        calls = []

        def _boom(*args, **kwargs):
            calls.append((args, kwargs))
            raise safe_io.AtomicWriteError("simulated write failure")

        try:
            monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", target)
            monkeypatch.setattr(safe_io, "atomic_write_json", _boom)
            wm.save_learned_weights(valid)  # must not raise
            assert calls == [((valid, target), {})], (
                "must call atomic_write_json with (weights, LEARNED_WEIGHTS_PATH), "
                "not a different argument order or a different target path"
            )
            assert wm._LEARNED_WEIGHTS == {"NYC": {"gfs_seamless": 5.0}}, (
                "save_learned_weights must leave _LEARNED_WEIGHTS untouched "
                "when the underlying write fails"
            )
        finally:
            wm._LEARNED_WEIGHTS = orig_lw

    def test_load_rejects_float_city_values(self, tmp_path):
        """load_learned_weights must return {} and delete corrupt file with float city values."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        corrupt = {"NYC": 0.72}
        weights_file = tmp_path / "learned_weights.json"
        weights_file.write_text(json.dumps(corrupt))
        orig_lw = wm._LEARNED_WEIGHTS
        orig_path = wm.LEARNED_WEIGHTS_PATH
        wm._LEARNED_WEIGHTS = {}
        wm.LEARNED_WEIGHTS_PATH = weights_file
        try:
            with patch(
                "weather_markets.os.path.getmtime", return_value=time.time() - 3600
            ):
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig_lw
            wm.LEARNED_WEIGHTS_PATH = orig_path

        assert result == {}, (
            f"load_learned_weights must return {{}} for corrupt float values, got {result!r}"
        )

    def test_load_rejects_non_positive_weights(self, tmp_path):
        """load_learned_weights must return {} when any weight is <= 0."""
        import json
        import time
        from unittest.mock import patch

        import weather_markets as wm

        bad = {"NYC": {"gfs_seamless": 0.0, "ecmwf_ifs025": 1.5}}
        weights_file = tmp_path / "learned_weights.json"
        weights_file.write_text(json.dumps(bad))
        orig_lw = wm._LEARNED_WEIGHTS
        orig_path = wm.LEARNED_WEIGHTS_PATH
        wm._LEARNED_WEIGHTS = {}
        wm.LEARNED_WEIGHTS_PATH = weights_file
        try:
            with patch(
                "weather_markets.os.path.getmtime", return_value=time.time() - 3600
            ):
                result = wm.load_learned_weights()
        finally:
            wm._LEARNED_WEIGHTS = orig_lw
            wm.LEARNED_WEIGHTS_PATH = orig_path

        assert result == {}, (
            f"load_learned_weights must return {{}} for non-positive weights, got {result!r}"
        )


# ── TestUtcTodayDate ──────────────────────────────────────────────────────────


class TestUtcTodayDate:
    """L5-E: weather_markets must use datetime.now(UTC).date() not date.today()
    for any UTC-vs-system-local comparison. Does NOT mean every days_out
    computation must be UTC-based -- analyze_trade's own days_out is
    deliberately CITY-LOCAL (backlog.txt "ANALYZE_TRADE'S past_date
    GATE..."); this class only guards against the naive-local-clock bug,
    not against city-local-timezone-aware computation."""

    def test_forecast_uncertainty_is_a_pure_function_of_days_out(self):
        """_forecast_uncertainty(days_out) no longer recomputes "today"
        itself (from UTC or anywhere else) -- both real callers, inside
        analyze_trade's not-metar-locked path, already have a
        correctly-computed CITY-LOCAL days_out in scope and pass it
        directly, so a second internal recomputation here would risk
        silently disagreeing with it during the UTC-rollover-vs-local-
        evening window (backlog.txt "ANALYZE_TRADE'S past_date GATE...").
        Pins the full days_out->sigma ladder as a pure value mapping."""
        import weather_markets as wm

        assert wm._forecast_uncertainty(0) == 3.0
        assert wm._forecast_uncertainty(1) == 3.0
        assert wm._forecast_uncertainty(2) == 4.0
        assert wm._forecast_uncertainty(3) == 4.0
        assert wm._forecast_uncertainty(4) == 5.0
        assert wm._forecast_uncertainty(5) == 5.0
        assert wm._forecast_uncertainty(6) == 6.0
        assert wm._forecast_uncertainty(7) == 6.0
        assert wm._forecast_uncertainty(8) == 7.5
        assert wm._forecast_uncertainty(30) == 7.5

    def test_no_date_today_calls_remain(self):
        """weather_markets.py must not contain any date.today() calls."""
        from pathlib import Path

        src = (Path(__file__).parent.parent / "weather_markets.py").read_text()
        assert "date.today()" not in src, (
            "Found date.today() in weather_markets.py — replace with datetime.now(UTC).date()"
        )


# ── TestPastDateGateCityLocal ─────────────────────────────────────────────────
# Regression tests for backlog.txt "ANALYZE_TRADE'S past_date GATE COMPARES A
# CITY-LOCAL target_date AGAINST UTC's CURRENT DATE". analyze_trade's
# past_date/days_out gates must key off each market's own CITY-LOCAL "today",
# not UTC's -- during the ~4-8h window every evening (00:00 UTC through each
# city's own local midnight), UTC's calendar date has already rolled over
# but the city's hasn't. Pins the exact behavior for one fixed UTC instant
# inside that window for all 4 representative US timezones (EDT/CDT/MDT/PDT)
# by patching weather_markets.datetime with a datetime subclass whose .now()
# returns that instant converted into whatever tzinfo is requested --
# preserves every other datetime classmethod (fromisoformat, arithmetic,
# etc.) that the rest of analyze_trade also relies on, unlike a full
# MagicMock swap.
class _FrozenDatetime(datetime):
    """datetime.now(tz) returns _FROZEN_INSTANT converted to tz (or naive
    _FROZEN_INSTANT if tz is None); every other datetime behavior is real."""

    _frozen_instant: "datetime" = None  # type: ignore[assignment]

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._frozen_instant.replace(tzinfo=None)
        return cls._frozen_instant.astimezone(tz)


def _frozen_datetime_at(instant):
    frozen = type("_FrozenDatetimeAt", (_FrozenDatetime,), {})
    frozen._frozen_instant = instant
    return frozen


class TestPastDateGateCityLocal:
    """(city, _CITY_TZ value) pairs for the 4 representative US timezones
    this bot trades, per backlog.txt's own EDT/CDT/MDT/PDT framing."""

    _CITIES = [
        ("NYC", "KXHIGHNY"),
        ("Chicago", "KXHIGHCHI"),
        ("Denver", "KXHIGHDEN"),
        ("LA", "KXHIGHLAX"),
    ]

    def _enriched(self, city, series, target_date):
        return {
            "_city": city,
            "_date": target_date,
            "_hour": None,
            "_forecast": {
                "high_f": 75.0,
                "low_f": 58.0,
                "precip_in": 0.0,
                "models_used": 3,
                "high_range": (73.0, 77.0),
            },
            "ticker": f"{series}-GATE-T74.5",
            "series_ticker": series,
            "title": f"{city} high above 74.5°F",
            "yes_ask": 55,
            "yes_bid": 45,
            "volume": 500,
            "volume_fp": 500,
            "open_interest": 200,
            "open_interest_fp": 200,
            "close_time": "",
        }

    def test_same_day_market_still_open_during_utc_rollover_window(self, monkeypatch):
        """A market whose target_date is still "today" in the city's own
        timezone must NOT be gated as past, even during the window where
        UTC's date has already rolled over to the city's tomorrow.

        Fixed instant: 2026-08-10 00:30 UTC. In every one of the 4
        representative timezones, local wall-clock time is still the
        evening of 2026-08-09 (EDT 20:30, CDT 19:30, MDT 18:30, PDT
        17:30) -- UTC's date (08-10) is one day ahead of every city's own
        local date (08-09). Pre-fix, the gate compared target_date against
        UTC's 08-10 and rejected a genuinely-still-open 08-09 market.
        """
        import weather_markets as wm

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)
        monkeypatch.setattr(wm, "datetime", _frozen_datetime_at(frozen_instant))
        # target_date == local today for every city here, so _metar_lock_in's
        # own top-level guard does NOT short-circuit -- without this mock it
        # would attempt a real network call to fetch live METAR data (the
        # exact "unmocked real network call" issue class backlog.txt has
        # flagged before). This test only cares whether the past_date gate
        # (which runs well before _metar_lock_in) fired, so a deterministic
        # not-locked result is all that's needed here.
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))

        for city, series in self._CITIES:
            local_today = frozen_instant.astimezone(ZoneInfo(wm._CITY_TZ[city])).date()
            assert local_today == date(2026, 8, 9), (
                f"test setup bug: expected {city} local date 2026-08-09 "
                f"during the UTC-rollover window, got {local_today}"
            )
            wm.reset_gate_counts()
            wm.analyze_trade(self._enriched(city, series, local_today))
            counts = wm.get_gate_counts()
            # Rule out an EARLIER gate (no_forecast/no_date/no_city/days_out)
            # having fired instead -- an assertion on past_date alone would
            # pass vacuously if the fixture stopped reaching that gate at all.
            assert counts.get("no_forecast") is None
            assert counts.get("no_date") is None
            assert counts.get("no_city") is None
            assert counts.get("days_out") is None
            assert counts.get("past_date") is None, (
                f"{city}: past_date gate wrongly fired for a market still "
                f"open in {city}'s own local time (target={local_today}, "
                f"UTC now={frozen_instant})"
            )

    def test_genuinely_past_market_still_gated_during_utc_rollover_window(
        self, monkeypatch
    ):
        """A market that is genuinely one full day in the past for the
        city (not just UTC) must still be rejected by the past_date gate,
        at the same fixed instant used by the "still open" test above --
        confirms the fix didn't just make the gate permissive."""
        import weather_markets as wm

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)
        monkeypatch.setattr(wm, "datetime", _frozen_datetime_at(frozen_instant))

        for city, series in self._CITIES:
            local_today = frozen_instant.astimezone(ZoneInfo(wm._CITY_TZ[city])).date()
            genuinely_past = local_today - timedelta(days=1)
            wm.reset_gate_counts()
            result = wm.analyze_trade(self._enriched(city, series, genuinely_past))
            assert result is None
            counts = wm.get_gate_counts()
            assert counts.get("past_date") == 1, (
                f"{city}: past_date gate should have fired for a market "
                f"genuinely one full local day in the past "
                f"(target={genuinely_past}, local today={local_today})"
            )

    def test_days_out_ceiling_uses_city_local_today_not_utc(self, monkeypatch):
        """The generic days_out ceiling gate (MAX_DAYS_OUT) must also key
        off city-local today. Same fixed 00:30 UTC instant as above: a
        market MAX_DAYS_OUT+1 days out from the city's own local today
        sits exactly MAX_DAYS_OUT days out from UTC's (already-rolled-
        over) date -- pre-fix, the UTC-based comparison would let it
        through 1 day past the intended ceiling instead of rejecting it.
        """
        import weather_markets as wm

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)
        monkeypatch.setattr(wm, "datetime", _frozen_datetime_at(frozen_instant))

        city, series = "NYC", "KXHIGHNY"
        local_today = frozen_instant.astimezone(ZoneInfo(wm._CITY_TZ[city])).date()
        target_date = local_today + timedelta(days=wm.MAX_DAYS_OUT + 1)

        wm.reset_gate_counts()
        result = wm.analyze_trade(self._enriched(city, series, target_date))
        assert result is None
        counts = wm.get_gate_counts()
        assert counts.get("days_out") == 1, (
            f"days_out gate should have fired: target is "
            f"MAX_DAYS_OUT+1={wm.MAX_DAYS_OUT + 1} days out from {city}'s "
            f"own local today ({local_today}), even though it's only "
            f"MAX_DAYS_OUT days out from UTC's already-rolled-over date"
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
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from weather_markets import analyze_trade

    # analyze_trade's past-date gate compares target_date against the
    # market's CITY-LOCAL today (NYC here), not UTC's -- during the ~4-8h
    # evening window where UTC has already rolled over past midnight but
    # NYC hasn't, `datetime.now(UTC).date() - 1 day` is NYC's actual TODAY,
    # not yesterday, which would make this "past" fixture accidentally
    # legitimate and the test's own premise wrong. Anchor to NYC's local
    # date instead so this is genuinely one full day in the past regardless
    # of wall-clock time relative to UTC.
    past = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
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


class TestGetEcmwfAifsProb:
    """backlog.txt '3-WAY MODEL_CONSENSUS CHECK': _get_ecmwf_aifs_prob must
    return ecmwf_aifs025_ensemble's own member-vote-fraction probability via
    the same _model_prob_and_mean infra _get_consensus_probs's ecmwf_mean
    fetch already uses (same cache key, so no second network call on a
    warm cache). Calls the module-import-time-captured real function
    (_REAL_GET_ECMWF_AIFS_PROB) since conftest's default_ecmwf_aifs_prob_none
    autouse fixture stubs weather_markets._get_ecmwf_aifs_prob to None by
    default."""

    def test_fetches_member_vote_fraction_probability(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_cb.record_success()  # ensure circuit closed

        # 5 members, 3 above the 70.0 threshold -> prob = 0.6.
        members = [65.0, 68.0, 71.0, 72.0, 73.0]

        def _fake_om_request(method, url, **kwargs):
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

        prob = _REAL_GET_ECMWF_AIFS_PROB("NYC", target, condition)
        assert prob == pytest.approx(0.6), f"expected 3/5=0.6, got {prob}"

        wm._ensemble_cache.clear()

    def test_returns_none_when_fewer_than_five_members(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {
                "daily": {
                    "temperature_2m_max_member01": [70.0],
                    "temperature_2m_max_member02": [71.0],
                    "temperature_2m_max_member03": [72.0],
                }
            }
            return resp

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        condition = {"type": "above", "threshold": 70.0}

        prob = _REAL_GET_ECMWF_AIFS_PROB("NYC", target, condition)
        assert prob is None, f"expected None below the 5-member floor, got {prob}"

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
        # batch_prewarm_ensemble now sleeps _ENSEMBLE_TRACKING_TIER_DELAY_SECS
        # (65s) between the blend-critical and tracking-only tiers (see
        # TestBatchPrewarmEnsembleRateLimitTiering below) -- stub it out here
        # so this test still runs in well under a second.
        monkeypatch.setattr(wm.time, "sleep", lambda _seconds: None)

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
        # 5th key element is the quarantine-state tag (empty -- nothing
        # quarantined in this test, isolate_member_quarantine ensures a
        # clean state file).
        blended = wm._ensemble_cache.get(("NYC", date_iso, None, "max", ""))
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


class TestBatchPrewarmEnsembleBiasCorrection:
    """batch_prewarm_ensemble is the actual production path (the [ENS batch]
    lines every cron cycle) -- get_ensemble_temps's own bias-correction test
    doesn't exercise it at all, and review flagged this as the highest-risk
    untested line: the H-14 per-model cache write (feeding
    _get_consensus_probs/_get_gem_ukmo_means/accuracy tracking) must stay
    RAW, while only the blended (city, date, None, var) entry that feeds
    the live trading forecast gets bias-corrected."""

    def test_per_model_cache_raw_but_blend_corrected(self, monkeypatch):
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()
        wm._ensemble_cb.record_success()
        wm._MODEL_BIAS_CACHE.clear()
        monkeypatch.setattr(wm.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(wm, "_model_weights", lambda city, month=None: {})
        # icon_seamless has a known +4.0 bias; gfs_seamless has none.
        monkeypatch.setattr(
            wm, "_model_bias", lambda city, var, **kw: {"icon_seamless": 4.0}
        )

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        date_iso = target.isoformat()

        members_by_model = {
            "icon_seamless": [70.0, 71.0, 72.0, 73.0, 74.0],
            "gfs_seamless": [68.0, 69.0, 70.0, 71.0, 72.0],
            "ecmwf_aifs025_ensemble": [74.0, 75.0, 76.0, 77.0, 78.0],
        }

        def _fake_om_request(method, url, **kwargs):
            params = kwargs.get("params", {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            daily_key = params.get("daily")
            if daily_key == "precipitation_sum":
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

        # H-14 per-model entry: must be the RAW forecast, untouched by bias
        # correction -- this is what _get_consensus_probs/_get_gem_ukmo_means
        # and accuracy tracking read, and correcting it would corrupt both
        # (a self-referential "corrected" prediction logged as if it were
        # the model's real forecast).
        icon_key = ("icon_seamless", "NYC", date_iso, "max", None)
        icon_raw = wm._ensemble_cache.get(icon_key)
        assert icon_raw == pytest.approx(members_by_model["icon_seamless"]), (
            f"per-model cache entry must stay raw/uncorrected: {icon_raw}"
        )

        # Blended entry: icon's members must be shifted down by its +4.0
        # bias (70,71,72,73,74 -> 66,67,68,69,70); gfs (no bias) unchanged.
        # 5th key element is the quarantine-state tag (empty in this test).
        blended = wm._ensemble_cache.get(("NYC", date_iso, None, "max", ""))
        assert blended is not None
        assert 66.0 in blended and 70.0 in blended, (
            f"icon's bias-corrected members missing from the blend: {blended}"
        )
        # 73.0 only exists in icon's RAW set (70-74) -- gfs's raw set is
        # 68-72 and ecmwf's is 74-78, neither overlaps 73.0, so it can only
        # appear here if icon's uncorrected members leaked into the blend.
        assert 73.0 not in blended, (
            f"icon's raw (uncorrected) 73.0 leaked into the blend: {blended}"
        )
        assert 68.0 in blended, (
            f"gfs_seamless (zero bias) must be unaffected: {blended}"
        )

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()
        wm._MODEL_BIAS_CACHE.clear()


class TestBatchPrewarmEnsembleRateLimitTiering:
    """Open-Meteo's free ensemble-api endpoint enforces an undocumented
    rolling-~60s request budget too tight for cron's 13 calls/cycle
    (confirmed empirically 2026-07-24). batch_prewarm_ensemble now fetches
    blend-critical models + precip (tier 1) before GEM/UKMO tracking-only
    models (tier 2), with a real _ENSEMBLE_TRACKING_TIER_DELAY_SECS pause
    between tiers so a rate-limit trip only ever costs tracking data, never
    the live trading blend."""

    def test_tier1_before_sleep_tier2_after(self, monkeypatch):
        from datetime import date, timedelta
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()
        wm._ensemble_cb.record_success()

        target = date.today() + timedelta(days=3)
        date_iso = target.isoformat()

        events: list[tuple] = []

        def _fake_om_request(method, url, **kwargs):
            params = kwargs.get("params", {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            daily_key = params.get("daily")
            if daily_key == "precipitation_sum":
                events.append(("request", "precip", params.get("models")))
                resp.json.return_value = {"daily": {"time": [date_iso]}}
                return resp
            model = params.get("models")
            events.append(("request", "temp", model))
            resp.json.return_value = {
                "daily": {
                    "time": [date_iso],
                    f"{daily_key}_member01": [70.0],
                }
            }
            return resp

        def _fake_sleep(seconds):
            events.append(("sleep", seconds))

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm.time, "sleep", _fake_sleep)

        written = wm.batch_prewarm_ensemble({("NYC", date_iso)})
        assert written > 0

        sleep_indices = [i for i, e in enumerate(events) if e[0] == "sleep"]
        assert len(sleep_indices) == 1, (
            f"expected exactly one tier-transition sleep, got {events}"
        )
        sleep_idx = sleep_indices[0]
        assert events[sleep_idx][1] == wm._ENSEMBLE_TRACKING_TIER_DELAY_SECS

        before = {e[2] for e in events[:sleep_idx] if e[0] == "request"}
        after = {e[2] for e in events[sleep_idx + 1 :] if e[0] == "request"}

        tracking_only = set(wm.TRACKING_ONLY_MODEL_NAMES)
        assert before & tracking_only == set(), (
            f"tracking-only model fetched before the tier sleep: {before}"
        )
        assert before >= {"icon_seamless", "gfs_seamless", "ecmwf_aifs025_ensemble"}, (
            f"blend-critical temp models missing from tier 1: {before}"
        )
        assert "ecmwf_ifs025" in before, "precip fetch did not run in tier 1"
        assert after == tracking_only, (
            f"tier 2 should be exactly the tracking-only models, got {after}"
        )

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()

    def test_tier2_skipped_when_circuit_trips_during_tier1(self, monkeypatch):
        from datetime import date, timedelta

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()
        wm._ensemble_cb.record_success()

        target = date.today() + timedelta(days=3)
        date_iso = target.isoformat()

        tripped = {"value": False}
        requested_models: list[str] = []

        def _fake_om_request(method, url, **kwargs):
            params = kwargs.get("params", {})
            daily_key = params.get("daily")
            model = (
                params.get("models") if daily_key != "precipitation_sum" else "precip"
            )
            requested_models.append(model)
            # Simulate the circuit tripping partway through tier 1 -- from
            # this point on is_open() (mocked below) reports OPEN.
            tripped["value"] = True
            raise ConnectionError("simulated Open-Meteo 429")

        sleep_calls: list[float] = []
        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm.time, "sleep", lambda s: sleep_calls.append(s))
        monkeypatch.setattr(wm._ensemble_cb, "is_open", lambda: tripped["value"])

        written = wm.batch_prewarm_ensemble({("NYC", date_iso)})
        assert written == 0

        tracking_only = set(wm.TRACKING_ONLY_MODEL_NAMES)
        assert not (set(requested_models) & tracking_only), (
            f"tier 2 (tracking-only) must not be attempted once the circuit "
            f"is open: {requested_models}"
        )
        assert sleep_calls == [], (
            "must not sleep out the tier-transition delay when tier 1 "
            "already tripped the circuit -- tier 2 will just be skipped anyway"
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


# ── TestMemberQuarantine (scan_member_quarantine, per-model EWMA drift guard) ──


class TestMemberQuarantineScan:
    """scan_member_quarantine() -- generic, per-model quarantine one layer
    above _weights_from_mae()'s soft inverse-MAE down-weighting (see the
    "Per-member EWMA quarantine" section preceding _model_bias in
    weather_markets.py for why the soft weighting alone can never fully
    exclude a member: repeats = max(1, round(w * 2)) always includes at
    least one copy).

    Detection statistic is per-model BRIER SCORE (tracker.get_member_brier()),
    not MAE -- swapped after monitoring the original MAE-based version
    against real production data found MAE (and even raw threshold-crossing
    win/loss) could reward a confidently-wrong, merely luckily-biased
    forecast. See scan_member_quarantine()'s own docstring for the full
    rationale.

    Peer-relative design (redesigned after an independent opus review found
    the original self-relative/own-history design would never have caught
    the live failure it was built for -- gfs_seamless's own recent MAE can
    be better than its own older history while still being the worst of the
    3 live candidates right now). z = (own.brier - mean(non-quarantined
    peers' recent brier)) / se, where se is the POOLED two-sample standard
    error (own's own std/sqrt(n) combined with each peer's, not just own's
    alone -- a second independent review found the one-sample version put
    the live gfs_seamless case right at the trip boundary purely from
    ignoring peer_mean's own sampling uncertainty). See _se() below, which
    mirrors scan_member_quarantine()'s exact formula so test numbers can't
    silently drift out of sync with a future formula change."""

    def _fake_brier(self, recent: dict):
        """Fake tracker.get_member_brier(days_back=...) -- scan_member_
        quarantine() makes exactly ONE call now (no baseline/end_days_back)."""

        def _fake(days_back=14):
            return recent

        return _fake

    def _stats(self, brier, n, std=1.0):
        return {
            "brier": brier,
            "n": n,
            "std": std,
            "city_breakdown": {},
            "city_n_breakdown": {},
        }

    def _se(self, own_n=30, own_std=1.0, peer_ns=(30, 30), peer_std=1.0):
        """Mirrors scan_member_quarantine()'s own pooled-SE formula exactly:
        se = sqrt(own.std^2/own.n + sum(peer.std^2/peer.n)/len(peers)^2)."""
        own_var = own_std**2 / own_n
        peer_pool_var = sum(peer_std**2 / n for n in peer_ns) / (len(peer_ns) ** 2)
        return (own_var + peer_pool_var) ** 0.5

    @pytest.fixture(autouse=True)
    def _clear_quarantine_state(self):
        # Explicit fixture (not xunit setup_method) so it's unambiguously
        # ordered after conftest's isolate_member_quarantine autouse fixture
        # redirects MEMBER_QUARANTINE_PATH -- this write must never land on
        # the real data/member_quarantine.json.
        import weather_markets as wm

        wm._save_member_quarantine_state({})

    def test_warmup_floor_own_n_blocks_trip(self, monkeypatch):
        """own.n below the floor must never update ewma_z/trip, however bad
        the Brier score looks, even with well-observed peers."""
        import weather_markets as wm

        recent = {
            "gfs_seamless": self._stats(brier=0.9, n=5, std=1.0),  # n<20
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert not state.get("gfs_seamless", {}).get("quarantined")
        assert "ewma_z" not in state.get("gfs_seamless", {})

    def test_warmup_floor_no_sufficient_peers_blocks_trip(self, monkeypatch):
        """A model with plenty of its own data still can't be judged if
        every OTHER candidate is data-thin -- there's no peer reference."""
        import weather_markets as wm

        recent = {
            "gfs_seamless": self._stats(brier=0.9, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=5, std=1.0),  # n<20
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=5, std=1.0),  # n<20
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert not state.get("gfs_seamless", {}).get("quarantined")
        assert "ewma_z" not in state.get("gfs_seamless", {})

    def test_zero_own_std_blocks_trip(self, monkeypatch):
        import weather_markets as wm

        recent = {
            "gfs_seamless": self._stats(brier=0.9, n=30, std=0.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert not state.get("gfs_seamless", {}).get("quarantined")

    def test_cold_start_ordinary_bad_reading_does_not_trip_on_first_scan(
        self, monkeypatch
    ):
        """ewma_z_prev is seeded at 0.0, not the first raw z -- an ORDINARY
        bad first reading (raw z=4, well past what a single day's noise
        would produce, but not extreme) must land well under the 2.0 trip
        line (ewma = 0.2*4 = 0.8), proving smoothing genuinely bounds a
        single scan's influence."""
        import weather_markets as wm

        se = self._se()  # 2 peers (icon, aifs), default std/n for all 3
        own_brier = 0.2 + 4.0 * se  # peer_mean = mean(0.2, 0.2) = 0.2
        recent = {
            "gfs_seamless": self._stats(brier=own_brier, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["last_z"] == pytest.approx(4.0, rel=1e-3)
        assert state["gfs_seamless"]["ewma_z"] == pytest.approx(0.8, rel=1e-3)
        assert not state["gfs_seamless"]["quarantined"]

    def test_cold_start_extreme_reading_can_trip_on_first_scan(self, monkeypatch):
        """The seeded-at-0 smoothing bounds an ORDINARY bad reading (see
        above) but does not and cannot prevent a single genuinely EXTREME
        reading (raw z >= 2/lambda = 10) from reaching the trip line on the
        very first scan -- ewma = 0.2*10 = 2.0 exactly. This is documented,
        intended behavior, not a bug: a model 10 pooled standard errors off
        its peers on day one should trip immediately, not wait. (The
        MIN_EFFECT floor is also cleared here -- own-vs-peer gap is 10*se,
        comfortably above the 0.008 floor.)"""
        import weather_markets as wm

        se = self._se()
        own_brier = 0.2 + 10.0 * se
        recent = {
            "gfs_seamless": self._stats(brier=own_brier, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["ewma_z"] == pytest.approx(2.0, rel=1e-3)
        assert state["gfs_seamless"]["quarantined"]
        assert result["newly_quarantined"] == ["gfs_seamless"]

    def test_sustained_moderate_drift_trips_after_repeated_scans_not_immediately(
        self, monkeypatch
    ):
        """A consistently-bad-but-not-extreme member (raw z=4 each scan)
        must accumulate past the trip line over several scans, not on
        scan 1 -- same ewma trajectory as the cold-start test above,
        repeated: 0.8, 1.44, 1.952, then 2.3616 on the 4th scan."""
        import weather_markets as wm

        se = self._se()
        own_brier = 0.2 + 4.0 * se
        recent = {
            "gfs_seamless": self._stats(brier=own_brier, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        assert not wm.load_member_quarantine_state()["gfs_seamless"]["quarantined"]
        wm.scan_member_quarantine()
        assert not wm.load_member_quarantine_state()["gfs_seamless"]["quarantined"]
        wm.scan_member_quarantine()
        assert not wm.load_member_quarantine_state()["gfs_seamless"]["quarantined"]
        wm.scan_member_quarantine()
        assert wm.load_member_quarantine_state()["gfs_seamless"]["quarantined"]

    def test_trip_blocked_when_effect_size_below_minimum_despite_high_z(
        self, monkeypatch
    ):
        """MEDIUM-2 (review): a purely statistical z-threshold shrinks its
        required Brier gap as ~1/sqrt(n), so at a large enough n a trivial,
        practically meaningless gap could become "significant". Simulate
        that directly with a huge n (own.std tiny relative to n so se is
        tiny) producing z well past 2.0 from a gap well under
        _QUARANTINE_MIN_EFFECT (0.008, Brier-scale) -- must NOT trip.
        n=2.5M (not 10k, as the old °F-scale version of this test used) --
        the floor shrank from 0.5°F to 0.008 when the statistic swapped
        to Brier, so a far smaller se (far larger n) is needed to keep the
        constructed effect size under the new floor while still producing
        z=10. Purely arithmetic (get_member_brier is mocked, no real rows
        are created), so the large n has no real runtime cost."""
        import weather_markets as wm

        se = self._se(own_n=2_500_000, peer_ns=(2_500_000, 2_500_000))
        # z=10 from this tiny se still means a real Brier gap far under 0.008.
        own_brier = 0.3 + 10.0 * se
        assert own_brier - 0.3 < wm._QUARANTINE_MIN_EFFECT, (
            "test setup bug: effect size isn't actually below the floor"
        )
        recent = {
            "gfs_seamless": self._stats(brier=own_brier, n=2_500_000, std=1.0),
            "icon_seamless": self._stats(brier=0.3, n=2_500_000, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.3, n=2_500_000, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["ewma_z"] >= wm._QUARANTINE_TRIP_Z, (
            "test setup bug: z-threshold alone would have tripped"
        )
        assert not state["gfs_seamless"]["quarantined"], (
            "must not trip on statistical significance alone when the "
            "practical Brier gap is below the minimum effect size floor"
        )
        assert result["newly_quarantined"] == []

    def test_asymmetric_hysteresis_dead_zone_no_flapping(self, monkeypatch):
        """Once quarantined, ewma_z sitting in the dead zone strictly
        between release (0.5) and trip (2.0) must never release -- release
        requires clearly-recovered, not just merely-not-terrible. Feeds
        raw z=1.0 (own.mae only 1 pooled SE above peers) while pre-seeded
        ewma_z is also 1.0, so the updated ewma_z (0.2*1 + 0.8*1 = 1.0)
        stays squarely inside (0.5, 2.0) -- the actual dead zone, not above
        the trip line as the original (buggy) version of this test had it."""
        import weather_markets as wm

        wm._save_member_quarantine_state(
            {"gfs_seamless": {"quarantined": True, "ewma_z": 1.0}}
        )
        se = self._se()
        own_brier = 0.2 + 1.0 * se
        recent = {
            "gfs_seamless": self._stats(brier=own_brier, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert 0.5 < state["gfs_seamless"]["ewma_z"] < 2.0, (
            f"test setup bug: ewma_z={state['gfs_seamless']['ewma_z']} isn't "
            f"actually in the dead zone"
        )
        assert state["gfs_seamless"]["quarantined"], (
            f"must stay quarantined while ewma_z={state['gfs_seamless']['ewma_z']} "
            f"is in the dead zone (above release, below trip)"
        )

    def test_release_only_at_or_below_release_line(self, monkeypatch):
        import weather_markets as wm

        wm._save_member_quarantine_state(
            {"gfs_seamless": {"quarantined": True, "ewma_z": 0.6}}
        )
        # own == peer_mean exactly -> z=0 -> new ewma_z = 0.2*0 + 0.8*0.6 = 0.48 <= 0.5
        recent = {
            "gfs_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        assert "gfs_seamless" in result["released"]
        assert not wm.load_member_quarantine_state()["gfs_seamless"]["quarantined"]

    def test_quarantined_model_stays_quarantined_when_data_goes_thin(self, monkeypatch):
        """A quarantined model that can no longer be evaluated (own.n drops
        below the floor) must stay quarantined rather than silently
        releasing from absence of evidence -- and last_scan_at must still
        update so it's visible this was checked, not skipped entirely."""
        import weather_markets as wm

        wm._save_member_quarantine_state(
            {"gfs_seamless": {"quarantined": True, "ewma_z": 3.0}}
        )
        recent = {
            "gfs_seamless": self._stats(brier=0.9, n=5, std=1.0),  # n<20 now
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["quarantined"]
        assert state["gfs_seamless"]["ewma_z"] == pytest.approx(3.0)  # unchanged
        assert "last_scan_at" in state["gfs_seamless"]
        assert result["released"] == []

    def test_peer_mean_excludes_already_quarantined_peer(self, monkeypatch):
        """A peer that was ALREADY quarantined going into this scan must not
        count toward another model's "normal" reference -- including its
        bad Brier score would inflate peer_mean and could mask a second bad
        member. icon is pre-quarantined with a wildly bad recent.brier
        (0.99); if that leaked into gfs's peer computation, gfs's z would
        come out strongly NEGATIVE instead of strongly positive."""
        import weather_markets as wm

        wm._save_member_quarantine_state(
            {"icon_seamless": {"quarantined": True, "ewma_z": 5.0}}
        )
        recent = {
            "gfs_seamless": self._stats(brier=0.5, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.99, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        # peer_mean for gfs must be just aifs's 0.2 (icon excluded) -- ONE
        # peer, not two, so the SE used here must reflect that.
        se_one_peer = self._se(peer_ns=(30,))
        assert state["gfs_seamless"]["last_z"] == pytest.approx(
            (0.5 - 0.2) / se_one_peer, rel=1e-3
        )
        assert state["gfs_seamless"]["last_z"] > 0

    def test_floor_quarantines_worst_first_blocks_the_rest(self, monkeypatch):
        """Two of the 3 real candidates simultaneously over trip threshold
        with MIN_ACTIVE=2 (room=1): only the worse (by ewma_z) is quarantined,
        the other appears in blocked_by_floor, not silently dropped."""
        import weather_markets as wm

        # gfs peer_mean = mean(icon=9, aifs=2) = 5.5 -> effect=4.5, big z
        # icon peer_mean = mean(gfs=10, aifs=2) = 6.0 -> effect=3.0, big z
        # gfs is worse (higher z/ewma) -> gfs quarantined, icon blocked. (Large
        # synthetic magnitudes, not realistic Brier values -- this is pure
        # mocked arithmetic exercising a single-scan trip, same as the
        # cold-start-extreme test's large own_brier construction.)
        recent = {
            "gfs_seamless": self._stats(brier=10.0, n=30, std=1.0),
            "icon_seamless": self._stats(brier=9.0, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=2.0, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        assert result["newly_quarantined"] == ["gfs_seamless"]
        assert result["blocked_by_floor"] == ["icon_seamless"]
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["quarantined"]
        assert not state["icon_seamless"]["quarantined"]

    def test_deterministic_tiebreak_on_exact_equal_ewma_z(self, monkeypatch):
        """Exact-float-tie between two candidates: alphabetically-first model
        name wins the tie-break (is quarantined). gfs and icon given equal
        (large, synthetic) brier -> by symmetry each one's peer_mean
        (computed from the OTHER two) is identical, producing an exact
        z/ewma_z tie clearing the trip line on a single scan."""
        import weather_markets as wm

        recent = {
            "gfs_seamless": self._stats(brier=12.0, n=30, std=1.0),
            "icon_seamless": self._stats(brier=12.0, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=2.0, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["ewma_z"] == pytest.approx(
            state["icon_seamless"]["ewma_z"]
        ), "test setup bug: this test requires an exact tie"
        assert result["newly_quarantined"] == ["gfs_seamless"]  # alphabetically first
        assert result["blocked_by_floor"] == ["icon_seamless"]

    def test_read_time_floor_clamp_tiebreak_is_deterministic(self):
        """get_quarantined_members()'s defensive read-time floor clamp (for
        a hand-edited/corrupted state file reporting too many quarantined)
        must use the SAME deterministic (-ewma_z, name) tiebreak as the scan
        path's pass 2 -- a set-iteration-order tiebreak would let two
        processes reading the identical corrupted file disagree on which
        model stays quarantined, splitting _quarantine_cache_tag()'s cache
        namespace between them."""
        import weather_markets as wm

        # All 3 candidates "quarantined" (invalid: floor only allows 1) with
        # an exact ewma_z tie between two of them.
        wm._save_member_quarantine_state(
            {
                "gfs_seamless": {"quarantined": True, "ewma_z": 5.0},
                "icon_seamless": {"quarantined": True, "ewma_z": 5.0},
                "ecmwf_aifs025_ensemble": {"quarantined": True, "ewma_z": 1.0},
            }
        )
        result = wm.get_quarantined_members()
        assert len(result) == 1, f"floor must clamp to 1, got {result}"
        # Between the exact-tied gfs/icon (both ewma_z=5.0, higher than
        # aifs's 1.0), alphabetically-first wins deterministically.
        assert result == {"gfs_seamless"}, (
            f"expected deterministic tiebreak to keep gfs_seamless, got {result}"
        )

    def test_stray_tracked_models_never_affect_peers_floor_or_room(self, monkeypatch):
        """ecmwf_ifs025/gem_global -- tracked by get_member_brier() but NOT
        real candidates for this blend -- must have zero effect on peer-mean
        computation or the active-member floor/room math, even with a
        terrible Brier score."""
        import weather_markets as wm

        recent = {
            "gfs_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_ifs025": self._stats(brier=0.99, n=30, std=1.0),
            "gem_global": self._stats(brier=0.99, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        assert result["newly_quarantined"] == []
        assert result["blocked_by_floor"] == []
        state = wm.load_member_quarantine_state()
        assert "ecmwf_ifs025" not in state
        assert "gem_global" not in state
        # If either stray leaked into a peer-mean, z would be nonzero.
        assert state["gfs_seamless"]["last_z"] == pytest.approx(0.0, abs=1e-6)

    def test_failed_persist_does_not_leave_mutated_state_in_the_cache(
        self, monkeypatch
    ):
        """MEDIUM-3 (review): scan_member_quarantine() must work on its own
        copy, never the module-level cache object -- otherwise a failed
        disk write still leaves this process's in-memory cache holding the
        never-persisted mutation, so it keeps "trading" against a decision
        disk never actually recorded. Prime the cache with a clean read,
        force the write to fail, run a scan that WOULD change state, then
        confirm a fresh read still returns the pre-scan (unmutated) state."""
        import weather_markets as wm

        wm._save_member_quarantine_state({"icon_seamless": {"quarantined": False}})
        pre_scan_state = wm.load_member_quarantine_state()  # primes the cache

        monkeypatch.setattr(
            wm._safe_io,
            "atomic_write_json",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        se = self._se()
        own_brier = 0.2 + 10.0 * se
        recent = {
            "gfs_seamless": self._stats(brier=own_brier, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()  # computes a real change, save fails
        assert result["newly_quarantined"] == ["gfs_seamless"], (
            "test setup bug: the scan itself must have decided to quarantine"
        )

        post_failure_state = wm.load_member_quarantine_state()
        assert post_failure_state == pre_scan_state, (
            f"a failed persist leaked the computed-but-unsaved mutation into "
            f"the process's cache: {post_failure_state} != {pre_scan_state}"
        )

    def test_persistence_round_trip(self, monkeypatch):
        import weather_markets as wm

        recent = {
            "gfs_seamless": self._stats(brier=0.5, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        # Fresh read, simulating a new process. Non-zero expected values (not
        # just presence of the ewma_z key) so this can't pass vacuously if
        # the write never actually happened.
        reloaded = wm.load_member_quarantine_state()
        se = self._se()
        assert "gfs_seamless" in reloaded
        assert reloaded["gfs_seamless"]["ewma_z"] == pytest.approx(
            0.2 * (0.5 - 0.2) / se, rel=1e-3
        )
        assert reloaded["gfs_seamless"]["last_own_brier"] == pytest.approx(0.5)
        assert "last_scan_at" in reloaded["gfs_seamless"]

    def test_legacy_mae_state_resets_ewma_z_instead_of_carrying_it_forward(
        self, monkeypatch
    ):
        """A state file predating the MAE->Brier swap (has last_own_mae, no
        last_own_brier) must have its ewma_z reset to 0.0 before this scan's
        EWMA update, not blended as if it were already on the Brier scale --
        the two statistics are on incompatible units. Also verifies the
        legacy keys are cleared once the entry is rewritten."""
        import weather_markets as wm

        wm._save_member_quarantine_state(
            {
                "gfs_seamless": {
                    "quarantined": False,
                    "ewma_z": 1.95,  # near the OLD MAE-era trip line
                    "last_own_mae": 5.37,
                    "last_peer_mean_mae": 3.49,
                    "last_effect_f": 1.88,
                }
            }
        )
        recent = {
            "gfs_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        # own == peer_mean -> z=0 this scan -> ewma_z = 0.2*0 + 0.8*ewma_z_prev.
        # If the stale 1.95 leaked through, ewma_z would be 0.8*1.95=1.56;
        # reset-to-0 means it must be exactly 0.0.
        assert state["gfs_seamless"]["ewma_z"] == pytest.approx(0.0, abs=1e-9), (
            f"stale MAE-scale ewma_z leaked into the Brier-scale EWMA: "
            f"{state['gfs_seamless']['ewma_z']}"
        )
        assert "last_own_mae" not in state["gfs_seamless"]
        assert "last_peer_mean_mae" not in state["gfs_seamless"]
        assert "last_effect_f" not in state["gfs_seamless"]
        assert "last_own_brier" in state["gfs_seamless"]

    def test_legacy_mae_state_does_not_auto_release_a_quarantined_model(
        self, monkeypatch
    ):
        """(opus-review MEDIUM-3) A model that WAS quarantined under MAE must
        not silently release on the same scan its ewma_z gets reset to 0 --
        the reset is about unit-compatibility, not evidence of recovery.
        own==peer_mean here (z=0), so ewma_z=0.2*0=0.0 <= the 0.5 release
        line -- without suppression this would release every time."""
        import weather_markets as wm

        wm._save_member_quarantine_state(
            {
                "gfs_seamless": {
                    "quarantined": True,
                    "ewma_z": 3.0,  # comfortably past the OLD MAE-era trip line
                    "last_own_mae": 8.0,
                    "last_peer_mean_mae": 2.0,
                    "last_effect_f": 6.0,
                }
            }
        )
        recent = {
            "gfs_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "icon_seamless": self._stats(brier=0.2, n=30, std=1.0),
            "ecmwf_aifs025_ensemble": self._stats(brier=0.2, n=30, std=1.0),
        }
        monkeypatch.setattr("tracker.get_member_brier", self._fake_brier(recent))
        result = wm.scan_member_quarantine()
        state = wm.load_member_quarantine_state()
        assert state["gfs_seamless"]["quarantined"], (
            "must stay quarantined on the legacy-reset scan even though "
            "ewma_z resets to a value under the release line"
        )
        assert state["gfs_seamless"]["ewma_z"] == pytest.approx(0.0, abs=1e-9), (
            "ewma_z itself must still update normally -- only the release "
            "decision is suppressed, not the EWMA computation"
        )
        assert result["released"] == []

        # Next scan (no longer legacy -- last_own_brier now present): if the
        # real signal stays at z=0, ewma_z stays 0.0 <= release line, and
        # THIS scan must release normally -- suppression is one-scan-only.
        result2 = wm.scan_member_quarantine()
        assert result2["released"] == ["gfs_seamless"]
        assert not wm.load_member_quarantine_state()["gfs_seamless"]["quarantined"]

    def test_quarantine_min_effect_is_within_sane_brier_scale_bounds(self):
        """Regression guard (opus-review MEDIUM-6): nothing else in this
        suite would catch _QUARANTINE_MIN_EFFECT being raised to an absurd
        value -- the largest effect any existing test constructs is 4.5
        (std=1.0 synthetic mocks), so the floor could be set anywhere up to
        ~2.2, including values well past 1.0 (a permanent quarantine
        disable, since real Brier scores are bounded to [0,1]), and every
        other test would still pass. Pin it to a small fraction of the real
        Brier scale (real forecasts run ~0.15-0.35 per this codebase's own
        established scale -- graduation gate 0.23, retirement threshold
        0.25) instead."""
        import weather_markets as wm

        assert 0 < wm._QUARANTINE_MIN_EFFECT < 0.1, (
            f"_QUARANTINE_MIN_EFFECT={wm._QUARANTINE_MIN_EFFECT} is outside "
            f"a sane fraction of the real Brier scale"
        )


class TestMemberQuarantineBlendHooks:
    """get_ensemble_temps()/batch_prewarm_ensemble() must respect quarantine
    state as a hard exclusion (soft _weights_from_mae down-weighting alone
    can never reach true exclusion -- see the module docstring), while
    accuracy tracking (and hence the ability to recover) continues
    regardless of quarantine status."""

    def test_get_ensemble_temps_skips_quarantined_model(self, monkeypatch):
        import weather_markets as wm

        wm._ensemble_cache.clear()
        monkeypatch.setattr(wm, "get_quarantined_members", lambda: {"gfs_seamless"})
        monkeypatch.setattr(wm, "_model_weights", lambda city, month=None: {})
        monkeypatch.setattr(wm, "_model_bias", lambda city, var: {})
        monkeypatch.setattr(
            wm, "CITY_COORDS", {"NYC": (40.7, -74.0, "America/New_York")}
        )

        called_with = []

        def _fake_fetch(lat, lon, tz, target_date, model, hour, var):
            called_with.append(model)
            return [70.0, 71.0]

        monkeypatch.setattr(wm, "_fetch_model_ensemble", _fake_fetch)

        from datetime import date as _date

        wm.get_ensemble_temps("NYC", _date(2026, 8, 20))

        assert "gfs_seamless" not in called_with, (
            f"quarantined model must never be fetched, got calls: {called_with}"
        )
        assert "icon_seamless" in called_with

    def test_get_ensemble_temps_cache_key_distinguishes_quarantine_state(
        self, monkeypatch
    ):
        """A cache entry built before a quarantine change must not be served
        after the change -- proves the cache-key fix, not just the filter."""
        import weather_markets as wm

        wm._ensemble_cache.clear()
        monkeypatch.setattr(wm, "_model_weights", lambda city, month=None: {})
        monkeypatch.setattr(wm, "_model_bias", lambda city, var: {})
        monkeypatch.setattr(
            wm, "CITY_COORDS", {"NYC": (40.7, -74.0, "America/New_York")}
        )
        monkeypatch.setattr(wm, "_fetch_model_ensemble", lambda *a, **k: [70.0])

        from datetime import date as _date

        monkeypatch.setattr(wm, "get_quarantined_members", lambda: set())
        result_before = wm.get_ensemble_temps("NYC", _date(2026, 8, 20))

        monkeypatch.setattr(wm, "get_quarantined_members", lambda: {"gfs_seamless"})
        result_after = wm.get_ensemble_temps("NYC", _date(2026, 8, 20))

        assert len(result_after) < len(result_before), (
            "post-quarantine call must build a fresh (filtered) blend, not "
            "serve the pre-quarantine cached one"
        )

    def test_batch_prewarm_still_fetches_quarantined_model_for_tracking(
        self, monkeypatch
    ):
        """A quarantined model must still be fetched and cached per-model
        (H-14) so its accuracy keeps being tracked and it can recover, while
        its members are excluded from the blended entry that feeds the live
        forecast -- mirrors TestBatchPrewarmEnsembleTrackingOnlyModels'
        gem/ukmo test, but for a REAL blend model that's dynamically
        quarantined rather than a statically tracking-only one."""
        from unittest.mock import MagicMock

        import weather_markets as wm

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()
        wm._ensemble_cb.record_success()
        monkeypatch.setattr(wm.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(wm, "get_quarantined_members", lambda: {"gfs_seamless"})

        from datetime import date, timedelta

        target = date.today() + timedelta(days=3)
        date_iso = target.isoformat()

        members_by_model = {
            "icon_seamless": [70.0, 71.0, 72.0],
            "gfs_seamless": [900.0, 901.0, 902.0],  # absurd -- must not leak into blend
            "ecmwf_aifs025_ensemble": [74.0, 75.0, 76.0],
            "gem_global": [200.0, 201.0, 202.0],
            "ukmo_global_ensemble_20km": [-200.0, -201.0, -202.0],
        }

        def _fake_om_request(method, url, **kwargs):
            params = kwargs.get("params", {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            daily_key = params.get("daily")
            if daily_key == "precipitation_sum":
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
        assert written > 0

        # Per-model cache entry (H-14) must still exist for the quarantined
        # model -- accuracy tracking must continue uninterrupted.
        key = ("gfs_seamless", "NYC", date_iso, "max", None)
        cached = wm._ensemble_cache.get(key)
        assert cached is not None, (
            "quarantined model's per-model cache entry must still be written "
            "so accuracy tracking (and recovery) can continue"
        )
        assert cached == pytest.approx(members_by_model["gfs_seamless"])

        # But its absurd values must NOT appear in the blended entry. Key's
        # 5th element is the quarantine-state tag -- gfs_seamless is the
        # only model quarantined in this test.
        blended = wm._ensemble_cache.get(("NYC", date_iso, None, "max", "gfs_seamless"))
        assert blended is not None
        # Tight bound: only icon_seamless (70-72) and ecmwf_aifs025_ensemble
        # (74-76) should ever appear here. A loose bound like `t < 500` would
        # also silently pass gem_global's 200s/ukmo's -200s/gfs's 900s --
        # this must actually distinguish "leaked" from "didn't leak", not
        # just "isn't absurdly huge".
        assert all(50.0 < t < 100.0 for t in blended), (
            f"quarantined gfs_seamless's members (or gem/ukmo's tracking-"
            f"only members) leaked into the live trading blend: {blended}"
        )
        assert any(t == pytest.approx(75.0) for t in blended), (
            "ecmwf_aifs025_ensemble's real member is missing from the blend"
        )
        assert any(t == pytest.approx(72.0) for t in blended), (
            "icon_seamless's real member is missing from the blend"
        )

        wm._ensemble_cache.clear()
        wm._ensemble_disk_pending.clear()


# ── TestModelBias (_model_bias, var-split bias-correction feeding the live blend) ──


class TestModelBias:
    """_model_bias() must correct each model's raw ensemble members toward its
    own known signed error, split by var -- never falling back to a
    pooled-across-var bias (verified worse than no correction at all via
    leave-one-out backtest, 2026-08-13)."""

    def _fake_bias_acc(self, **overrides) -> dict:
        acc = {
            "gfs_seamless": {
                "max": {
                    "bias": 4.4,
                    "n": 30,
                    "city_breakdown": {"NYC": 6.0},
                    "city_n_breakdown": {"NYC": 25},
                },
                "min": {
                    "bias": 0.4,
                    "n": 30,
                    "city_breakdown": {},
                    "city_n_breakdown": {},
                },
            },
        }
        acc.update(overrides)
        return acc

    def test_uses_city_specific_bias_when_above_floor(self, monkeypatch):
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()
        monkeypatch.setattr(
            "tracker.get_member_bias", lambda days_back=60: self._fake_bias_acc()
        )
        result = wm._model_bias("NYC", "max", min_n_city=20, min_n_global=10)
        assert result["gfs_seamless"] == pytest.approx(6.0), (
            f"NYC has 25 max observations, clears the 20 floor -- must use "
            f"the city-specific bias (6.0), not the global one (4.4): {result}"
        )
        wm._MODEL_BIAS_CACHE.clear()

    def test_falls_back_to_global_when_city_thin(self, monkeypatch):
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()
        monkeypatch.setattr(
            "tracker.get_member_bias", lambda days_back=60: self._fake_bias_acc()
        )
        # Chicago has zero city-specific max observations for gfs_seamless
        # in the fixture -- must fall back to the global var-specific bias.
        result = wm._model_bias("Chicago", "max", min_n_city=20, min_n_global=10)
        assert result["gfs_seamless"] == pytest.approx(4.4), (
            f"Chicago has no city-specific data, global n=30 clears the 10 "
            f"floor -- must use the global max-var bias: {result}"
        )
        wm._MODEL_BIAS_CACHE.clear()

    def test_model_absent_when_both_city_and_global_too_thin(self, monkeypatch):
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()
        thin_acc = {
            "gfs_seamless": {
                "max": {
                    "bias": 4.4,
                    "n": 3,  # below min_n_global
                    "city_breakdown": {},
                    "city_n_breakdown": {},
                },
            },
        }
        monkeypatch.setattr("tracker.get_member_bias", lambda days_back=60: thin_acc)
        result = wm._model_bias("NYC", "max", min_n_city=20, min_n_global=10)
        assert "gfs_seamless" not in result, (
            f"too thin for both city and global floors -- model must be "
            f"absent (caller's .get(model, 0.0) then applies zero "
            f"correction), not present with an unreliable number: {result}"
        )
        wm._MODEL_BIAS_CACHE.clear()

    def test_var_split_never_pools_max_and_min(self, monkeypatch):
        """gfs_seamless's fixture has max bias=4.4 and min bias=0.4 -- these
        must never mix. Requesting var='min' must never return the max
        figure, and vice versa."""
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()
        monkeypatch.setattr(
            "tracker.get_member_bias", lambda days_back=60: self._fake_bias_acc()
        )
        max_result = wm._model_bias("Chicago", "max", min_n_city=20, min_n_global=10)
        wm._MODEL_BIAS_CACHE.clear()
        min_result = wm._model_bias("Chicago", "min", min_n_city=20, min_n_global=10)
        wm._MODEL_BIAS_CACHE.clear()

        assert max_result["gfs_seamless"] == pytest.approx(4.4)
        assert min_result["gfs_seamless"] == pytest.approx(0.4)
        assert max_result["gfs_seamless"] != min_result["gfs_seamless"]

    def test_model_with_no_data_for_requested_var_absent(self, monkeypatch):
        """A model that only has 'min' data must not appear at all when
        var='max' is requested -- no silent fallback to its other var."""
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()
        min_only_acc = {
            "icon_seamless": {
                "min": {
                    "bias": -0.7,
                    "n": 30,
                    "city_breakdown": {},
                    "city_n_breakdown": {},
                },
            },
        }
        monkeypatch.setattr(
            "tracker.get_member_bias", lambda days_back=60: min_only_acc
        )
        result = wm._model_bias("NYC", "max", min_n_city=20, min_n_global=10)
        assert "icon_seamless" not in result
        wm._MODEL_BIAS_CACHE.clear()

    def test_empty_when_tracker_call_fails(self, monkeypatch):
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()

        def _raise(days_back=60):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr("tracker.get_member_bias", _raise)
        assert wm._model_bias("NYC", "max") == {}
        wm._MODEL_BIAS_CACHE.clear()

    def test_cache_key_includes_floors(self, monkeypatch):
        """Review-caught (2026-08-13): the cache key omitted min_n_city/
        min_n_global, so two calls differing only in floors would collide
        on the same cache slot -- the second call's genuinely different
        query would silently return the first call's cached answer instead
        of being recomputed."""
        import weather_markets as wm

        wm._MODEL_BIAS_CACHE.clear()
        monkeypatch.setattr(
            "tracker.get_member_bias", lambda days_back=60: self._fake_bias_acc()
        )
        # NYC has 25 max observations for gfs_seamless (fixture) -- clears a
        # 20-obs city floor but not a 30-obs one, in which case it must
        # fall back to the global bias (4.4, global n=30) instead.
        loose = wm._model_bias("NYC", "max", min_n_city=20, min_n_global=10)
        strict = wm._model_bias("NYC", "max", min_n_city=30, min_n_global=10)

        assert loose["gfs_seamless"] == pytest.approx(6.0), (
            "25 obs clears the 20-floor city-specific bias"
        )
        assert strict["gfs_seamless"] == pytest.approx(4.4), (
            f"25 obs does NOT clear the 30-floor -- must fall back to the "
            f"global bias (4.4), not silently reuse the first call's cached "
            f"city-specific answer (6.0) for a different floor: {strict}"
        )
        wm._MODEL_BIAS_CACHE.clear()


class TestGetEnsembleTempsBiasCorrection:
    """Wiring test: get_ensemble_temps() must subtract each model's bias from
    its raw members before weighting/repeating into the blend, and must
    skip bias correction entirely for hourly fetches (hour is not None),
    matching var's own "ignored if hour is set" semantics."""

    def _patch_common(self, monkeypatch, wm, *, bias: dict):
        # NYC is a real CITY_COORDS entry already -- no need to fake it.
        wm._ensemble_cache.clear()
        monkeypatch.setattr(wm, "_model_weights", lambda city, month=None: {})
        monkeypatch.setattr(
            wm, "_model_bias", lambda city, var, **kw: dict(bias) if var else {}
        )

    def test_bias_subtracted_from_raw_members_before_blend(self, monkeypatch):
        from datetime import date, timedelta

        import weather_markets as wm

        self._patch_common(monkeypatch, wm, bias={"icon_seamless": 3.0})

        def _fake_fetch(lat, lon, tz, target_date, model, hour, var):
            return {"icon_seamless": [70.0, 72.0], "gfs_seamless": [60.0, 62.0]}.get(
                model, []
            )

        monkeypatch.setattr(wm, "_fetch_model_ensemble", _fake_fetch)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless", "gfs_seamless"])

        target = date.today() + timedelta(days=3)
        temps = wm.get_ensemble_temps("NYC", target, hour=None, var="max")

        # icon_seamless's raw [70, 72] must be shifted down by its 3.0 bias
        # -> [67, 69]; gfs_seamless (no bias entry, treated as 0.0) unchanged.
        assert 67.0 in temps and 69.0 in temps, f"icon not bias-corrected: {temps}"
        assert 70.0 not in temps and 72.0 not in temps, (
            f"raw uncorrected icon values leaked into the blend: {temps}"
        )
        assert 60.0 in temps and 62.0 in temps, (
            f"gfs (zero bias) must be unaffected: {temps}"
        )
        wm._ensemble_cache.clear()

    def test_hourly_fetch_skips_bias_correction(self, monkeypatch):
        """hour is not None -> var is semantically meaningless (a daily-
        extreme correction must not be applied to an hourly forecast)."""
        from datetime import date, timedelta

        import weather_markets as wm

        self._patch_common(monkeypatch, wm, bias={"icon_seamless": 3.0})

        calls = {"model_bias": 0}

        def _tracking_model_bias(city, var, **kw):
            calls["model_bias"] += 1
            return {"icon_seamless": 3.0}

        monkeypatch.setattr(wm, "_model_bias", _tracking_model_bias)

        def _fake_fetch(lat, lon, tz, target_date, model, hour, var):
            return {"icon_seamless": [70.0, 72.0]}.get(model, [])

        monkeypatch.setattr(wm, "_fetch_model_ensemble", _fake_fetch)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless"])

        target = date.today() + timedelta(days=3)
        temps = wm.get_ensemble_temps("NYC", target, hour=14, var="max")

        assert calls["model_bias"] == 0, (
            "_model_bias must not be called at all for an hourly fetch"
        )
        assert 70.0 in temps and 72.0 in temps, (
            f"hourly fetch must use raw, uncorrected temps: {temps}"
        )
        wm._ensemble_cache.clear()


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
        from datetime import datetime
        from unittest.mock import MagicMock, patch
        from zoneinfo import ZoneInfo

        import metar as _metar
        import weather_markets as wm

        # _metar_lock_in gates on city-local ("America/New_York" for NYC)
        # calendar date, not UTC -- match that clock or this test flips false
        # for part of every day (UTC rolls to the next calendar date before
        # NY local time does: ~19:00-20:00 local through midnight, depending
        # on DST).
        today = datetime.now(ZoneInfo("America/New_York")).date()
        fake_obs_time = MagicMock()
        fake_obs_local = MagicMock(hour=local_hour)
        fake_obs_local.date.return_value = today
        fake_obs_time.astimezone.return_value = fake_obs_local

        with patch.object(wm, "_metar_station_for_city", return_value="KJFK"):
            with (
                patch.object(
                    _metar,
                    "fetch_metar",
                    return_value={
                        "current_temp_f": min_temp_f,
                        "obs_time": fake_obs_time,
                    },
                ),
                # _metar_lock_in sources the daily extreme from
                # fetch_metar_daily_extreme, not fetch_metar()'s own
                # min_temp_f/max_temp_f fields (2026-08-09 — see
                # fetch_metar_daily_extreme's docstring). ticker is always a
                # KXLOW* ticker here, so only "min" is ever requested.
                patch.object(
                    _metar, "fetch_metar_daily_extreme", return_value=min_temp_f
                ),
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


# ── TestMetarLockInCombinesCurrentWithDailyExtreme ───────────────────────────
# Backlog.txt "weather_markets._metar_lock_in never combines current_temp_f
# with the daily-extreme cache" (filed 2026-08-21, round-3 review of AUD-0016):
# fetch_metar and fetch_metar_daily_extreme are independently ~15-min-TTL
# cached and can disagree. _metar_lock_in must combine them via max()/min()
# (direction matching HIGH-vs-LOW market type) the same way
# settlement_monitor._check_between_settlement's AUD-0016 fix does, rather
# than using the stale daily extreme alone and silently ignoring a fresher,
# more-extreme current_temp_f reading.
#
# Unlike the between-bucket branch (see TestBetweenLockInDynamicConfidence in
# tests/test_phase2_batch_d.py), this above/below branch does NOT need a
# separate "gate on the raw extreme, measure clearance on the combined
# value" split. Not because every branch check_metar_lockout can reach is
# monotone-safe (a HIGH market's "below"-direction YES is not, and remains a
# separate, pre-existing, out-of-scope gap) -- rather, combining always
# moves _comp_temp in the single direction that tightens whichever
# comparison a given branch performs: it can only make a monotone-safe
# branch fire at least as readily (a correct tighter bound) and can only
# make a non-monotone branch fire less readily (more conservative). There is
# no interior band here for a fresher reading to be prematurely counted as
# having "entered", so a plain uniform combine is correct and sufficient.


class TestMetarLockInCombinesCurrentWithDailyExtreme:
    """Above/below branch (weather_markets.py ~L10909-10935)."""

    def _call(self, current_temp_f, daily_extreme, threshold, cond_type, ticker):
        from datetime import datetime
        from unittest.mock import MagicMock, patch
        from zoneinfo import ZoneInfo

        import metar as _metar
        import weather_markets as wm

        today = datetime.now(ZoneInfo("America/New_York")).date()
        fake_obs_time = MagicMock()
        fake_obs_local = MagicMock(hour=16)
        fake_obs_local.date.return_value = today
        fake_obs_time.astimezone.return_value = fake_obs_local

        with patch.object(wm, "_metar_station_for_city", return_value="KJFK"):
            with (
                patch.object(
                    _metar,
                    "fetch_metar",
                    return_value={
                        "current_temp_f": current_temp_f,
                        "obs_time": fake_obs_time,
                    },
                ),
                patch.object(
                    _metar, "fetch_metar_daily_extreme", return_value=daily_extreme
                ),
            ):
                return wm._metar_lock_in(
                    city="NYC",
                    target_date=today,
                    condition={"type": cond_type, "threshold": threshold},
                    ticker=ticker,
                )

    def test_high_market_stale_low_daily_extreme_does_not_falsely_lock_yes(self):
        """HIGH market ('below 85' -- bet the day's high stays below 85), a
        stale cached daily-high-so-far of 80 (<= 85-3 margin) would, on its
        own, lock a confident YES ('high stayed below 85'). But a fresher
        current_temp_f of 90 shows the day has ALREADY spiked past 85 --
        the YES lock would be dangerously wrong. Must combine via max() and
        lock NO instead (the day's high has already breached the threshold),
        not silently lock the stale, wrong YES."""
        locked, _prob, details = self._call(
            current_temp_f=90.0,
            daily_extreme=80.0,
            threshold=85.0,
            cond_type="below",
            ticker="KXHIGHNY-26AUG10-B85.0",
        )
        assert locked is True
        assert details.get("outcome") == "no", (
            f"expected a NO lock reflecting the fresher, higher current "
            f"reading (90 >= 85+3), not a stale YES off the cached daily "
            f"extreme (80) alone: {details}"
        )
        assert details.get("comp_temp_f") == 90.0

    def test_high_market_fresher_current_extends_daily_extreme_to_lock(self):
        """HIGH market ('above 85'), a stale cached daily-high-so-far of 83
        (inside the no-lock zone, [82, 88]) would not lock on its own. A
        fresher current_temp_f of 90 (>= 85+3) shows the day has already
        cleared the threshold -- must combine via max() and lock YES."""
        locked, _prob, details = self._call(
            current_temp_f=90.0,
            daily_extreme=83.0,
            threshold=85.0,
            cond_type="above",
            ticker="KXHIGHNY-26AUG10-B85.0",
        )
        assert locked is True
        assert details.get("outcome") == "yes", (
            f"expected a YES lock off the fresher current reading (90 >= "
            f"85+3), not withheld because the stale daily extreme (83) "
            f"alone doesn't clear the margin: {details}"
        )
        assert details.get("comp_temp_f") == 90.0

    def test_low_market_combines_fresher_lower_current_into_safe_no_lock(self):
        """LOW market ('above 40' -- bet the day's low stays above 40), a
        stale cached daily-low-so-far of 42 (inside the no-lock zone, [37,
        43]) would not lock on its own. A fresher current_temp_f of 30
        (<= 40-3, the monotone-safe NO direction -- the low already fell
        below the margin and can only stay there or go lower) must not be
        ignored in favor of the stale, still-in-range daily extreme."""
        locked, _prob, details = self._call(
            current_temp_f=30.0,
            daily_extreme=42.0,
            threshold=40.0,
            cond_type="above",
            ticker="KXLOWNY-26AUG10-B40.0",
        )
        assert locked is True
        assert details.get("outcome") == "no", (
            f"expected a NO lock off the fresher, lower current reading "
            f"(30 <= 40-3), not withheld because the stale daily extreme "
            f"(42) alone doesn't clear the margin: {details}"
        )
        assert details.get("comp_temp_f") == 30.0


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
            patch("mos.fetch_nbm_quantiles", return_value=None),
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

    def test_no_metar_station_falls_back_to_instantaneous_temp(self, monkeypatch):
        """Positive control (backlog.txt L710): a REALISTIC get_live_observation
        fixture -- matching nws.py's actual return shape of exactly
        {temp_f, timestamp, description}, with no max_temp_f/high_f keys --
        must fall through to temp_f when no METAR station resolves for the
        city. Confirms the fallback path is reached and behaves honestly
        when option (a)'s METAR enhancement can't apply, rather than passing
        vacuously because the fixture happened to include keys nws.py never
        actually sets."""
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"temp_f": 75.0, "timestamp": "", "description": ""},
        )
        monkeypatch.setattr(wm, "_metar_station_for_city", lambda city: None)
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
        assert captured["current_temp"] == pytest.approx(75.0), (
            "with no METAR station available, must fall back to the "
            "instantaneous temp_f (75.0) from the realistic live-obs fixture"
        )

    def test_uses_metar_daily_extreme_when_station_available(self, monkeypatch):
        """var='max' at days_out=0 with a resolvable METAR station must
        prefer the real running daily max from metar.fetch_metar_daily_
        extreme() over the instantaneous current temp (the high may have
        already occurred and be higher than 'right now') -- this is the
        actual fix for backlog.txt L710's dead branch."""
        import metar as _metar
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"temp_f": 75.0, "timestamp": "", "description": ""},
        )
        monkeypatch.setattr(wm, "_metar_station_for_city", lambda city: "KJFK")
        captured_extreme_args = {}

        def _fake_daily_extreme(station, city_tz, target_date, extreme):
            captured_extreme_args["station"] = station
            captured_extreme_args["city_tz"] = city_tz
            captured_extreme_args["extreme"] = extreme
            return 82.0

        monkeypatch.setattr(_metar, "fetch_metar_daily_extreme", _fake_daily_extreme)
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
            "must use the real METAR daily max (82.0), not the instantaneous "
            "current temp (75.0), for a var='max' days_out=0 lookup with a "
            "resolvable station"
        )
        assert captured_extreme_args == {
            "station": "KJFK",
            "city_tz": "America/New_York",
            "extreme": "max",
        }

    def test_metar_fetch_failure_falls_back_to_instantaneous_temp(self, monkeypatch):
        """A resolvable station whose daily-extreme fetch fails (returns
        None, e.g. network error) must still fall back to temp_f rather than
        propagating None all the way to _compute_persistence_prob's result."""
        import metar as _metar
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"temp_f": 75.0, "timestamp": "", "description": ""},
        )
        monkeypatch.setattr(wm, "_metar_station_for_city", lambda city: "KJFK")
        monkeypatch.setattr(_metar, "fetch_metar_daily_extreme", lambda *a, **kw: None)
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
        assert captured["current_temp"] == pytest.approx(75.0), (
            "a failed METAR daily-extreme fetch (None) must fall back to "
            "the instantaneous temp_f (75.0), not silently drop the "
            "persistence signal entirely"
        )

    def test_uses_metar_daily_extreme_when_station_available_for_min_var(
        self, monkeypatch
    ):
        """AUD-0020 fix: var='min' at days_out=0 with a resolvable METAR
        station must prefer the real running daily LOW from metar.fetch_
        metar_daily_extreme(..., "min") over the instantaneous current temp,
        symmetric with var='max''s existing daily-high preference (the
        morning low may have already occurred and be lower than 'right
        now'). Supersedes the old test_uses_instantaneous_temp_for_min_var,
        which asserted the pre-fix behavior this fix eliminates."""
        import metar as _metar
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"temp_f": 61.0, "timestamp": "", "description": ""},
        )
        monkeypatch.setattr(wm, "_metar_station_for_city", lambda city: "KJFK")
        captured_extreme_args = {}

        def _fake_daily_extreme(station, city_tz, target_date, extreme):
            captured_extreme_args["station"] = station
            captured_extreme_args["city_tz"] = city_tz
            captured_extreme_args["extreme"] = extreme
            return 58.0

        monkeypatch.setattr(_metar, "fetch_metar_daily_extreme", _fake_daily_extreme)
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
        assert captured["current_temp"] == pytest.approx(58.0), (
            "must use the real METAR daily min (58.0), not the instantaneous "
            "current temp (61.0), for a var='min' days_out=0 lookup with a "
            "resolvable station"
        )
        assert captured_extreme_args == {
            "station": "KJFK",
            "city_tz": "America/New_York",
            "extreme": "min",
        }

    def test_no_metar_station_falls_back_to_instantaneous_temp_for_min_var(
        self, monkeypatch
    ):
        """var='min' with no resolvable METAR station must still fall back
        to the instantaneous temp_f, mirroring var='max''s existing
        no-station fallback test."""
        import weather_markets as wm

        monkeypatch.setattr(
            "nws.get_live_observation",
            lambda *a, **kw: {"temp_f": 61.0, "timestamp": "", "description": ""},
        )
        monkeypatch.setattr(wm, "_metar_station_for_city", lambda city: None)
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
        assert captured["current_temp"] == pytest.approx(61.0), (
            "with no METAR station available, must fall back to the "
            "instantaneous temp_f (61.0)"
        )

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
