"""
Unit tests for consistency.py — monotonicity / arbitrage detection.
"""

import unittest

from consistency import find_violations


def _market(ticker, yes_bid=0, yes_ask=0, no_bid=0, series=None, title=""):
    return {
        "ticker": ticker,
        "series_ticker": series or ticker.rsplit("-", 1)[0],
        "title": title,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
    }


class TestConsistency(unittest.TestCase):
    def test_no_violation_when_monotone(self):
        """
        Thresholds T60, T65, T70 should be monotone (higher temp = lower prob
        of exceeding): P(>70) < P(>65) < P(>60).
        """
        markets = [
            # P(>60) = 0.80 → yes_bid=0.78
            _market(
                "KXHIGH-26APR09-T60",
                yes_bid=0.78,
                yes_ask=0.82,
                series="KXHIGH-26APR09",
                title="high > 60",
            ),
            # P(>65) = 0.55 → yes_bid=0.53
            _market(
                "KXHIGH-26APR09-T65",
                yes_bid=0.53,
                yes_ask=0.57,
                series="KXHIGH-26APR09",
                title="high > 65",
            ),
            # P(>70) = 0.25 → yes_bid=0.23
            _market(
                "KXHIGH-26APR09-T70",
                yes_bid=0.23,
                yes_ask=0.27,
                series="KXHIGH-26APR09",
                title="high > 70",
            ),
        ]
        violations = find_violations(markets)
        self.assertEqual(violations, [])

    def test_violation_detected(self):
        """
        If P(>70) > P(>65) we have a monotonicity violation (free arbitrage).
        """
        markets = [
            _market(
                "KXHIGH-26APR09-T65",
                yes_bid=0.40,
                yes_ask=0.45,
                series="KXHIGH-26APR09",
                title="high > 65",
            ),
            # Inverted: P(>70) should be < P(>65) but here it's higher
            _market(
                "KXHIGH-26APR09-T70",
                yes_bid=0.55,
                yes_ask=0.60,
                series="KXHIGH-26APR09",
                title="high > 70",
            ),
        ]
        violations = find_violations(markets)
        # Should find at least one violation
        self.assertGreater(len(violations), 0)

    def test_single_market_no_violation(self):
        """A single market in a series can't violate monotonicity."""
        markets = [
            _market(
                "KXHIGH-26APR09-T68",
                yes_bid=0.45,
                yes_ask=0.50,
                series="KXHIGH-26APR09",
                title="high > 68",
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_different_series_not_compared(self):
        """Markets from different series should never be compared."""
        markets = [
            _market(
                "KXHIGHNY-26APR09-T65",
                yes_bid=0.40,
                yes_ask=0.45,
                series="KXHIGHNY-26APR09",
                title="NYC high > 65",
            ),
            # Higher threshold in a DIFFERENT series — not a violation
            _market(
                "KXHIGHCHI-26APR09-T70",
                yes_bid=0.55,
                yes_ask=0.60,
                series="KXHIGHCHI-26APR09",
                title="Chicago high > 70",
            ),
        ]
        self.assertEqual(find_violations(markets), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
