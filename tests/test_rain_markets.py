"""
Tests for backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 1 (schema +
safe discovery for KXRAIN*M monthly rain-total ladder markets -- zero
live-trading behavior change, no probability model yet).
"""

from __future__ import annotations


class TestAnalyzeTradeMonthlyRainGuard:
    """analyze_trade() must return None immediately for any KXRAIN*M
    monthly rain-total ticker (unconditional -- unlike the hourly guard,
    Step 1 has zero model for rain at all), before condition parsing, and
    must not affect existing daily/precip/snow/hourly tickers."""

    def test_seattle_rain_ticker_returns_none(self):
        import weather_markets as wm

        assert wm.analyze_trade({"ticker": "KXRAINSEAM-26JUL-1"}) is None

    def test_la_rain_ticker_returns_none(self):
        import weather_markets as wm

        assert wm.analyze_trade({"ticker": "KXRAINLAXM-26JUL-7"}) is None

    def test_denver_rain_ticker_returns_none(self):
        import weather_markets as wm

        assert wm.analyze_trade({"ticker": "KXRAINDENM-26JUL-4"}) is None

    def test_monthly_rain_gate_counted(self):
        """The skip is counted via the existing _count_gate mechanism (same
        pattern every other analyze_trade gate uses), for scan-cycle
        visibility -- not a silent no-op. Distinct gate name from hourly's
        "hourly_not_target_hour" so gate-count telemetry stays
        distinguishable."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXRAINSEAM-26JUL-1"})
        counts = wm.get_gate_counts()
        assert counts.get("monthly_rain_not_yet_supported") == 1

    def test_daily_high_ticker_unaffected(self):
        """Regression control: an ordinary daily HIGH ticker must not be
        caught by the new monthly-rain guard (would fail downstream on
        missing forecast data, not the new guard -- confirmed by checking
        the gate count, not just that the result differs)."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXHIGHNY-26JUL20-T70"})
        counts = wm.get_gate_counts()
        assert counts.get("monthly_rain_not_yet_supported") is None


