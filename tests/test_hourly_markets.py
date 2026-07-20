"""
Tests for backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" (KXTEMPxxxH)
Step 1 -- schema + safe discovery, no probability model yet. See
C:\\Users\\thesa\\.claude\\plans\\virtual-percolating-badger.md for the full plan.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAnalyzeTradeHourlyGuard:
    """analyze_trade() must return None immediately for KXTEMPxxxH tickers,
    before condition parsing, and must not affect existing daily/precip/snow
    tickers -- the safety-critical piece of Step 1 (see plan's "Context"
    section on the analyze_trade fall-through risk this guard prevents)."""

    def _analyze(self, ticker: str) -> dict | None:
        import weather_markets as wm

        return wm.analyze_trade({"ticker": ticker})

    def test_nyc_hourly_ticker_returns_none(self):
        assert self._analyze("KXTEMPNYCH-26JUL2008-T71.99") is None

    def test_austin_hourly_ticker_returns_none(self):
        assert self._analyze("KXTEMPAUSH-26JUL2008-T78.99") is None

    def test_chicago_hourly_ticker_returns_none(self):
        assert self._analyze("KXTEMPCHIH-26JUL2008-T85.99") is None

    def test_la_hourly_ticker_returns_none(self):
        assert self._analyze("KXTEMPLAXH-26JUL2008-T77.99") is None

    def test_dc_hourly_ticker_returns_none(self):
        assert self._analyze("KXTEMPDCH-26JUL2008-T82.99") is None

    def test_hourly_gate_counted(self):
        """The skip is counted via the existing _count_gate mechanism (same
        pattern every other analyze_trade gate uses), for scan-cycle
        visibility -- not a silent no-op."""
        import weather_markets as wm

        wm.reset_gate_counts()
        self._analyze("KXTEMPNYCH-26JUL2008-T71.99")
        counts = wm.get_gate_counts()
        assert counts.get("hourly_not_yet_supported") == 1

    def test_daily_ticker_unaffected_by_hourly_guard(self):
        """Regression: an ordinary daily-market enriched dict that would
        otherwise pass every gate must still reach the real temperature
        analysis path -- the hourly guard must not fire for it and must not
        alter its behavior. Mirrors tests/test_p0_11_retired_strategy.py's
        _make_enriched fixture shape."""
        import datetime

        import weather_markets as wm

        wm.reset_gate_counts()
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        enriched = {
            "ticker": "KXHIGH-26MAY10-T75",
            "series_ticker": "KXHIGH",
            "title": "Will the high temperature be above 75°F?",
            "_city": "NYC",
            "_date": tomorrow,
            "_hour": None,
            "_forecast": {
                "high_f": 78.0,
                "low_f": 60.0,
                "high_range": [77.0, 79.0],
                "low_range": [59.0, 61.0],
            },
        }
        wm.analyze_trade(enriched)
        counts = wm.get_gate_counts()
        assert counts.get("hourly_not_yet_supported", 0) == 0


class TestComputeMarketImpliedExcludesHourly:
    """compute_market_implied_distributions() groups by (city, target_date)
    independently of and before analyze_trade() -- the analyze_trade guard
    above does not protect it. Hourly brackets must not be silently pooled
    into a daily market's event group and corrupt its distribution fit."""

    def _daily_market(self, floor_strike, ticker_suffix, bid, ask):
        # bid/ask must decrease as floor_strike increases (a real "P(above
        # X)" curve) -- identical prices across strikes is a degenerate,
        # non-CDF-shaped input that fit_market_implied_distribution's
        # optimizer fails to converge on (verified live: an earlier version
        # of this fixture using flat 40/45 for every strike produced None,
        # silently making the whole mixed-vs-daily-only comparison a
        # vacuous None==None pass regardless of whether hourly brackets were
        # actually excluded).
        return {
            "ticker": f"KXHIGHNY-26JUL20-T{ticker_suffix}",
            "title": f"Will the high temp in NYC be above {floor_strike}°?",
            "close_time": "2026-07-20T23:00:00Z",
            "yes_bid": bid,
            "yes_ask": ask,
            "floor_strike": floor_strike,
            "volume_fp": 500,
        }

    def _hourly_market(self, floor_strike, ticker_suffix, bid, ask):
        return {
            "ticker": f"KXTEMPNYCH-26JUL2008-T{ticker_suffix}",
            "title": f"Will the temp in NYC be above {floor_strike}° at 8am EDT?",
            "close_time": "2026-07-20T12:00:00Z",
            "yes_bid": bid,
            "yes_ask": ask,
            "floor_strike": floor_strike,
            "volume_fp": 500,
        }

    def test_mixed_list_fit_matches_daily_only_fit(self):
        import weather_markets as wm

        daily_only = [
            self._daily_market(70.0, "70", 75, 80),
            self._daily_market(75.0, "75", 45, 50),
            self._daily_market(80.0, "80", 15, 20),
        ]
        # Same city/date as the daily markets, deliberately overlapping
        # strike range and a real above/below-parseable title/ticker shape
        # -- would genuinely get pooled into the same event group and shift
        # the fit if the exclusion were removed (verified below).
        hourly_extra = [
            self._hourly_market(70.0, "60", 90, 95),
            self._hourly_market(75.0, "65", 60, 65),
        ]

        fit_daily_only = wm.compute_market_implied_distributions(daily_only)
        fit_mixed = wm.compute_market_implied_distributions(daily_only + hourly_extra)

        assert fit_daily_only[("NYC", "2026-07-20")] is not None, (
            "test fixture itself is degenerate (fit didn't converge) -- "
            "this assertion isn't testing anything real"
        )
        assert fit_daily_only == fit_mixed, (
            "hourly brackets changed the daily market-implied fit -- they "
            "were not excluded before event-grouping"
        )


