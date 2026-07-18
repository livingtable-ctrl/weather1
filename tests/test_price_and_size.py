"""
Tests for weather_markets._price_and_size — the shared entry-price/EV/Kelly
tail extracted from the precip/snow/temperature trade-analysis paths
(backlog.txt "ANALYZE-TRADE PRICING/EV/KELLY TAIL TRIPLICATED ACROSS
TEMP/PRECIP/SNOW PATHS").

Two layers:
  1. Direct unit tests on _price_and_size() with hand-computed expected
     values — exhaustive, mutation-testable, no mocking required.
  2. Characterization tests driving _analyze_precip_trade/_analyze_snow_trade/
     analyze_trade end-to-end (via the METAR-locked branch for the
     temperature path, which puts blended_prob under direct control and
     bypasses the unrelated ensemble/consensus/climatology blend pipeline)
     to prove the call-site wiring is correct, not just the helper in
     isolation.

The end-to-end characterization values here were cross-checked by running
the identical fixtures against the pre-refactor weather_markets.py (git
HEAD before this consolidation) — every field matched bit-for-bit except:
  - net_edge, off by ~1e-16 (float rounding-cadence noise from consolidating
    what used to be several separate round(x, 6) calls into one chain —
    immaterial, not a real behavior change), and
  - temp_no_side_empty_book's entry_side_edge: 0.75 (old, buggy) -> 0.05
    (new, fixed) — see test_temp_no_side_empty_book_entry_side_edge_bugfix.
"""

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import utils
import weather_markets as wm
from weather_markets import _price_and_size


def _prices(yes_ask, yes_bid):
    return wm.parse_market_price({"yes_ask": yes_ask, "yes_bid": yes_bid})


# ── Direct unit tests on _price_and_size ────────────────────────────────────


class TestPriceAndSizeYesSide:
    def test_entry_price_is_yes_ask(self):
        prices = _prices(yes_ask=0.60, yes_bid=0.55)
        r = _price_and_size(0.75, prices, {"type": "above"}, "yes", ci=(0.70, 0.80))
        assert r["entry_price"] == 0.60

    def test_net_ev_and_net_edge_hand_computed(self):
        prices = _prices(yes_ask=0.50, yes_bid=0.45)
        r = _price_and_size(0.70, prices, {"type": "above"}, "yes", ci=(0.70, 0.70))
        # payout = 1 - 0.50 = 0.50; net_ev = 0.7*0.5*1 - 0.3*0.5 = 0.35 - 0.15 = 0.20
        assert r["net_ev"] == pytest.approx(0.20, abs=1e-9)
        # net_edge = net_ev / entry_price = 0.20 / 0.50 = 0.40
        assert r["net_edge"] == pytest.approx(0.40, abs=1e-9)
        assert r["edge"] == pytest.approx(0.70 - prices["implied_prob"], abs=1e-9)

    def test_net_edge_capped_at_3(self):
        prices = _prices(yes_ask=0.01, yes_bid=0.005)
        r = _price_and_size(0.99, prices, {"type": "above"}, "yes", ci=(0.99, 0.99))
        assert r["net_edge"] == 3.0


