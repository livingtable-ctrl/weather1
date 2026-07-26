"""
Tests for backlog.txt "RAIN / SNOW / HURRICANE MARKETS" -- SNOW Step 1
(discovery/schema/safety for KXDENSNOWM, the one snow series among this
bot's 21 tracked cities that has ever had a real market -- zero live-trading
behavior change, no probability model). Mirrors the narrower set of rain's
own original Step 1 tests (test_rain_markets.py's current suite is Step-2-
shaped; rain's Step 1 guard is gone from the live code, replaced by a real
model). Deliberately scoped to one city -- see KNOWN_UNTRACKED_SNOW_SERIES
in weather_markets.py for the other 32 real-but-excluded snow series and why
each is excluded (live-verified 2026-07-26: every one has zero markets ever
created, except KXASPSNOWM/Aspen, an untracked city).
"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import MagicMock


def _mock_client(live_tickers):
    client = MagicMock()
    client.get_series_list.return_value = [{"ticker": t} for t in live_tickers]
    return client


def _snow_market(
    ticker="KXDENSNOWM-26DEC-5.0",
    floor_strike=5.0,
    strike_type="greater",
    close_time="2027-01-01T18:58:59Z",
    yes_bid=0.30,
    yes_ask=0.35,
    volume_fp=500,
):
    return {
        "ticker": ticker,
        "title": "Snow in Denver in Dec 2026?",
        "yes_sub_title": f"Above {floor_strike} inches",
        "floor_strike": floor_strike,
        "strike_type": strike_type,
        "close_time": close_time,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "volume_fp": volume_fp,
    }


class TestSnowTickerDiscovery:
    def test_kxdensnowm_resolves_to_denver(self):
        import weather_markets as wm

        assert wm._parse_city_from_ticker("KXDENSNOWM-26DEC-5.0") == "Denver"

    def test_dict_lookup_is_actually_consulted_not_just_the_den_coincidence(
        self, monkeypatch
    ):
        """Opus-review finding: 'DEN' is also a substring fallback match for
        Denver (weather_markets.py's generic chain), so the test above
        passes even with _KXSNOW_MONTHLY_CITY deleted entirely -- it wasn't
        pinning the new code. Proves the dict path is real by pointing it at
        a deliberately WRONG city and confirming resolution follows it."""
        import weather_markets as wm

        monkeypatch.setitem(wm._KXSNOW_MONTHLY_CITY, "KXDENSNOWM", "NotARealCity")
        assert wm._parse_city_from_ticker("KXDENSNOWM-26DEC-5.0") == "NotARealCity"

    def test_kxdensnowm_in_known_weather_series(self):
        import weather_markets as wm

        assert "KXDENSNOWM" in wm.KNOWN_WEATHER_SERIES
        assert "KXSNOW" not in wm.KNOWN_WEATHER_SERIES  # dead placeholder removed

    def test_condition_reads_floor_strike_directly(self):
        """Must run before the generic SNOW_SERIES/is_snow_ticker branch, or
        this would misparse as a daily precip_snow condition instead of
        reading the real floor_strike field."""
        import weather_markets as wm

        cond = wm._parse_market_condition(_snow_market())
        assert cond == {"type": "snow_month_total", "threshold": 5.0}

    def test_unexpected_strike_type_refuses_to_guess(self):
        import weather_markets as wm

        cond = wm._parse_market_condition(_snow_market(strike_type="less_or_equal"))
        assert cond is None

    def test_other_snow_series_not_in_known_weather_series(self):
        """Regression control: the 32 real-but-excluded series must stay
        excluded, not accidentally get added alongside KXDENSNOWM."""
        import weather_markets as wm

        for excluded in ("KXNYCSNOWM", "KXCHISNOWM", "KXASPSNOWM", "KXMIASNOWM"):
            assert excluded not in wm.KNOWN_WEATHER_SERIES
            assert excluded in wm.KNOWN_UNTRACKED_SNOW_SERIES


class TestAnalyzeTradeMonthlySnowGating:
    """True Step 1 shape: unconditional return-None guard, zero model --
    unlike rain's current (Step 2) code."""

    def test_gates_out_unconditionally(self):
        import weather_markets as wm

        m = _snow_market()
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        counts = wm.get_gate_counts()
        assert counts.get("monthly_snow_not_yet_supported") == 1

    def test_bare_ticker_dict_still_gates_via_snow_guard_not_no_city(self):
        """Confirms the guard fires before the generic no_city gate, even
        with zero enrichment -- matching how hurricane's guard was ordered
        first in this same function."""
        import weather_markets as wm

        wm.reset_gate_counts()
        assert wm.analyze_trade({"ticker": "KXDENSNOWM-26DEC-5.0"}) is None
        counts = wm.get_gate_counts()
        assert counts.get("monthly_snow_not_yet_supported") == 1
        assert counts.get("no_city") is None

    def test_daily_high_ticker_unaffected(self):
        """Regression control: an ordinary daily HIGH ticker must still hit
        the normal no_forecast gate, not the new snow guard."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXHIGHNY-26JUL20-T70", "_city": "NYC"})
        counts = wm.get_gate_counts()
        assert counts.get("no_forecast") == 1
        assert counts.get("monthly_snow_not_yet_supported") is None

    def test_rain_ticker_unaffected(self):
        """Regression control: the new KXDENSNOWM-prefix guard must not
        collide with the existing monthly-rain ticker family."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXRAINDENM-26JUL-7"})
        assert wm.get_gate_counts().get("monthly_snow_not_yet_supported") is None


