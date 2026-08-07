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


def _rain_market(
    ticker, floor_strike, yes_bid=0, yes_ask=0, no_bid=0, strike_type="greater"
):
    """KXRAIN*M monthly rain-total ladder market. floor_strike/strike_type
    shape confirmed live 2026-08-06 against KXRAINNYCM/KXRAINCHIM/KXRAINSTPM
    -- Kalshi's own market fields, not derived from ticker/title text the
    way _market()'s temperature fixtures are. Price fields use the
    yes_bid_dollars/yes_ask_dollars string shape (opus-review-caught: the
    real current live API shape, matching tests/test_rain_markets.py's own
    _rain_market fixture -- coalesce_market_price/parse_market_price accept
    both that and the legacy yes_bid/yes_ask float shape _market() above
    uses, but this file's earlier draft used the legacy shape for a fixture
    whose docstring claimed to be live-verified, which it wasn't)."""
    return {
        "ticker": ticker,
        "title": f"Rain in {ticker.split('-')[0]} 2026?",
        "floor_strike": floor_strike,
        "strike_type": strike_type,
        "yes_bid_dollars": str(yes_bid),
        "yes_ask_dollars": str(yes_ask),
        "no_bid_dollars": str(no_bid),
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

    def test_monthly_rain_markets_grouped_by_city_and_month_no_violation_when_monotone(
        self,
    ):
        """backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE CHECK
        STILL BLANKET-EXCLUDES KXRAIN*M" (resolved 2026-08-06): KXRAIN*M
        monthly rain-total ladder brackets now reach _group_markets via a
        dedicated (city, "RAIN", year, month) key. floor_strike=1 priced
        high (0.80-0.85) and floor_strike=7 priced low (0.10-0.15) is
        monotone DECREASING as threshold increases -- the correct shape for
        precip_month_total's single-sided "total > threshold" rule -- so
        this must NOT produce a violation, same real values this test
        exercised before the blanket exclusion was removed."""
        markets = [
            _rain_market(
                "KXRAINSEAM-26JUL-1", floor_strike=1, yes_bid=0.80, yes_ask=0.85
            ),
            _rain_market(
                "KXRAINSEAM-26JUL-7", floor_strike=7, yes_bid=0.10, yes_ask=0.15
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_markets_do_not_log_date_extraction_warning(self):
        """Rain markets take a dedicated early branch in _group_markets
        (see the KXRAIN*M ticker-prefix check) and never reach the generic
        date_match/L-8-warning path at all now, so a well-formed rain
        market must never trigger that warning."""
        import logging

        markets = [
            _rain_market(
                "KXRAINSEAM-26JUL-1", floor_strike=1, yes_bid=0.80, yes_ask=0.85
            ),
        ]
        with self.assertNoLogs(level=logging.WARNING):
            find_violations(markets)

    def test_monthly_rain_violation_detected_and_flagged_shadow(self):
        """Inverted rain ladder (floor_strike=7 priced HIGHER than
        floor_strike=1) is a real monotonicity violation, the same shape as
        test_violation_detected -- but every rain-sourced Violation must
        come back with is_shadow=True (first pass, not yet graduated to
        live placement -- see consistency.find_violations's docstring)."""
        markets = [
            _rain_market(
                "KXRAINSEAM-26JUL-1", floor_strike=1, yes_bid=0.40, yes_ask=0.45
            ),
            _rain_market(
                "KXRAINSEAM-26JUL-7", floor_strike=7, yes_bid=0.55, yes_ask=0.60
            ),
        ]
        violations = find_violations(markets)
        self.assertGreater(len(violations), 0)
        for v in violations:
            self.assertTrue(v.is_shadow, f"rain violation must be shadow-flagged: {v}")
        # Unit must read "in" (inches), never "°" -- rain is not temperature.
        # Pins the actual rendering (opus-review-caught: a bare assertIn("in", ...)
        # would also pass on a mis-rounded ">7in)" vs ">7.0in)" -- this ties
        # the assertion to the real :g-formatted threshold too).
        self.assertIn(">7in)", violations[0].description)
        self.assertNotIn("°", violations[0].description)

    def test_monthly_rain_different_cities_not_compared(self):
        """Two different rain cities in the same month must never be
        pooled into one group -- mirrors test_different_series_not_compared
        for temperature."""
        markets = [
            _rain_market(
                "KXRAINSEAM-26JUL-1", floor_strike=1, yes_bid=0.40, yes_ask=0.45
            ),
            # Higher threshold, different city -- would be a violation if
            # wrongly grouped with Seattle's above.
            _rain_market(
                "KXRAINCHIM-26JUL-7", floor_strike=7, yes_bid=0.55, yes_ask=0.60
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_different_months_not_compared(self):
        """Same city, different accrual months must never be pooled --
        rain-specific case with no temperature analog (temperature's key is
        already per-day)."""
        markets = [
            _rain_market(
                "KXRAINSEAM-26JUL-1", floor_strike=1, yes_bid=0.40, yes_ask=0.45
            ),
            _rain_market(
                "KXRAINSEAM-26AUG-7", floor_strike=7, yes_bid=0.55, yes_ask=0.60
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_irregular_ladder_size_matches_real_st_petersburg_shape(
        self,
    ):
        """St. Petersburg's real July 2026 ladder (live-checked 2026-08-06)
        has exactly 10 brackets, floor_strike 1-10, all strike_type=greater
        -- a materially bigger/irregular shape than NYC's typical 4-7. A
        monotone-decreasing 10-bracket ladder must produce zero violations
        regardless of size."""
        markets = [
            _rain_market(
                f"KXRAINSTPM-26JUL-{n}",
                floor_strike=n,
                yes_bid=max(0.90 - n * 0.08, 0.02),
                yes_ask=max(0.95 - n * 0.08, 0.05),
            )
            for n in range(1, 11)
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_missing_floor_strike_excluded(self):
        """A rain market missing floor_strike (malformed/unexpected API
        shape) must be silently skipped, fail-closed -- never guessed,
        mirroring weather_markets._parse_market_condition's identical
        guard for the same ticker family."""
        m = _rain_market(
            "KXRAINSEAM-26JUL-1", floor_strike=1, yes_bid=0.80, yes_ask=0.85
        )
        m["floor_strike"] = None
        markets = [
            m,
            _rain_market(
                "KXRAINSEAM-26JUL-7", floor_strike=7, yes_bid=0.10, yes_ask=0.15
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_monthly_rain_unexpected_strike_type_excluded(self):
        """A rain market with strike_type != "greater" (never observed
        live, but a real Kalshi listing change could introduce one) must be
        skipped, not guessed at -- same fail-closed reasoning as
        weather_markets._parse_market_condition's identical branch."""
        markets = [
            _rain_market(
                "KXRAINSEAM-26JUL-1",
                floor_strike=1,
                yes_bid=0.80,
                yes_ask=0.85,
                strike_type="less",
            ),
            _rain_market(
                "KXRAINSEAM-26JUL-7", floor_strike=7, yes_bid=0.10, yes_ask=0.15
            ),
        ]
        self.assertEqual(find_violations(markets), [])

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

    def test_hurricane_next_event_markets_excluded(self):
        """backlog.txt "HURRICANE MARKETS" -- time-to-next-event model
        (2026-08-07): KXNEXTHURDATE/KXNEXTCAT5HURDATE tickers must never
        reach _group_markets either -- same reasoning as the hurricane-count
        exclusion above (KNOWN_WEATHER_SERIES now returns them, with no
        shadow-gate check of find_violations()'s own)."""
        markets = [
            _market(
                "KXNEXTHURDATE-26DEC01-26SEP15",
                yes_bid=0.10,
                yes_ask=0.15,
                series="KXNEXTHURDATE",
                title="hurricane before Sep 15 -- above threshold",
            ),
            _market(
                "KXNEXTHURDATE-26DEC01-26OCT01",
                yes_bid=0.80,
                yes_ask=0.85,  # priced HIGHER for a LATER date -- a real violation shape
                series="KXNEXTHURDATE",
                title="hurricane before Oct 1 -- above threshold",
            ),
        ]
        self.assertEqual(find_violations(markets), [])

    def test_hurricane_next_event_exclusion_is_mutation_proof(self):
        """Opus-review-caught (2026-08-07, MEDIUM): the test above is NOT
        actually mutation-proof -- real KXNEXTHURDATE tickers end in a date
        suffix ("-26SEP15"), which _parse_threshold's own `-T<n>`/`-B<n>`
        regex can't match, so those markets get dropped by the "if not
        parsed: continue" check regardless of whether the exclusion guard is
        present. Disabling the guard and re-running the exact test above
        still returns [] -- proving it, not just claiming it, would have
        caught this before it shipped. This test uses adversarial (not
        real-shape) tickers ending in "-T5"/"-T6" specifically because that
        IS a shape _parse_threshold matches, confirmed to produce a real
        violation with the guard removed -- the single genuine barrier
        between these tickers and the arb auto-placer's real
        paper.place_paper_order."""
        markets = [
            _market(
                "KXNEXTHURDATE-26SEP15-T5",
                yes_bid=0.10,
                yes_ask=0.15,
                series="KXNEXTHURDATE",
                title="hurricane threshold -- above 5",
            ),
            _market(
                "KXNEXTHURDATE-26SEP15-T6",
                yes_bid=0.80,
                yes_ask=0.85,
                series="KXNEXTHURDATE",
                title="hurricane threshold -- above 6",
            ),
        ]
        assert find_violations(markets) == []


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