class TestPriceAndSizeNoSide:
    def test_entry_price_uses_no_ask_not_no_bid(self):
        # no_ask = 1 - yes_bid (what we pay for NO), not 1 - yes_ask.
        prices = _prices(yes_ask=0.60, yes_bid=0.50)
        r = _price_and_size(0.30, prices, {"type": "above"}, "no", ci=(0.25, 0.35))
        assert r["entry_price"] == pytest.approx(1.0 - 0.50, abs=1e-9)

    def test_empty_bid_book_entry_price_fallback(self):
        # yes_bid == 0 (no real bid) -> entry_price falls back to 1 - market_prob.
        prices = _prices(yes_ask=0.30, yes_bid=0.0)
        market_prob = prices["implied_prob"]
        r = _price_and_size(0.10, prices, {"type": "above"}, "no", ci=(0.05, 0.15))
        assert r["entry_price"] == pytest.approx(1.0 - market_prob, abs=1e-9)

    def test_empty_bid_book_entry_side_edge_fallback_uses_1_minus_market_prob(self):
        """The bug this consolidation fixed: the NO-side entry_side_edge
        fallback (empty bid book) must use 1.0 - market_prob, not
        market_prob — using market_prob directly overstates edge below 0.5
        and understates it above 0.5 (see backlog.txt divergence note)."""
        prices = _prices(yes_ask=0.30, yes_bid=0.0)
        market_prob = prices["implied_prob"]  # 0.15
        blended_prob = 0.10
        r = _price_and_size(
            blended_prob, prices, {"type": "above"}, "no", ci=(0.05, 0.15)
        )
        expected = (1.0 - blended_prob) - (1.0 - market_prob)
        assert r["entry_side_edge"] == pytest.approx(expected, abs=1e-9)
        # Sanity: the old (buggy) formula would have given a very different answer.
        buggy = (1.0 - blended_prob) - market_prob
        assert abs(r["entry_side_edge"] - buggy) > 0.1


class TestPriceAndSizeCiAdjustedKelly:
    def test_no_consensus_capped_at_kelly_cap(self):
        prices = _prices(yes_ask=0.30, yes_bid=0.25)
        r = _price_and_size(
            0.90, prices, {"type": "above"}, "yes", ci=(0.85, 0.95), consensus=False
        )
        assert r["ci_adjusted_kelly"] <= utils.KELLY_CAP + 1e-9

    def test_consensus_raises_cap_to_kelly_cap_times_mult(self):
        prices = _prices(yes_ask=0.30, yes_bid=0.25)
        r = _price_and_size(
            0.90, prices, {"type": "above"}, "yes", ci=(0.85, 0.95), consensus=True
        )
        expected_cap = utils.KELLY_CAP * utils.KELLY_CAP_CONSENSUS_MULT
        assert r["ci_adjusted_kelly"] <= expected_cap + 1e-9
        # And it should actually reach a value only reachable with the higher cap
        # (i.e. strictly above the non-consensus cap) for this strong-edge fixture.
        r_no_consensus = _price_and_size(
            0.90, prices, {"type": "above"}, "yes", ci=(0.85, 0.95), consensus=False
        )
        assert r["ci_adjusted_kelly"] > r_no_consensus["ci_adjusted_kelly"]

    def test_default_consensus_cap_matches_hardcoded_033_at_default_env(self):
        # Locks in the backlog-mandated derivation: KELLY_CAP(0.25) * MULT(1.32) == 0.33.
        assert utils.KELLY_CAP == pytest.approx(0.25)
        assert utils.KELLY_CAP * utils.KELLY_CAP_CONSENSUS_MULT == pytest.approx(0.33)

    def test_extra_kelly_scales_applied_multiplicatively(self):
        prices = _prices(yes_ask=0.30, yes_bid=0.25)
        base = _price_and_size(0.90, prices, {"type": "above"}, "yes", ci=(0.85, 0.95))
        scaled = _price_and_size(
            0.90,
            prices,
            {"type": "above"},
            "yes",
            ci=(0.85, 0.95),
            extra_kelly_scales=(0.5,),
        )
        assert scaled["ci_adjusted_kelly"] == pytest.approx(
            base["ci_adjusted_kelly"] * 0.5, abs=1e-6
        )

    def test_condition_type_scale_reduces_precip_relative_to_temperature(self):
        prices = _prices(yes_ask=0.30, yes_bid=0.25)
        temp_r = _price_and_size(
            0.90, prices, {"type": "above"}, "yes", ci=(0.85, 0.95)
        )
        precip_r = _price_and_size(
            0.90, prices, {"type": "precip_snow"}, "yes", ci=(0.85, 0.95)
        )
        assert precip_r["ci_adjusted_kelly"] < temp_r["ci_adjusted_kelly"]

    def test_time_decay_shrinks_edge_metrics_but_not_entry_price(self):
        prices = _prices(yes_ask=0.60, yes_bid=0.55)
        full = _price_and_size(0.75, prices, {"type": "above"}, "yes", ci=(0.70, 0.80))
        decayed = _price_and_size(
            0.75, prices, {"type": "above"}, "yes", ci=(0.70, 0.80), time_decay=0.5
        )
        assert decayed["entry_price"] == full["entry_price"]
        assert decayed["edge"] == pytest.approx(full["edge"] * 0.5, abs=1e-9)
        assert decayed["entry_side_edge"] == pytest.approx(
            full["entry_side_edge"] * 0.5, abs=1e-9
        )
        assert decayed["net_edge"] == pytest.approx(full["net_edge"] * 0.5, abs=1e-9)

    def test_time_decay_applies_before_the_net_edge_3_cap_not_after(self):
        """Regression for a bug the opus review caught in this consolidation:
        the original temperature code computed
        min((net_ev/entry_price) * time_decay, 3.0) — decay INSIDE the cap.
        A naive extraction computed min(net_ev/entry_price, 3.0) * time_decay
        instead — decay OUTSIDE the cap — which silently halves net_edge
        (relative to the correct value) whenever the uncapped ratio exceeds
        3.0 and time_decay < 1.0, understating a real near-close trade's
        edge and potentially dropping it below a trade-gate threshold."""
        # entry_price=0.10 -> uncapped net_ev/entry_price for blended_prob=0.95
        # is well above 3.0, so this fixture exercises the cap boundary.
        prices = _prices(yes_ask=0.10, yes_bid=0.08)
        full = _price_and_size(0.95, prices, {"type": "above"}, "yes", ci=(0.95, 0.95))
        assert full["net_edge"] == 3.0  # uncapped value is far above 3.0

        decayed = _price_and_size(
            0.95, prices, {"type": "above"}, "yes", ci=(0.95, 0.95), time_decay=0.3
        )
        # Correct (decay-inside-cap): min(net_ev/entry_price * 0.3, 3.0).
        uncapped = decayed["net_ev"] / decayed["entry_price"]
        assert uncapped * 0.3 < 3.0, (
            "fixture must produce a decayed value under the cap"
        )
        assert decayed["net_edge"] == pytest.approx(uncapped * 0.3, abs=1e-9)
        # The bug this guards against: decay-outside-cap would give
        # min(uncapped, 3.0) * 0.3 == 3.0 * 0.3 == 0.9, which differs here.
        buggy = min(uncapped, 3.0) * 0.3
        assert decayed["net_edge"] != pytest.approx(buggy, abs=1e-9)