class TestCheckSeriesDriftSnow:
    def test_unknown_snow_ticker_warns_immediately(self, tmp_path, monkeypatch, caplog):
        import weather_markets as wm

        drift_path = tmp_path / "series_drift_check.json"
        monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

        live_with_extra = [*wm.KNOWN_WEATHER_SERIES, "KXNEWCITYSNOWM"]

        with caplog.at_level(logging.WARNING):
            client = _mock_client(live_with_extra)
            wm.check_series_drift(client)

        assert any(
            "KXNEWCITYSNOWM" in r.message and "not in KNOWN_WEATHER_SERIES" in r.message
            for r in caplog.records
        )

    def test_known_untracked_snow_series_suppressed(
        self, tmp_path, monkeypatch, caplog
    ):
        """All 32 KNOWN_UNTRACKED_SNOW_SERIES entries must be suppressed,
        not just the genuinely-unknown case above."""
        import weather_markets as wm

        drift_path = tmp_path / "series_drift_check.json"
        monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

        live_with_untracked = [
            *wm.KNOWN_WEATHER_SERIES,
            *wm.KNOWN_UNTRACKED_SNOW_SERIES,
        ]

        with caplog.at_level(logging.WARNING):
            client = _mock_client(live_with_untracked)
            wm.check_series_drift(client)

        assert not any(
            "not in KNOWN_WEATHER_SERIES" in r.message for r in caplog.records
        )

    def test_missing_kxdensnowm_flagged_after_3_days(self, tmp_path, monkeypatch):
        """Regression control mirroring the pre-existing KXHIGH/KXLOW
        missing-ticker test: KXDENSNOWM must now be watched the same way."""
        import json

        import weather_markets as wm

        drift_path = tmp_path / "series_drift_check.json"
        monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

        live_without_denver_snow = [
            t for t in wm.KNOWN_WEATHER_SERIES if t != "KXDENSNOWM"
        ]
        client = _mock_client(live_without_denver_snow)

        for day_offset in range(3):
            state = json.loads(drift_path.read_text()) if drift_path.exists() else {}
            state["date"] = f"2020-01-{1 + day_offset:02d}"  # force a new day each loop
            drift_path.write_text(json.dumps(state))
            wm.check_series_drift(client)

        state = json.loads(drift_path.read_text())
        assert state["missing_days"].get("KXDENSNOWM") == 3


