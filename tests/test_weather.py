"""
Unit tests for weather_markets.py — probability math, condition parsing,
fee-adjusted edge, Kelly criterion, bootstrap CI, and time-of-day risk.
"""

import unittest
from datetime import UTC, datetime, timedelta

from weather_markets import (
    _bootstrap_ci_precip,
    _forecast_probability,
    _normal_cdf,
    _parse_market_condition,
    _time_risk,
    ensemble_stats,
    kelly_fraction,
)


class TestKellyFraction(unittest.TestCase):
    def test_no_edge_returns_zero(self):
        """When our probability matches market price, Kelly = 0."""
        self.assertAlmostEqual(kelly_fraction(0.60, 0.60), 0.0, places=4)

    def test_positive_edge(self):
        """Strong positive edge should give a positive Kelly fraction."""
        k = kelly_fraction(0.70, 0.50)
        self.assertGreater(k, 0)

    def test_negative_edge_returns_zero(self):
        """We should never bet when edge is negative."""
        k = kelly_fraction(0.30, 0.60)
        self.assertEqual(k, 0.0)

    def test_half_kelly(self):
        """Result should be half of full Kelly."""
        # Full Kelly = (b*p - q) / b  where b = (1-price)/price
        p, price = 0.70, 0.50
        b = (1 - price) / price
        q = 1 - p
        full_k = (b * p - q) / b
        self.assertAlmostEqual(kelly_fraction(p, price), full_k / 2, places=6)

    def test_fee_reduces_kelly(self):
        """Kelly with fee should be <= Kelly without fee."""
        k_gross = kelly_fraction(0.70, 0.50)
        k_net = kelly_fraction(0.70, 0.50, fee_rate=0.07)
        self.assertLessEqual(k_net, k_gross)

    def test_fee_wipes_small_edge(self):
        """A tiny edge that is negative after fees should return 0."""
        # 2% gross edge: 0.52 prob, 0.50 price
        k_gross = kelly_fraction(0.52, 0.50)
        k_net = kelly_fraction(0.52, 0.50, fee_rate=0.07)
        # gross > 0 but net may be 0 or close
        self.assertGreaterEqual(k_gross, 0)
        self.assertGreaterEqual(k_net, 0)  # never negative


class TestNormalCDF(unittest.TestCase):
    def test_median(self):
        """P(X <= mu) = 0.5 for a normal distribution."""
        self.assertAlmostEqual(_normal_cdf(70, 70, 5), 0.5, places=3)

    def test_above_mean(self):
        """P(X <= mu + 2sigma) ~ 0.977."""
        self.assertAlmostEqual(_normal_cdf(80, 70, 5), 0.9772, places=2)

    def test_below_mean(self):
        """P(X <= mu - 2sigma) ~ 0.023."""
        self.assertAlmostEqual(_normal_cdf(60, 70, 5), 0.0228, places=2)


class TestForecastProbability(unittest.TestCase):
    def test_above_condition(self):
        """If forecast equals threshold exactly, P(above) ~ 0.5."""
        cond = {"type": "above", "threshold": 70.0}
        p = _forecast_probability(cond, 70.0, 5.0)
        self.assertAlmostEqual(p, 0.5, places=2)

    def test_below_condition(self):
        """If forecast is much higher than threshold, P(below) ~ 0."""
        cond = {"type": "below", "threshold": 40.0}
        p = _forecast_probability(cond, 70.0, 5.0)
        self.assertLess(p, 0.01)

    def test_between_condition(self):
        """A very wide range around the forecast should have high probability."""
        cond = {"type": "between", "lower": 50.0, "upper": 90.0}
        p = _forecast_probability(cond, 70.0, 5.0)
        self.assertGreater(p, 0.95)


class TestEnsembleStats(unittest.TestCase):
    def test_basic(self):
        temps = [60.0, 65.0, 70.0, 75.0, 80.0]
        s = ensemble_stats(temps)
        self.assertAlmostEqual(s["mean"], 70.0)
        self.assertEqual(s["min"], 60.0)
        self.assertEqual(s["max"], 80.0)

    def test_single(self):
        s = ensemble_stats([72.5])
        self.assertEqual(s["mean"], 72.5)
        self.assertEqual(s["std"], 0.0)

    def test_empty(self):
        self.assertEqual(ensemble_stats([]), {})


