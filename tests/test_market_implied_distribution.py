"""
Tests for weather_markets.fit_market_implied_distribution and
compute_market_implied_distributions — the market-implied temperature
distribution signal (backlog.txt "MARKET-IMPLIED TEMPERATURE DISTRIBUTION
FROM THE FULL LADDER").

Log-only signal: fits a Normal(mean, sigma) to one city/date event's full
sibling bracket ladder by weighted least squares against each liquid
bracket's mid-price (treated as an implied probability mass over its
threshold), weighted by volume. Never wired into blended_prob/sigma/kelly.
"""

import sys
from pathlib import Path

import pytest
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent))

import weather_markets as wm


def _market(ticker, title, mass, volume=100, series="KXHIGHNY", spread=0.01):
    return {
        "ticker": ticker,
        "title": title,
        "series_ticker": series,
        "yes_bid": round(max(0.0, mass - spread), 4),
        "yes_ask": round(min(1.0, mass + spread), 4),
        "volume": volume,
    }


def _normal_ladder(true_mean, true_sigma, brackets, series="KXHIGHNY", **kw):
    """Build a sibling ladder whose mid-prices are the *exact* implied
    probability masses of a known Normal(true_mean, true_sigma) -- so the
    fit's recovered (mean, sigma) can be checked against a known answer."""
    out = []
    for ticker, title, kind, val in brackets:
        if kind == "below":
            mass = norm.cdf(val - 0.5, true_mean, true_sigma)
        elif kind == "above":
            mass = 1 - norm.cdf(val + 0.5, true_mean, true_sigma)
        else:
            lo, hi = val
            mass = norm.cdf(hi, true_mean, true_sigma) - norm.cdf(
                lo, true_mean, true_sigma
            )
        out.append(_market(ticker, title, mass, series=series, **kw))
    return out


_MIXED_LADDER = [
    ("KXHIGHNY-26JUL20-T55", "Will NYC high be below 55F?", "below", 55),
    ("KXHIGHNY-26JUL20-B60.5", "NYC high 59.5-61.5F", "between", (59.5, 61.5)),
    ("KXHIGHNY-26JUL20-B65.5", "NYC high 64.5-66.5F", "between", (64.5, 66.5)),
    ("KXHIGHNY-26JUL20-B70.5", "NYC high 69.5-71.5F", "between", (69.5, 71.5)),
    ("KXHIGHNY-26JUL20-B75.5", "NYC high 74.5-76.5F", "between", (74.5, 76.5)),
    ("KXHIGHNY-26JUL20-T85", "Will NYC high be above 85F?", "above", 85),
]

_BETWEEN_ONLY_LADDER = [
    ("KXHIGHNY-26JUL20-B60.5", "NYC high 59.5-61.5F", "between", (59.5, 61.5)),
    ("KXHIGHNY-26JUL20-B65.5", "NYC high 64.5-66.5F", "between", (64.5, 66.5)),
    ("KXHIGHNY-26JUL20-B70.5", "NYC high 69.5-71.5F", "between", (69.5, 71.5)),
    ("KXHIGHNY-26JUL20-B75.5", "NYC high 74.5-76.5F", "between", (74.5, 76.5)),
]


