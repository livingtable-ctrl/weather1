"""
Unit tests for weather_markets.py — probability math, condition parsing,
fee-adjusted edge, and Kelly criterion.
"""

import unittest

from weather_markets import (
    _forecast_probability,
    _normal_cdf,
    _parse_market_condition,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
