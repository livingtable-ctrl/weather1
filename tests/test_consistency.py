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

    def test_hourly_directional_markets_excluded(self):
        """backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 1:
        KXTEMPxxxH brackets must never reach _group_markets. Without the
        exclusion, two DIFFERENT hours' ladders for the same city/day would
        share the identical (series, date_str) grouping key (date_str is
        day-level only, no hour) and get compared for monotonicity as if
        they were one ladder -- these prices genuinely would trip the
        monotonicity check (mirrors test_violation_detected's inverted-price
        shape exactly) if not excluded, and find_violations() feeds directly
        into automatic corrective trading, unlike the log-only
        market-implied-distribution signal."""
        markets = [
            _market(
                "KXTEMPNYCH-26JUL2008-T65",
                yes_bid=0.40,
                yes_ask=0.45,
                series="KXTEMPNYCH",
                title="NYC temp > 65 at 8am",
            ),
            _market(
                "KXTEMPNYCH-26JUL2015-T70",
                yes_bid=0.55,
                yes_ask=0.60,
                series="KXTEMPNYCH",
                title="NYC temp > 70 at 3pm",
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_markets_excluded(self):
        """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 1: KXRAIN*M
        monthly rain-total ladder brackets must never reach _group_markets.
        Without the exclusion, this doesn't produce a false violation
        (date_match already fails to match these tickers, so they'd be
        dropped via the "not series or not date_str" skip regardless -- this
        assertion alone would NOT catch a removed exclusion, confirmed by
        mutation-testing it), but it WOULD log a spurious L-8 warning every
        scan (series resolves truthy from the ticker prefix while
        date_match stays None) -- see the companion log-noise assertion
        below, which IS the real regression guard."""
        markets = [
            _market(
                "KXRAINSEAM-26JUL-1",
                yes_bid=0.80,
                yes_ask=0.85,
                series="KXRAINSEAM",
                title="Rain in Seattle in Jul 2026?",
            ),
            _market(
                "KXRAINSEAM-26JUL-7",
                yes_bid=0.10,
                yes_ask=0.15,
                series="KXRAINSEAM",
                title="Rain in Seattle in Jul 2026?",
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_markets_do_not_log_date_extraction_warning(self):
        """The actual regression guard for the exclusion above: mutation-
        tested by temporarily removing consistency.py's KXRAIN*M exclusion
        and confirming this assertion fails (the L-8 warning fires) before
        restoring it. find_violations() returning [] alone (previous test)
        does NOT catch a removed exclusion -- only this log-absence check
        does."""
        import logging

        markets = [
            _market(
                "KXRAINSEAM-26JUL-1",
                yes_bid=0.80,
                yes_ask=0.85,
                series="KXRAINSEAM",
                title="Rain in Seattle in Jul 2026?",
            ),
        ]
        with self.assertNoLogs(level=logging.WARNING):
            find_violations(markets)

    def test_hurricane_count_markets_excluded(self):
        """backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03,
        opus-review-caught, HIGH): KXHURCTOT/KXHURCTOTMAJ/KXTROPSTORM
        tickers must never reach _group_markets. UNLIKE rain/snow's
        exclusion above, this one is NOT redundant with the date_match/
        _parse_threshold regexes -- these tickers embed a real day-level
        date ("KXHURCTOT-26DEC01-T9") AND a real "-T9" threshold suffix,
        both of which match. Title text containing "above" (simulating a
        possible future Kalshi phrasing, or a fallback match this session's
        live check didn't anticipate) is used here specifically so this
        test would catch a REAL violation if the exclusion were removed --
        not just a log warning, unlike the rain/snow tests above.
        find_violations() feeds directly into automatic corrective trading
        (paper.place_paper_order via main.py's arb auto-placer), which has
        no shadow-gate check of its own for this ticker family."""
        markets = [
            _market(
                "KXHURCTOT-26DEC01-T7",
                yes_bid=0.10,
                yes_ask=0.15,
                series="KXHURCTOT",
                title="more than 7 hurricanes -- above threshold",
            ),
            _market(
                "KXHURCTOT-26DEC01-T9",
                yes_bid=0.80,
                yes_ask=0.85,  # inverted: T9 priced HIGHER than T7 -- a real violation shape
                series="KXHURCTOT",
                title="more than 9 hurricanes -- above threshold",
            ),
        ]
        self.assertEqual(find_violations(markets), [])


class TestParseThresholdRealApiShape(unittest.TestCase):
    """_parse_threshold() with market.get("series_ticker") absent -- the
    real Kalshi response shape (confirmed live 2026-07-25 while fixing
    tracker.py's unrelated candlestick-backfill bug). Deliberately does NOT
    use the module's shared _market() helper above, since that helper
    always synthesizes a fake series_ticker and so the whole rest of this
    file exercises R26's series-prefix branch, which is dead in production.
    """

    def test_above_condition_derived_from_title_with_no_series_ticker(self):
        from consistency import _parse_threshold

        market = {
            "ticker": "KXLOWTPHX-26JUL26-T96",
            "title": "Will the minimum temperature in Phoenix be above 96°F?",
        }
        self.assertEqual(_parse_threshold(market), ("above", 96.0))

    def test_below_condition_derived_from_title_with_no_series_ticker(self):
        from consistency import _parse_threshold

        market = {
            "ticker": "KXHIGHCHI-26JUL26-T89",
            "title": "Will the high temp in Chicago be below 89°F?",
        }
        self.assertEqual(_parse_threshold(market), ("below", 89.0))

    def test_series_prefix_would_invert_these_two_real_ladders(self):
        """Regression guard for the exact bug an independent review found:
        if a ticker.split("-")[0]-style fallback were ever added to
        _parse_threshold (mirroring tracker.py's unrelated
        _derive_series_ticker fix), these two real market shapes would flip
        to the WRONG direction (KXLOWTPHX's "HIGH" substring absent, but a
        naive "series prefix decides direction" reading of KXHIGHCHI would
        say "above" when the real condition is "below"). This test locks in
        the CORRECT (title-derived) answer so that mistake would fail here
        immediately, not just get caught by a future live-arbitrage
        false-positive."""
        from consistency import _parse_threshold

        above_market = {
            "ticker": "KXLOWTPHX-26JUL26-T96",
            "title": "Will the minimum temperature in Phoenix be above 96°F?",
        }
        below_market = {
            "ticker": "KXHIGHCHI-26JUL26-T89",
            "title": "Will the high temp in Chicago be below 89°F?",
        }
        self.assertEqual(_parse_threshold(above_market)[0], "above")
        self.assertEqual(_parse_threshold(below_market)[0], "below")


if __name__ == "__main__":
    unittest.main(verbosity=2)