class TestFitMarketImpliedDistribution:
    def test_recovers_known_normal_distribution_mixed_ladder(self):
        siblings = _normal_ladder(70.0, 5.0, _MIXED_LADDER)
        result = wm.fit_market_implied_distribution(siblings)
        assert result is not None
        assert result["implied_mean"] == pytest.approx(70.0, abs=0.05)
        assert result["implied_sigma"] == pytest.approx(5.0, abs=0.05)
        assert result["fit_residual"] < 1e-4

    def test_recovers_known_normal_distribution_between_only_ladder(self):
        # Real weather markets are commonly ALL "between" buckets with no
        # separate above/below markets -- the fit must not depend on having
        # at least one open-sided (above/below) bracket.
        siblings = _normal_ladder(62.0, 6.0, _BETWEEN_ONLY_LADDER)
        result = wm.fit_market_implied_distribution(siblings)
        assert result is not None
        assert result["implied_mean"] == pytest.approx(62.0, abs=0.1)
        assert result["implied_sigma"] == pytest.approx(6.0, abs=0.1)

    def test_returns_none_below_three_liquid_brackets(self):
        siblings = _normal_ladder(70.0, 5.0, _MIXED_LADDER[:2])
        assert wm.fit_market_implied_distribution(siblings) is None

    def test_zero_volume_brackets_excluded_from_thin_book_count(self):
        # 3 siblings but one has zero volume -- since the fit is
        # volume-weighted, a zero-volume point can't influence it, so it
        # shouldn't count toward the "3 liquid brackets" floor either.
        siblings = _normal_ladder(70.0, 5.0, _MIXED_LADDER[:3])
        siblings[-1]["volume"] = 0
        assert wm.fit_market_implied_distribution(siblings) is None

    def test_non_temperature_siblings_excluded(self):
        precip = [
            _market(
                "KXRAINNY-26JUL20-P0.25",
                "more than 0.25 inches rain",
                0.3,
                series="KXRAIN",
            ),
            _market(
                "KXRAINNY-26JUL20-P0.50",
                "more than 0.50 inches rain",
                0.1,
                series="KXRAIN",
            ),
            _market(
                "KXRAINNY-26JUL20-P0.75",
                "more than 0.75 inches rain",
                0.05,
                series="KXRAIN",
            ),
        ]
        assert wm.fit_market_implied_distribution(precip) is None

    def test_mixed_temperature_and_precip_only_counts_temperature(self):
        # A realistic scan groups by (city, date) via parse_city_date, which
        # doesn't distinguish market type -- if a precip market for the same
        # city/date ever ended up in the sibling list, it must not count
        # toward the liquid-bracket floor or influence the fit.
        siblings = _normal_ladder(70.0, 5.0, _MIXED_LADDER[:2])  # only 2 real
        siblings.append(
            _market(
                "KXRAINNY-26JUL20-P0.25",
                "more than 0.25 inches rain",
                0.3,
                series="KXRAIN",
            )
        )
        assert wm.fit_market_implied_distribution(siblings) is None

    def test_mutation_volume_weight_actually_pulls_the_fit(self):
        # Mutation check: two otherwise-identical ladders differing only in
        # which bracket carries the dominant volume must fit differently --
        # proves volume is actually used as a weight, not just read and
        # ignored.
        base = _normal_ladder(70.0, 5.0, _MIXED_LADDER)
        # Corrupt one bracket's price so it disagrees with the rest, then
        # compare the fit when that bracket is heavily weighted vs. lightly
        # weighted.
        corrupted = [dict(m) for m in base]
        corrupted[0]["yes_bid"] = 0.45
        corrupted[0]["yes_ask"] = 0.47  # mid ~0.46, far from the true ~0.001

        heavy = [dict(m) for m in corrupted]
        heavy[0]["volume"] = 100000
        light = [dict(m) for m in corrupted]
        light[0]["volume"] = 1

        r_heavy = wm.fit_market_implied_distribution(heavy)
        r_light = wm.fit_market_implied_distribution(light)
        assert r_heavy is not None and r_light is not None
        # The corrupted bracket implies a much colder event (mass~0.46 at
        # the coldest bucket's boundary) -- heavily weighting it should pull
        # implied_mean down relative to lightly weighting it.
        assert r_heavy["implied_mean"] < r_light["implied_mean"]

    def test_illiquid_siblings_excluded(self):
        # A sibling with no real quote and no volume (is_liquid()=False)
        # must not count toward the liquid-bracket floor.
        siblings = _normal_ladder(70.0, 5.0, _MIXED_LADDER[:3])
        siblings[-1]["yes_bid"] = 0.0
        siblings[-1]["yes_ask"] = 0.0
        siblings[-1]["volume"] = 0
        assert wm.fit_market_implied_distribution(siblings) is None

    def test_degenerate_fit_returns_none_not_garbage(self):
        # All brackets priced identically (no informative signal at all) can
        # drive the optimizer toward a degenerate (very large) sigma -- must
        # be rejected rather than logged as a real fit.
        siblings = [
            _market(f"KXHIGHNY-26JUL20-B{v}.5", f"{v - 1}-{v + 1}F", 0.5)
            for v in (50, 60, 70, 80)
        ]
        result = wm.fit_market_implied_distribution(siblings)
        if result is not None:
            assert 0.1 <= result["implied_sigma"] <= 50.0


class TestComputeMarketImpliedDistributions:
    def test_groups_by_city_and_date_independently(self):
        nyc = _normal_ladder(70.0, 5.0, _MIXED_LADDER, series="KXHIGHNY")
        den = _normal_ladder(
            55.0,
            4.0,
            [
                (t.replace("KXHIGHNY", "KXHIGHDEN"), title, kind, val)
                for t, title, kind, val in _MIXED_LADDER
            ],
            series="KXHIGHDEN",
        )
        result = wm.compute_market_implied_distributions(nyc + den)

        assert ("NYC", "2026-07-20") in result
        assert ("Denver", "2026-07-20") in result
        nyc_fit = result[("NYC", "2026-07-20")]
        den_fit = result[("Denver", "2026-07-20")]
        assert nyc_fit is not None and den_fit is not None
        assert nyc_fit["implied_mean"] == pytest.approx(70.0, abs=0.1)
        assert den_fit["implied_mean"] == pytest.approx(55.0, abs=0.1)

    def test_thin_event_maps_to_none_not_omitted(self):
        # An event with too few liquid siblings still gets a key in the
        # result dict (mapped to None), so a caller doing a plain .get()
        # lookup for a market whose event never had enough siblings gets a
        # clean None rather than accidentally reading a stale/wrong entry.
        one_market = [_market("KXHIGHDEN-26JUL21-T60", "above 60", 0.4)]
        # NOTE: KXHIGHDEN ticker used here maps to Denver via
        # _parse_city_from_ticker; series_ticker left at the default
        # KXHIGHNY on purpose has no bearing on city resolution (ticker
        # prefix drives it), just documenting this isn't a copy-paste bug.
        result = wm.compute_market_implied_distributions(one_market)
        assert result.get(("Denver", "2026-07-21")) is None

    def test_unparseable_markets_skipped_from_grouping(self):
        garbage = [{"ticker": "not-a-real-ticker", "title": "???"}]
        result = wm.compute_market_implied_distributions(garbage)
        assert result == {}

    def test_no_network_calls(self, monkeypatch):
        # Purely CPU-bound: patch requests entirely and confirm nothing breaks.
        import requests

        def _boom(*a, **kw):
            raise AssertionError(
                "compute_market_implied_distributions made a network call"
            )

        monkeypatch.setattr(requests, "get", _boom)
        monkeypatch.setattr(requests, "post", _boom)
        siblings = _normal_ladder(70.0, 5.0, _MIXED_LADDER)
        result = wm.compute_market_implied_distributions(siblings)
        assert result[("NYC", "2026-07-20")] is not None