class TestPriceAndSizeYesSideAskFallback:
    def test_default_false_has_no_fallback_empty_ask_book(self):
        """Precip/snow's original behavior: no fallback when yes_ask==0 on a
        YES-side signal — entry_side_edge reference price is 0, matching the
        pre-consolidation precip/snow formula exactly (must NOT change)."""
        prices = _prices(yes_ask=0.0, yes_bid=0.40)  # yes_ask empty, mid=0.40
        r = _price_and_size(0.70, prices, {"type": "above"}, "yes", ci=(0.65, 0.75))
        assert r["entry_side_edge"] == pytest.approx(0.70 - 0.0, abs=1e-9)

    def test_true_falls_back_to_market_prob_empty_ask_book(self):
        """Temperature's original guard, restored via yes_side_ask_fallback=True:
        entry_side_edge reference price falls back to market_prob (mid) when
        yes_ask==0 on a YES-side signal — this consolidation must not silently
        drop it for the one path that had it."""
        prices = _prices(yes_ask=0.0, yes_bid=0.40)
        market_prob = prices["implied_prob"]  # mid = 0.40 (yes_ask==0 case)
        r = _price_and_size(
            0.70,
            prices,
            {"type": "above"},
            "yes",
            ci=(0.65, 0.75),
            yes_side_ask_fallback=True,
        )
        assert r["entry_side_edge"] == pytest.approx(0.70 - market_prob, abs=1e-9)