class TestComputeMarketImpliedExcludesMonthlyRain:
    """compute_market_implied_distributions() groups by (city, target_date)
    independently of and before analyze_trade() -- the analyze_trade guard
    above does not protect it. Monthly-rain brackets have no day component,
    so parse_city_date() already returns None for them and the loop's own
    "city is None or target_date is None" skip would drop them regardless --
    this exclusion is a forward-guard (protects against Kalshi ever adding a
    day component, or _KXRAIN_MONTHLY_CITY diverging from what
    parse_city_date() actually parses), verified here by confirming a
    mixed list produces an identical fit to a daily-only list."""

    def _daily_market(self, floor_strike, ticker_suffix, bid, ask):
        # bid/ask must decrease as floor_strike increases (a real "P(above
        # X)" curve) -- identical prices across strikes is a degenerate,
        # non-CDF-shaped input the optimizer fails to converge on.
        return {
            "ticker": f"KXHIGHNY-26JUL20-T{ticker_suffix}",
            "title": f"Will the high temp in NYC be above {floor_strike}°?",
            "close_time": "2026-07-20T23:00:00Z",
            "yes_bid": bid,
            "yes_ask": ask,
            "floor_strike": floor_strike,
            "volume_fp": 500,
        }

    def _rain_market(self, floor_strike, bid, ask):
        return {
            "ticker": f"KXRAINSEAM-26JUL-{int(floor_strike)}",
            "title": "Rain in Seattle in Jul 2026?",
            "close_time": "2026-08-01T03:59:59Z",
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
        rain_extra = [
            self._rain_market(1, 80, 85),
            self._rain_market(7, 10, 15),
        ]

        fit_daily_only = wm.compute_market_implied_distributions(daily_only)
        fit_mixed = wm.compute_market_implied_distributions(daily_only + rain_extra)

        assert fit_daily_only[("NYC", "2026-07-20")] is not None, (
            "test fixture itself is degenerate (fit didn't converge) -- "
            "this assertion isn't testing anything real"
        )
        assert fit_daily_only == fit_mixed, (
            "monthly-rain brackets changed the daily market-implied fit -- "
            "they were not excluded before event-grouping"
        )

    def test_rain_only_list_produces_no_distributions(self):
        """Vacuous today on its own -- parse_city_date() already returns
        target_date=None for rain tickers, so the loop's own "city is None
        or target_date is None" skip drops them regardless of the explicit
        prefix exclusion (confirmed by mutation-testing: deleting the
        exclusion leaves this assertion green). Real regression coverage
        for the exclusion itself is the next test."""
        import weather_markets as wm

        rain_only = [self._rain_market(1, 80, 85), self._rain_market(7, 10, 15)]
        result = wm.compute_market_implied_distributions(rain_only)
        assert result == {}

    def test_exclusion_holds_even_if_a_date_were_parseable(self, monkeypatch):
        """The real regression guard for the explicit prefix exclusion
        (weather_markets.py ~4746) -- the exclusion is a documented
        forward-guard against Kalshi ever adding a day component to these
        tickers, or _KXRAIN_MONTHLY_CITY diverging from what
        parse_city_date() actually parses. Simulates exactly that scenario
        by patching parse_city_date() to return a real (city, date) for a
        rain ticker (as if the ticker format had changed to include a day),
        and confirms the explicit prefix check still excludes it -- proving
        the guard does real work, not just coincidentally agreeing with
        parse_city_date()'s current None-return behavior."""
        import weather_markets as wm

        real_parse_city_date = wm.parse_city_date

        def _fake_parse_city_date(market):
            if market.get("ticker", "").upper().startswith("KXRAINSEAM"):
                from datetime import date

                return ("Seattle", date(2026, 7, 20))
            return real_parse_city_date(market)

        monkeypatch.setattr(wm, "parse_city_date", _fake_parse_city_date)

        daily_only = [self._daily_market(70.0, "70", 75, 80)]
        rain_market = self._rain_market(1, 80, 85)

        result = wm.compute_market_implied_distributions(daily_only + [rain_market])

        assert ("Seattle", "2026-07-20") not in result, (
            "rain market reached event-grouping despite a now-parseable date -- "
            "the explicit prefix exclusion did not fire"
        )


class TestCheckPositionLimitsBlocksMonthlyRain:
    """paper.check_position_limits() must refuse ANY qty/price for a
    monthly-rain ticker, before any other check runs -- this is the one
    genuinely reachable gap in Step 1 (not just defense-in-depth): main.py's
    manual "place order with explicit ticker+qty" command resolves
    city/target_date_str via a forecast-free enrichment and calls this
    function directly, bypassing analyze_trade() entirely when qty is given
    explicitly. Since target_date_str stays None for rain tickers, the
    city/date/directional/correlated-group caps would already be skipped --
    only the flat per-market/portfolio caps would still apply -- so this
    must block outright, not rely on those partial caps."""

    def test_blocks_regardless_of_qty_and_price(self):
        import paper

        result = paper.check_position_limits("KXRAINSEAM-26JUL-1", qty=1, price=0.10)
        assert result["ok"] is False
        assert "rain" in result["reason"].lower()

    def test_blocks_even_for_tiny_order(self):
        """A single $0.01 contract must still be blocked -- this is a
        no-model gate, not a sizing/exposure cap that scales with the
        order's cost."""
        import paper

        result = paper.check_position_limits("KXRAINDENM-26JUL-7", qty=1, price=0.01)
        assert result["ok"] is False

    def test_blocks_even_when_city_and_date_are_present(self):
        """The guard must fire before the `if city and target_date_str:`
        exposure-cap block, not rely on those args being absent -- today
        target_date_str is always None for rain tickers (no day component
        in the ticker), so this also locks in the guard's before-everything
        ordering against a future refactor that moves it below that block
        or against city/date resolution ever changing for these tickers."""
        import paper

        result = paper.check_position_limits(
            "KXRAINSEAM-26JUL-1",
            qty=1,
            price=0.10,
            city="Seattle",
            target_date_str="2026-07-01",
            side="yes",
        )
        assert result["ok"] is False

    def test_daily_ticker_unaffected(self, tmp_path):
        """Regression control: an ordinary ticker must reach the real
        exposure-cap logic (not the new rain guard) -- verified by mocking
        the dependencies the real logic needs and confirming a small order
        on an empty portfolio passes."""
        from unittest.mock import patch

        import paper

        with patch("paper.DATA_PATH", tmp_path / "p.json"):
            paper._save(
                {
                    "_version": paper._SCHEMA_VERSION,
                    "balance": paper.STARTING_BALANCE,
                    "peak_balance": paper.STARTING_BALANCE,
                    "trades": [],
                }
            )
            with patch("paper.get_open_trades", return_value=[]):
                with patch("paper.get_total_exposure", return_value=0.0):
                    result = paper.check_position_limits(
                        "KXHIGHNY-26JUL20-T70", qty=1, price=0.50
                    )
        assert result["ok"] is True