class TestCheckPositionLimitsBlocksMonthlySnow:
    """paper.check_position_limits() is the one call path reachable without
    analyze_trade() first -- must refuse a monthly-snow ticker outright."""

    def test_blocks_regardless_of_qty_and_price(self):
        import paper

        result = paper.check_position_limits("KXDENSNOWM-26DEC-5.0", qty=1, price=0.10)
        assert result["ok"] is False
        assert "snow" in result["reason"].lower()

    def test_blocks_even_when_city_and_date_are_present(self):
        import paper

        result = paper.check_position_limits(
            "KXDENSNOWM-26DEC-5.0",
            qty=1,
            price=0.10,
            city="Denver",
            target_date_str="2026-12-01",
            side="yes",
        )
        assert result["ok"] is False

    def test_daily_ticker_unaffected(self, tmp_path):
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


class TestComputeMarketImpliedExcludesMonthlySnow:
    """compute_market_implied_distributions() groups by (city, target_date)
    independently of analyze_trade() -- same architectural gap rain's own
    exclusion closes, mirrored here for snow."""

    def _daily_market(self, floor_strike, ticker_suffix, bid, ask):
        return {
            "ticker": f"KXHIGHNY-26JUL20-T{ticker_suffix}",
            "title": f"Will the high temp in NYC be above {floor_strike}°?",
            "close_time": "2026-07-20T23:00:00Z",
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
        snow_extra = [
            _snow_market(ticker="KXDENSNOWM-26DEC-1.0", floor_strike=1.0),
            _snow_market(ticker="KXDENSNOWM-26DEC-7.0", floor_strike=7.0),
        ]

        fit_daily_only = wm.compute_market_implied_distributions(daily_only)
        fit_mixed = wm.compute_market_implied_distributions(daily_only + snow_extra)

        assert fit_daily_only[("NYC", "2026-07-20")] is not None
        assert fit_daily_only == fit_mixed, (
            "monthly-snow brackets changed the daily market-implied fit -- "
            "they were not excluded before event-grouping"
        )

    def test_snow_only_list_produces_no_distributions(self):
        import weather_markets as wm

        snow_only = [
            _snow_market(ticker="KXDENSNOWM-26DEC-1.0", floor_strike=1.0),
            _snow_market(ticker="KXDENSNOWM-26DEC-7.0", floor_strike=7.0),
        ]
        result = wm.compute_market_implied_distributions(snow_only)
        assert result == {}

    def test_exclusion_holds_even_if_a_date_were_parseable(self, monkeypatch):
        """Real regression guard for the explicit prefix exclusion -- proves
        it does real work rather than coincidentally agreeing with
        parse_city_date()'s current None-return behavior for this ticker
        family, mirroring rain's identical mutation-style test."""
        import weather_markets as wm

        real_parse_city_date = wm.parse_city_date

        def _fake_parse_city_date(market):
            if market.get("ticker", "").upper().startswith("KXDENSNOWM"):
                return ("Denver", date(2026, 12, 1))
            return real_parse_city_date(market)

        monkeypatch.setattr(wm, "parse_city_date", _fake_parse_city_date)

        daily_only = [self._daily_market(70.0, "70", 75, 80)]
        snow_market = _snow_market(ticker="KXDENSNOWM-26DEC-1.0", floor_strike=1.0)

        result = wm.compute_market_implied_distributions(daily_only + [snow_market])

        assert ("Denver", "2026-12-01") not in result, (
            "snow market reached event-grouping despite a now-parseable date -- "
            "the explicit prefix exclusion isn't doing real work"
        )


class TestGroupMarketsExcludesMonthlySnow:
    def test_snow_market_excluded_no_warning(self, caplog):
        import logging

        import consistency

        with caplog.at_level(logging.WARNING):
            groups = consistency._group_markets([_snow_market()])
        assert groups == {}
        assert not any("date" in r.message.lower() for r in caplog.records)