class TestPriceAndSizeMutation:
    """Mutation-style checks: strip a factor, confirm the output actually changes."""

    def test_removing_ci_scale_effect_changes_output(self):
        prices = _prices(yes_ask=0.30, yes_bid=0.25)
        narrow_ci = _price_and_size(
            0.90, prices, {"type": "above"}, "yes", ci=(0.89, 0.91)
        )
        wide_ci = _price_and_size(
            0.90, prices, {"type": "above"}, "yes", ci=(0.50, 0.99)
        )
        assert narrow_ci["ci_adjusted_kelly"] != wide_ci["ci_adjusted_kelly"]

    def test_consensus_flag_actually_changes_cap_behavior(self):
        prices = _prices(yes_ask=0.20, yes_bid=0.15)
        r_false = _price_and_size(
            0.95, prices, {"type": "above"}, "yes", ci=(0.90, 0.99), consensus=False
        )
        r_true = _price_and_size(
            0.95, prices, {"type": "above"}, "yes", ci=(0.90, 0.99), consensus=True
        )
        assert r_false["ci_adjusted_kelly"] != r_true["ci_adjusted_kelly"]


# ── Characterization tests: full call-site wiring (precip/snow/temp) ───────


class TestPrecipTradeWiring:
    def test_yes_side_normal_book(self):
        with (
            mock.patch.object(
                wm, "_fetch_ensemble_precip", lambda *a, **kw: [0.02] * 12
            ),
            mock.patch.object(wm, "climatological_prob", lambda *a, **kw: 0.30),
        ):
            enriched = {
                "_city": "NYC",
                "ticker": "KXRAINNY-26JUL20",
                "yes_ask": 0.30,
                "yes_bid": 0.20,
            }
            forecast = {"precip_in": 0.05}
            condition = {"type": "precip_any", "threshold": 0.0}
            target_date = date.today() + timedelta(days=1)
            coords = (40.7, -74.0, "America/New_York")
            r = wm._analyze_precip_trade(
                enriched, forecast, condition, target_date, coords
            )
        assert r is not None
        assert r["recommended_side"] == "yes"
        assert r["edge"] == pytest.approx(0.6246999999999999, abs=1e-9)
        assert r["entry_side_edge"] == pytest.approx(0.5747, abs=1e-4)
        assert r["kelly"] == pytest.approx(0.20525, abs=1e-6)
        assert r["ci_adjusted_kelly"] == pytest.approx(0.0, abs=1e-9)

    def test_no_side_empty_bid_book(self):
        with (
            mock.patch.object(
                wm, "_fetch_ensemble_precip", lambda *a, **kw: [0.001] * 12
            ),
            mock.patch.object(wm, "climatological_prob", lambda *a, **kw: 0.30),
        ):
            enriched = {
                "_city": "NYC",
                "ticker": "KXRAINNY-26JUL20",
                "yes_ask": 0.90,
                "yes_bid": 0.0,
            }
            forecast = {"precip_in": 0.05}
            condition = {"type": "precip_any", "threshold": 0.0}
            target_date = date.today() + timedelta(days=1)
            coords = (40.7, -74.0, "America/New_York")
            r = wm._analyze_precip_trade(
                enriched, forecast, condition, target_date, coords
            )
        assert r is not None
        assert r["recommended_side"] == "no"
        assert r["edge"] == pytest.approx(-0.3963, abs=1e-4)
        assert r["entry_side_edge"] == pytest.approx(0.3963, abs=1e-4)
        assert r["kelly"] == pytest.approx(0.2201666666666667, abs=1e-6)