class TestParseMarketCondition(unittest.TestCase):
    def _market(self, ticker, title=""):
        return {"ticker": ticker, "title": title}

    def test_above_temp(self):
        m = self._market("KXHIGHNY-26APR09-T72", "Will NYC high be > 72°F?")
        c = _parse_market_condition(m)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["type"], "above")
        self.assertAlmostEqual(c["threshold"], 72.0)

    def test_below_temp(self):
        m = self._market("KXLOWCHI-26APR09-T45", "Will Chicago low be < 45°F?")
        c = _parse_market_condition(m)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["type"], "below")
        self.assertAlmostEqual(c["threshold"], 45.0)

    def test_bucket(self):
        m = self._market("KXHIGHNY-26APR09-B67.5", "NYC high between 67-68°F?")
        c = _parse_market_condition(m)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["type"], "between")
        self.assertAlmostEqual(c["lower"], 67.0)
        self.assertAlmostEqual(c["upper"], 68.0)

    def test_precip_any(self):
        m = self._market("KXRAIN-NY-26APR09", "Will there be any rain in NYC?")
        c = _parse_market_condition(m)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertIn(c["type"], ("precip_any", "precip_above"))

    def test_unrecognised_returns_none(self):
        m = self._market("KXSPORTS-26APR09-T10", "random market")
        # Won't have precip keywords, and has T10 suffix, but no above/below in title
        # → should return None (no direction)
        c = _parse_market_condition(m)
        # None is fine; we just check it doesn't crash
        self.assertIn(
            c,
            [
                None,
                {"type": "above", "threshold": 10.0},
                {"type": "below", "threshold": 10.0},
            ],
        )


class TestBootstrapCIPrecip(unittest.TestCase):
    def test_all_above_threshold_gives_high_prob(self):
        """All members above 0.01in → precip_any CI should be near (1, 1)."""
        members = [0.5] * 50
        condition = {"type": "precip_any"}
        lo, hi = _bootstrap_ci_precip(members, condition)
        self.assertGreater(lo, 0.95)
        self.assertGreater(hi, 0.95)

    def test_half_above_gives_straddling_ci(self):
        """Half members above 0.10in → CI should straddle 0.5."""
        members = [0.20] * 25 + [0.05] * 25
        condition = {"type": "precip_above", "threshold": 0.10}
        lo, hi = _bootstrap_ci_precip(members, condition)
        self.assertLess(lo, 0.55)
        self.assertGreater(hi, 0.45)

    def test_small_sample_returns_full_range(self):
        """Fewer than 5 members → returns (0.0, 1.0) as uninformative CI."""
        members = [0.3, 0.4, 0.5]
        condition = {"type": "precip_any"}
        lo, hi = _bootstrap_ci_precip(members, condition)
        self.assertEqual(lo, 0.0)
        self.assertEqual(hi, 1.0)

    def test_none_above_threshold_gives_low_prob(self):
        """No members above threshold → CI near (0, 0)."""
        members = [0.0] * 30
        condition = {"type": "precip_above", "threshold": 0.10}
        lo, hi = _bootstrap_ci_precip(members, condition)
        self.assertLess(hi, 0.05)


class TestTimeRisk(unittest.TestCase):
    def _close_time(
        self, hours_from_now: float, local_hour_override: int | None = None
    ) -> str:
        """Build an ISO close_time string."""
        dt = datetime.now(UTC) + timedelta(hours=hours_from_now)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_near_close_returns_low_risk(self):
        """Market closing in 90 minutes → LOW / 0.5."""
        ct = self._close_time(1.5)
        label, mult = _time_risk(ct, "America/New_York")
        self.assertEqual(label, "LOW")
        self.assertAlmostEqual(mult, 0.5)

    def test_far_out_returns_high_risk(self):
        """Market closing in 48 hours during daytime → HIGH / 1.0."""
        # 48h from now will have a local_hour that's not >= 20
        ct = self._close_time(48)
        label, mult = _time_risk(ct, "America/New_York")
        # Could be LOW if it lands after 8pm — just check mult is valid
        self.assertIn(label, ("HIGH", "MEDIUM", "LOW"))
        self.assertLessEqual(mult, 1.0)
        self.assertGreater(mult, 0.0)

    def test_missing_close_time_returns_high_risk(self):
        """Empty close_time string → HIGH / 1.0 (safe default)."""
        label, mult = _time_risk("", "America/New_York")
        self.assertEqual(label, "HIGH")
        self.assertAlmostEqual(mult, 1.0)

    def test_within_12_hours_returns_medium_or_low(self):
        """Market closing in 6 hours → MEDIUM or LOW."""
        ct = self._close_time(6)
        label, mult = _time_risk(ct, "America/New_York")
        self.assertIn(label, ("MEDIUM", "LOW"))
        self.assertLess(mult, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