class TestHourlyTemperatureProxy:
    """compute_hourly_temperature_proxy / determine_hourly_target_hours --
    empirical target-hour determination from real settlement history
    (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 1)."""

    def _ladder(self, close_time, strikes_and_results):
        """strikes_and_results: list of (floor_strike, "yes"/"no")."""
        return [
            {
                "ticker": f"KXTEMPNYCH-x-T{strike}",
                "status": "finalized",
                "close_time": close_time,
                "floor_strike": strike,
                "result": result,
            }
            for strike, result in strikes_and_results
        ]

    def test_real_nyc_ladder_pulled_live_2026_07_20(self):
        """Ground truth: the exact ladder pulled live this session (NYC, Jul
        19 noon EDT = 2026-07-19T16:00:00Z) flipped yes->no between
        floor=74.99 and floor=75.99 -- proxy should be their midpoint."""
        import weather_markets as wm

        markets = self._ladder(
            "2026-07-19T16:00:00Z",
            [
                (70.99, "yes"),
                (71.99, "yes"),
                (72.99, "yes"),
                (73.99, "yes"),
                (74.99, "yes"),
                (75.99, "no"),
                (76.99, "no"),
                (77.99, "no"),
                (78.99, "no"),
                (79.99, "no"),
            ],
        )
        proxy_by_hour = wm.compute_hourly_temperature_proxy(markets, "America/New_York")
        # 16:00 UTC = 12:00 (noon) EDT
        assert proxy_by_hour == {12: [75.49]}

    def test_max_and_min_hour_identified_from_averaged_history(self):
        """Two days of an afternoon hour reading ~85 and two days of a
        pre-dawn hour reading ~60 -- max_hour/min_hour must pick out the
        correct LOCAL hour, averaged across days."""
        import weather_markets as wm

        # 3pm EDT = 19:00 UTC; 5am EDT = 09:00 UTC.
        markets = (
            self._ladder(
                "2026-07-18T19:00:00Z",
                [(83.0, "yes"), (84.0, "yes"), (85.0, "no"), (86.0, "no")],
            )
            + self._ladder(
                "2026-07-19T19:00:00Z",
                [(85.0, "yes"), (86.0, "yes"), (87.0, "no"), (88.0, "no")],
            )
            + self._ladder(
                "2026-07-18T09:00:00Z",
                [(58.0, "yes"), (59.0, "yes"), (60.0, "no"), (61.0, "no")],
            )
            + self._ladder(
                "2026-07-19T09:00:00Z",
                [(60.0, "yes"), (61.0, "yes"), (62.0, "no"), (63.0, "no")],
            )
        )
        result = wm.determine_hourly_target_hours(markets, "America/New_York")
        assert result == {"max_hour": 15, "min_hour": 5}

    def test_no_flip_hour_day_skipped_not_guessed(self):
        """A ladder that's all "yes" (true reading above every strike) has
        no clean flip and must be silently excluded, not produce a bogus
        proxy from the boundary strike."""
        import weather_markets as wm

        markets = self._ladder(
            "2026-07-19T19:00:00Z",
            [(83.0, "yes"), (84.0, "yes"), (85.0, "yes")],
        )
        proxy_by_hour = wm.compute_hourly_temperature_proxy(markets, "America/New_York")
        assert proxy_by_hour == {}

    def test_no_data_returns_none_hours(self):
        import weather_markets as wm

        result = wm.determine_hourly_target_hours([], "America/New_York")
        assert result == {"max_hour": None, "min_hour": None}

    def test_non_finalized_markets_excluded(self):
        """Only status=finalized markets have a real, settled `result` --
        active/initialized markets must not contribute a proxy."""
        import weather_markets as wm

        markets = [
            {
                "ticker": "KXTEMPNYCH-x-T75",
                "status": "active",
                "close_time": "2026-07-20T12:00:00Z",
                "floor_strike": 75.0,
                "result": "",
            },
        ]
        proxy_by_hour = wm.compute_hourly_temperature_proxy(markets, "America/New_York")
        assert proxy_by_hour == {}