class TestSnowTradeWiring:
    def test_yes_side_normal_book(self):
        with (
            mock.patch.object(
                wm, "_fetch_ensemble_precip", lambda *a, **kw: [0.3] * 12
            ),
            mock.patch.object(wm, "climatological_prob", lambda *a, **kw: 0.20),
        ):
            enriched = {
                "_city": "NYC",
                "ticker": "KXSNOWNY-26JAN20",
                "yes_ask": 0.25,
                "yes_bid": 0.15,
            }
            forecast = {"high_f": 30.0, "low_f": 20.0, "humidity_pct": 80.0}
            condition = {"type": "precip_snow", "threshold": 1.0}
            target_date = date(2026, 1, 20)
            coords = (40.7, -74.0, "America/New_York")
            r = wm._analyze_snow_trade(
                enriched, forecast, condition, target_date, coords
            )
        assert r is not None
        assert r["recommended_side"] == "yes"
        assert r["edge"] == pytest.approx(0.6568, abs=1e-4)
        assert r["kelly"] == pytest.approx(0.20226666666666668, abs=1e-6)
        # ens_prob (0.3-members path), clim_prior (0.20), and blended_prob don't
        # all agree on direction here, so snow_consensus is False for this fixture.
        assert r["consensus"] is False

    def test_no_side_empty_bid_book(self):
        with (
            mock.patch.object(
                wm, "_fetch_ensemble_precip", lambda *a, **kw: [0.001] * 12
            ),
            mock.patch.object(wm, "climatological_prob", lambda *a, **kw: 0.20),
        ):
            enriched = {
                "_city": "NYC",
                "ticker": "KXSNOWNY-26JAN20",
                "yes_ask": 0.85,
                "yes_bid": 0.0,
            }
            forecast = {"high_f": 30.0, "low_f": 20.0, "humidity_pct": 80.0}
            condition = {"type": "precip_snow", "threshold": 1.0}
            target_date = date(2026, 1, 20)
            coords = (40.7, -74.0, "America/New_York")
            r = wm._analyze_snow_trade(
                enriched, forecast, condition, target_date, coords
            )
        assert r is not None
        assert r["recommended_side"] == "no"
        assert r["entry_side_edge"] == pytest.approx(0.3892, abs=1e-4)
        assert r["kelly"] == pytest.approx(0.2289411764705882, abs=1e-6)
        # Dry ensemble (0.001 members -> ens_prob near 0), clim_prior (0.20) and
        # blended_prob both land below 0.5 here, so all three agree -> True.
        assert r["consensus"] is True

    def test_consensus_bonus_actually_raises_ci_adjusted_kelly(self):
        # Mutation check: an ens_prob/clim_prior/blended_prob agreement fixture
        # must produce a strictly higher ci_adjusted_kelly than an otherwise-
        # identical fixture where clim_prior disagrees with the ensemble
        # (snow_consensus=False) -- proves the wiring actually reaches
        # _price_and_size's consensus bonus, not just that the field is set.
        # _bootstrap_ci_precip is pinned (not just given a spread-inducing
        # members list) because it draws from unseeded random.choices --
        # without pinning it, the two calls below get independent random CIs
        # and the assertion is flaky (~2.5% false-fail; see backlog.txt's
        # implementation-style memory item 11 on unseeded-RNG test traps).
        members = [0.05, 0.08, 0.1, 0.12, 0.15, 0.18, 0.2, 0.22, 0.25, 0.28, 0.3, 0.35]
        common = dict(
            enriched={
                "_city": "NYC",
                "ticker": "KXSNOWNY-26JAN20",
                "yes_ask": 0.20,
                "yes_bid": 0.10,
            },
            forecast={"high_f": 25.0, "low_f": 15.0, "humidity_pct": 85.0},
            condition={"type": "precip_snow", "threshold": 2.0},
            target_date=date(2026, 1, 20),
            coords=(40.7, -74.0, "America/New_York"),
        )
        with (
            mock.patch.object(wm, "_fetch_ensemble_precip", lambda *a, **kw: members),
            mock.patch.object(wm, "climatological_prob", lambda *a, **kw: 0.90),
            mock.patch.object(
                wm, "_bootstrap_ci_precip", lambda *a, **kw: (0.4167, 0.9167)
            ),
        ):
            r_consensus = wm._analyze_snow_trade(**common)
        with (
            mock.patch.object(wm, "_fetch_ensemble_precip", lambda *a, **kw: members),
            mock.patch.object(wm, "climatological_prob", lambda *a, **kw: 0.05),
            mock.patch.object(
                wm, "_bootstrap_ci_precip", lambda *a, **kw: (0.4167, 0.9167)
            ),
        ):
            r_no_consensus = wm._analyze_snow_trade(**common)
        assert r_consensus["consensus"] is True
        assert r_no_consensus["consensus"] is False
        assert r_consensus["ci_adjusted_kelly"] > r_no_consensus["ci_adjusted_kelly"]


def _metar_locked_temp_result(yes_ask, yes_bid, blended_prob, current_temp_f):
    tomorrow = date.today() + timedelta(days=1)
    close_time = (datetime.now(UTC) + timedelta(hours=20)).isoformat()
    enriched = {
        "_forecast": {"high_f": 75.0, "low_f": 55.0, "precip_in": 0.0, "wind_mph": 5.0},
        "_date": tomorrow,
        "_city": "NYC",
        "_hour": None,
        "ticker": "KXHIGHNY-26JUL20-T72",
        "title": "Will NYC high temperature be above 72F?",
        "series_ticker": "KXHIGH-23-NYC",
        "yes_ask": yes_ask,
        "yes_bid": yes_bid,
        "volume": 500,
        "open_interest": 200,
        "close_time": close_time,
    }
    lockout = {"reason": "test-metar-lock", "current_temp_f": current_temp_f}
    with (
        mock.patch.object(
            wm, "_metar_lock_in", lambda *a, **kw: (True, blended_prob, lockout)
        ),
        mock.patch.object(wm, "_SEASONAL_WEIGHTS", {}),
        mock.patch.object(wm, "_CONDITION_WEIGHTS", {}),
        mock.patch.object(wm, "_CITY_WEIGHTS", {}),
    ):
        return wm.analyze_trade(enriched)


class TestTemperatureTradeWiring:
    """Uses the METAR-locked branch to put blended_prob under direct control,
    isolating the entry-price/EV/Kelly tail from the unrelated ensemble blend
    pipeline. See module docstring for the pre-refactor cross-check."""

    def test_yes_side_normal_book(self):
        r = _metar_locked_temp_result(
            yes_ask=0.60, yes_bid=0.55, blended_prob=0.75, current_temp_f=74.0
        )
        assert r is not None
        assert r["recommended_side"] == "yes"
        assert r["entry_price"] == pytest.approx(0.60, abs=1e-9)
        assert r["edge"] == pytest.approx(0.17500000000000004, abs=1e-9)
        assert r["entry_side_edge"] == pytest.approx(0.15, abs=1e-9)
        assert r["kelly"] == pytest.approx(0.09374999999999999, abs=1e-9)
        assert r["fee_adjusted_kelly"] == r["kelly"]
        assert r["ci_adjusted_kelly"] == pytest.approx(0.05601, abs=1e-5)
        assert r["consensus"] is True

    def test_no_side_empty_bid_book_entry_side_edge_bugfix(self):
        """The consolidation's one deliberate behavior change: temperature's
        NO-side entry_side_edge fallback (empty bid book) previously used
        market_prob directly instead of 1.0 - market_prob, unlike the
        already-fixed precip/snow copies. Confirmed via a pre-refactor A/B
        run: old value was 0.75, new (correct) value is 0.05."""
        r = _metar_locked_temp_result(
            yes_ask=0.30, yes_bid=0.0, blended_prob=0.10, current_temp_f=68.0
        )
        assert r is not None
        assert r["recommended_side"] == "no"
        assert r["entry_price"] == pytest.approx(0.85, abs=1e-9)
        assert r["entry_side_edge"] == pytest.approx(0.05, abs=1e-6)
        # The old, buggy formula would have produced 0.75 here — assert we're
        # nowhere near it.
        assert abs(r["entry_side_edge"] - 0.75) > 0.5
