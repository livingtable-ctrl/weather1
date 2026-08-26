"""Tests for batch-51 items 1/2/4: KXRAIN (daily)/KXRAINWKND onboarding
(TRACK-ONLY, go/no-go failed), KXHOLIDAYTMAX/TMIN onboarding (real
shadow-trade model, own dedicated gate), and the catalog/settlement-source
drift watcher extension. Mirrors tests/test_hurricane_markets.py's and
tests/test_series_drift.py's established conventions for ticker predicates,
condition parsing, gates, and once-per-cadence state-file checks.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _today():
    return datetime.now(UTC).date()


# ── City-suffix map / ticker predicates ─────────────────────────────────────


class TestSuffixCitySeriesPredicates:
    @pytest.mark.parametrize(
        "ticker,expected_city",
        [
            ("KXRAIN-26AUG24-SFO", "SanFrancisco"),
            ("KXRAIN-26AUG24-DC", "Washington"),
            ("KXRAIN-26AUG24-LV", "LasVegas"),
            ("KXRAIN-26AUG24-NOLA", "NewOrleans"),
            ("KXRAIN-26AUG24-SATX", "SanAntonio"),
            ("KXRAIN-26AUG24-PHIL", "Philadelphia"),
            ("KXRAIN-26AUG24-MIN", "Minneapolis"),
            ("KXRAIN-26AUG24-OKC", "OklahomaCity"),
            ("KXRAIN-26AUG24-LAX", "LA"),
            ("KXRAIN-26AUG24-NYC", "NYC"),
            ("KXRAINWKND-26AUG29-SFO", "SanFrancisco"),
            ("KXHOLIDAYTMAX-260704100-SFO", "SanFrancisco"),
            ("KXHOLIDAYTMIN-26070450-SFO", "SanFrancisco"),
        ],
    )
    def test_city_resolves_via_suffix(self, ticker, expected_city):
        import weather_markets as wm

        assert wm._parse_city_from_ticker(ticker) == expected_city

    def test_all_20_bot_cities_covered(self):
        """Suffix map must cover exactly the bot's 20 tracked cities --
        live-verified 2026-08-24 identical suffix set across all 4 series."""
        import weather_markets as wm

        assert len(wm._KXRAIN_DAILY_CITY_SUFFIX) == 20
        assert (
            set(wm._KXRAIN_DAILY_CITY_SUFFIX.values()) == wm.TEMPERATURE_MARKET_CITIES
        )

    def test_suffix_lookup_does_not_fire_for_unrelated_series(self):
        """A ticker whose series isn't KXRAIN/KXRAINWKND/KXHOLIDAYTMAX/TMIN
        must fall through to the prefix-keyed dicts unaffected, even if its
        trailing segment happens to match a city code coincidentally."""
        import weather_markets as wm

        assert wm._city_from_suffix_series("KXHIGHNY-26JUL20-T70") is None
        assert wm._city_from_suffix_series("KXRAINSFOM-26JUL-7") is None

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("KXRAIN-26AUG24-SFO", True),
            ("KXRAINWKND-26AUG29-SFO", False),
            ("KXRAINSFOM-26JUL-7", False),  # monthly ladder, different series
            ("KXHIGHNY-26JUL20-T70", False),
        ],
    )
    def test_is_rain_daily_ticker(self, ticker, expected):
        import weather_markets as wm

        assert wm.is_rain_daily_ticker(ticker) is expected

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("KXRAINWKND-26AUG29-SFO", True),
            ("KXRAIN-26AUG24-SFO", False),
        ],
    )
    def test_is_rain_weekend_ticker(self, ticker, expected):
        import weather_markets as wm

        assert wm.is_rain_weekend_ticker(ticker) is expected

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("KXHOLIDAYTMAX-260704100-SFO", True),
            ("KXHOLIDAYTMIN-26070450-SFO", True),
            ("KXHIGHSFO-26JUL04-T100", False),
            ("KXRAIN-26AUG24-SFO", False),
        ],
    )
    def test_is_holiday_temp_ticker(self, ticker, expected):
        import weather_markets as wm

        assert wm.is_holiday_temp_ticker(ticker) is expected

    def test_registry_membership(self):
        import weather_markets as wm

        for series in ("KXRAIN", "KXRAINWKND", "KXHOLIDAYTMAX", "KXHOLIDAYTMIN"):
            assert series in wm.KNOWN_WEATHER_SERIES
        assert "KXRAIN" not in wm.KNOWN_UNTRACKED_RAIN_SERIES

    def test_every_rain_suffix_series_member_is_caught_by_a_predicate(self):
        """Opus-review-caught consistency gap: _KXRAIN_DAILY_SUFFIX_SERIES
        (used for CITY parsing) and is_rain_daily_ticker()/is_rain_weekend_
        ticker() (used for the analyze_trade TRACK-ONLY gate) are two
        independent sources of truth for the same series set today --
        currently in sync (this test proves it), but if a future session
        ever adds a third series here (e.g. KXRAINHOLIDAY) for city-parsing
        purposes ONLY, without also updating the two predicates, the new
        series would silently get real city/date resolution AND flow
        straight into the live analyze_trade probability path with none of
        this batch's own track-only protection. This test converts that
        into a guard that fails loudly the moment the two drift apart,
        mirroring TestKxtempHourlyCityRegistryTie's own established
        pattern in test_weather_markets.py."""
        import weather_markets as wm

        for series in wm._KXRAIN_DAILY_SUFFIX_SERIES:
            example_ticker = f"{series}-26AUG24-SFO"
            caught = wm.is_rain_daily_ticker(
                example_ticker
            ) or wm.is_rain_weekend_ticker(example_ticker)
            assert caught, (
                f"{series} is in _KXRAIN_DAILY_SUFFIX_SERIES (gets city "
                f"parsing) but neither is_rain_daily_ticker nor "
                f"is_rain_weekend_ticker catches it -- would reach "
                f"analyze_trade's real probability path unprotected"
            )


# ── item 3 diagnosis: enrich_with_forecast's own separate date regex ────────


class TestEnrichWithForecastHurricaneNextEventDateGuard:
    """batch-51 item 3: enrich_with_forecast() had its own copy of the
    date-extraction regex, never given the same _HURRICANE_NEXT_EVENT_SERIES
    guard parse_city_date() already has (backlog.txt "[RESOLVED 2026-08-07]
    HURRICANE MARKETS -- TIME-TO-NEXT-EVENT MODEL SHIPPED SHADOW-ONLY").
    Live-confirmed during the diagnosis: enriched["_date"] came back as the
    wrong-but-non-None ticker's season-reference segment for every real
    KXNEXTHURDATE/KXNEXTCAT5HURDATE ticker."""

    def test_next_event_ticker_date_stays_none(self):
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXNEXTHURDATE-26DEC01-26SEP15", "title": "hurricane"},
            fetch_forecast=False,
        )
        assert enriched.get("_date") is None

    def test_cat5_next_event_ticker_date_stays_none(self):
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXNEXTCAT5HURDATE-26DEC01-26SEP01", "title": "hurricane"},
            fetch_forecast=False,
        )
        assert enriched.get("_date") is None

    def test_ordinary_daily_ticker_still_gets_its_real_date(self):
        """Positive control: the guard must be series-exact, not a
        regression on every other ticker's date parsing."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXHIGHNY-26AUG24-T70", "title": "above 70"},
            fetch_forecast=False,
        )
        assert enriched.get("_date") == date(2026, 8, 24)

    def test_hurricane_count_ticker_still_gets_its_real_date(self):
        """Positive control: hurricane-COUNT tickers (a different family,
        whose ticker date IS its real close date) must be unaffected --
        this guard is scoped to _HURRICANE_NEXT_EVENT_SERIES only."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {"ticker": "KXHURCTOT-26DEC01-T9", "title": "hurricane count"},
            fetch_forecast=False,
        )
        assert enriched.get("_date") == date(2026, 12, 1)


class TestEnrichWithForecastHolidayTempDateGuard:
    """Opus-review-caught BLOCKER: item 2's own go/no-go PASSED and its
    registry/parser layer was tested end-to-end at the unit level, but NO
    test anywhere exercised enrich_with_forecast() with a real holiday-temp
    ticker -- which is exactly the function that had its own separate,
    un-consolidated date regex missing the equivalent of parse_city_date's
    holiday branch. Without this fix, `_date` stayed None for every real
    KXHOLIDAYTMAX/TMIN market, `enrich_with_forecast`'s own `if city and
    target_date` guard never fired so a forecast was never fetched, and
    analyze_trade() gated every one of these markets out on "no_forecast"
    -- item 2 shipped completely inert in production despite every
    registry/parser unit test passing. This class (and
    TestAnalyzeTradeHolidayTempEndToEnd below) are what should have caught
    it; they didn't exist before the review."""

    def test_holiday_tmax_date_and_city_populate(self):
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXHOLIDAYTMAX-260704100-SFO",
                "title": "holiday max temp",
                "yes_sub_title": "San Francisco",
            },
            fetch_forecast=False,
        )
        assert enriched.get("_city") == "SanFrancisco"
        assert enriched.get("_date") == date(2026, 7, 4)

    def test_holiday_tmin_date_and_city_populate(self):
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXHOLIDAYTMIN-26070450-SFO",
                "title": "holiday min temp",
                "yes_sub_title": "San Francisco",
            },
            fetch_forecast=False,
        )
        assert enriched.get("_city") == "SanFrancisco"
        assert enriched.get("_date") == date(2026, 7, 4)

    def test_without_the_fix_forecast_fetch_guard_would_never_fire(self):
        """Characterizes the exact failure mode the fix closes: with the
        holiday branch disabled, _date stays None, so
        enrich_with_forecast's own `if city and target_date and
        fetch_forecast` guard can never pass for this family."""
        import weather_markets as wm

        real_series_set = wm._KXHOLIDAY_TEMP_SUFFIX_SERIES
        try:
            wm._KXHOLIDAY_TEMP_SUFFIX_SERIES = frozenset()
            enriched = wm.enrich_with_forecast(
                {"ticker": "KXHOLIDAYTMAX-260704100-SFO", "title": "x"},
                fetch_forecast=False,
            )
        finally:
            wm._KXHOLIDAY_TEMP_SUFFIX_SERIES = real_series_set
        assert enriched.get("_date") is None


# ── analyze_trade: holiday-temp reaches the real daily-temp model ───────────


class TestAnalyzeTradeHolidayTempEndToEnd:
    """The end-to-end test that should have existed from the start: builds
    the enriched dict via the REAL enrich_with_forecast() (not a hand-
    rolled {"_date": ..., "_city": ...} dict, which every other test in
    this file uses and which would NOT have caught BLOCKER 1 -- confirmed
    live during the fix that a hand-built enriched dict masks exactly this
    class of bug), then confirms analyze_trade() reaches its real "above"/
    "below" temperature analysis body and produces a full result, not a
    gate rejection."""

    def _near_future_ticker_and_close(self, series, threshold_segment):
        """Dynamically computed (today + 2 days) rather than a hardcoded
        date -- a hardcoded date would silently start failing on
        analyze_trade's MAX_DAYS_OUT gate once real wall-clock time moves
        past it, unrelated to whether the code under test still works."""
        target = _today() + timedelta(days=2)
        date_segment = f"{target.year - 2000:02d}{target.month:02d}{target.day:02d}"
        ticker = f"{series}-{date_segment}{threshold_segment}-SFO"
        close_time = (target + timedelta(days=1)).isoformat() + "T03:59:59Z"
        return ticker, target, close_time

    @staticmethod
    def _pin_external_fetches(monkeypatch, wm, *, temps):
        """Pin every source analyze_trade would otherwise fetch live.

        These two tests are about ROUTING -- that a real enriched dict from
        the real producer reaches the daily temperature model rather than a
        gate -- so the model's inputs may be fixed. Unpinned they reached
        aviationweather.gov (via _metar_lock_in), Open-Meteo and
        mesonet.agron.iastate.edu, which made a routing assertion depend on
        live weather. `temps` is chosen per test so the resulting BLEND (not the
        raw member fraction -- the Gaussian widens it) sits near that test's
        own market price, keeping the >0.25 model_mkt_gap gate well out of the
        way. Each caller records its own measured gap.
        """
        monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (False, 0.0, {}))
        monkeypatch.setattr(wm, "get_ensemble_temps", lambda *a, **kw: temps)
        monkeypatch.setattr(wm, "get_ensemble_members", lambda *a, **kw: None)
        monkeypatch.setattr(
            wm, "_get_consensus_probs", lambda *a, **kw: (None, None, None, None, None)
        )
        monkeypatch.setattr(wm, "fetch_temperature_nbm", lambda *a, **kw: None)
        monkeypatch.setattr(wm, "fetch_temperature_ecmwf", lambda *a, **kw: None)
        monkeypatch.setattr("nws.nws_prob", lambda *a, **kw: None)
        # Pinned explicitly, not left to conftest: climatological_prob returns
        # None today only because isolate_climatology_data_dir blocks
        # climatology's session, which drops climatology from the blend
        # entirely. Relying on that made the margin below depend on an
        # unrelated fixture -- with a live SF winter climatology the TMIN
        # blend moved far enough to trip the model_mkt_gap gate
        # (opus-review-caught, reproduced).
        monkeypatch.setattr("climatology.climatological_prob", lambda *a, **kw: None)
        monkeypatch.setattr(
            "climate_indices.temperature_adjustment", lambda *a, **kw: 0.0
        )
        monkeypatch.setattr("nws.get_live_observation", lambda *a, **kw: None)
        monkeypatch.setattr("mos.fetch_nbm_quantiles", lambda *a, **kw: None)
        # A second, independent METAR fetch: the dew-point coastal correction
        # (weather_markets.py:15776) fires for _DEW_POINT_SENSITIVE_CITIES,
        # which includes SanFrancisco, and is not reached through
        # _metar_lock_in.
        monkeypatch.setattr("metar.fetch_metar", lambda *a, **kw: None)

    def test_holiday_tmax_reaches_the_real_daily_temp_model(self, monkeypatch):
        import weather_markets as wm

        ticker, target_date, close_time = self._near_future_ticker_and_close(
            "KXHOLIDAYTMAX", "075"
        )
        market = {
            "ticker": ticker,
            "title": "Where will the max temp be above 75?",
            "yes_sub_title": "San Francisco",
            "floor_strike": 75,
            "cap_strike": None,
            "strike_type": "greater",
            "yes_bid_dollars": "0.30",
            "yes_ask_dollars": "0.32",
            "no_bid_dollars": "0.68",
            "no_ask_dollars": "0.70",
            "close_time": close_time,
            "volume": 5000,
            "volume_fp": 5000,
            "open_interest_fp": 5000,
            "liquidity_dollars": "500.00",
        }
        enriched = wm.enrich_with_forecast(market, fetch_forecast=False)
        assert enriched.get("_city") == "SanFrancisco"
        assert enriched.get("_date") == target_date
        # Forecast injected directly (avoid a live network dependency in
        # this test) -- the point under test is that analyze_trade reaches
        # its real "above" analysis body at all, given a real enriched
        # dict from the real producer function, not that the forecast
        # fetch itself works (covered elsewhere).
        enriched["_forecast"] = {"high_f": 74.0, "low_f": 60.0, "precip_in": 0.0}

        # 6 of 19 members above the 75 threshold. Measured blend: 0.348
        # against the 0.31 market mid -- a 0.038 gap.
        self._pin_external_fetches(
            monkeypatch, wm, temps=[73.0] * 7 + [74.5] * 6 + [76.0] * 6
        )
        wm.reset_gate_counts()
        result = wm.analyze_trade(enriched)

        assert result is not None, (
            f"analyze_trade returned None; gate counts: {wm.get_gate_counts()}"
        )
        assert result["condition"]["type"] == "above"
        assert result["condition"]["threshold"] == 75.0
        assert "forecast_prob" in result
        assert "edge" in result
        # batch-76 item 2, the no-op control for its TMIN sibling below: the
        # `or "max"` tail was RIGHT for this series, so teaching
        # _var_from_ticker_prefix the family must not disturb it. Pinned so
        # the two are asserted the same way and can't drift apart.
        assert result["condition"]["var"] == "max"

    def test_holiday_tmin_reaches_the_real_daily_temp_model(self, monkeypatch):
        import weather_markets as wm

        ticker, target_date, close_time = self._near_future_ticker_and_close(
            "KXHOLIDAYTMIN", "50"
        )
        market = {
            "ticker": ticker,
            "title": "Where will the min temp be below 50?",
            "yes_sub_title": "San Francisco",
            "floor_strike": None,
            "cap_strike": 50,
            "strike_type": "less",
            "yes_bid_dollars": "0.20",
            "yes_ask_dollars": "0.22",
            "no_bid_dollars": "0.78",
            "no_ask_dollars": "0.80",
            "close_time": close_time,
            "volume": 5000,
            "volume_fp": 5000,
            "open_interest_fp": 5000,
            "liquidity_dollars": "500.00",
        }
        enriched = wm.enrich_with_forecast(market, fetch_forecast=False)
        assert enriched.get("_date") == target_date
        enriched["_forecast"] = {"high_f": 74.0, "low_f": 60.0, "precip_in": 0.0}

        # 3 of 19 members below the 50 threshold. Measured blend: 0.163
        # against this fixture's 0.21 market mid -- a 0.047 gap, 0.20 clear of
        # the model_mkt_gap gate. The earlier pin sat at a 0.197 gap, i.e.
        # 0.053 from tripping it, which is not margin worth relying on.
        self._pin_external_fetches(
            monkeypatch, wm, temps=[46.0] * 3 + [54.0] * 9 + [58.0] * 7
        )
        wm.reset_gate_counts()
        result = wm.analyze_trade(enriched)

        assert result is not None, (
            f"analyze_trade returned None; gate counts: {wm.get_gate_counts()}"
        )
        assert result["condition"]["type"] == "below"
        assert result["condition"]["threshold"] == 50.0
        # batch-76 item 2. THE field the whole fix is written around, and it
        # was unpinned here: condition["var"] is threaded onto the paper
        # trade, becomes ensemble_member_scores.var, and is what
        # get_dynamic_station_bias reads for the max cell. While
        # _var_from_ticker_prefix returned None for this family, the `or
        # "max"` tail in _daily_var_from_series labelled this daily MINIMUM
        # market "max" end to end. Mutation target: reverting that helper
        # makes this line fail while every other assertion here still
        # passes -- which is exactly how it went unnoticed.
        assert result["condition"]["var"] == "min"


# ── parse_city_date ──────────────────────────────────────────────────────────


class TestParseCityDateBatch51:
    def test_rain_daily_date_and_city(self):
        import weather_markets as wm

        city, target_date = wm.parse_city_date({"ticker": "KXRAIN-26AUG24-SFO"})
        assert city == "SanFrancisco"
        assert target_date == date(2026, 8, 24)

    def test_rain_weekend_date_is_the_window_start(self):
        import weather_markets as wm

        city, target_date = wm.parse_city_date({"ticker": "KXRAINWKND-26AUG29-SFO"})
        assert city == "SanFrancisco"
        assert target_date == date(2026, 8, 29)

    def test_holiday_tmax_date_from_packed_segment(self):
        import weather_markets as wm

        city, target_date = wm.parse_city_date(
            {"ticker": "KXHOLIDAYTMAX-260704100-SFO"}
        )
        assert city == "SanFrancisco"
        assert target_date == date(2026, 7, 4)

    def test_holiday_tmin_date_from_packed_segment_two_digit_threshold(self):
        import weather_markets as wm

        city, target_date = wm.parse_city_date({"ticker": "KXHOLIDAYTMIN-26070450-SFO"})
        assert city == "SanFrancisco"
        assert target_date == date(2026, 7, 4)

    def test_holiday_temp_never_matches_the_month_abbreviation_regex(self):
        """Confirms the bug this needed its own branch for, against the
        REAL production function (not a standalone regex re-derivation) --
        monkeypatch the holiday branch off and confirm parse_city_date
        falls through to the generic regex path and fails to find a date,
        proving the explicit branch is load-bearing, not redundant."""
        import weather_markets as wm

        with_branch = wm.parse_city_date({"ticker": "KXHOLIDAYTMAX-260704100-SFO"})
        assert with_branch == ("SanFrancisco", date(2026, 7, 4))

        real_series_set = wm._KXHOLIDAY_TEMP_SUFFIX_SERIES
        try:
            wm._KXHOLIDAY_TEMP_SUFFIX_SERIES = frozenset()
            without_branch = wm.parse_city_date(
                {"ticker": "KXHOLIDAYTMAX-260704100-SFO"}
            )
        finally:
            wm._KXHOLIDAY_TEMP_SUFFIX_SERIES = real_series_set
        assert without_branch[1] is None, (
            "without the explicit branch, the generic MON-abbreviation "
            "regex must fail to find a date in this ticker's packed "
            "numeric segment -- confirms the branch is load-bearing"
        )

    def test_holiday_temp_invalid_date_returns_none_not_raise(self):
        import weather_markets as wm

        city, target_date = wm.parse_city_date(
            {"ticker": "KXHOLIDAYTMAX-269999100-SFO"}
        )
        assert city == "SanFrancisco"
        assert target_date is None


# ── _parse_market_condition ──────────────────────────────────────────────────


class TestParseMarketConditionRainDaily:
    def test_daily_rain_is_precip_any_explicit(self):
        import weather_markets as wm

        cond = wm._parse_market_condition(
            {"ticker": "KXRAIN-26AUG24-SFO", "title": "Will it rain today?"}
        )
        assert cond == {"type": "precip_any"}

    def test_weekend_rain_is_precip_any_explicit(self):
        import weather_markets as wm

        cond = wm._parse_market_condition(
            {"ticker": "KXRAINWKND-26AUG29-SFO", "title": "Rain this weekend?"}
        )
        assert cond == {"type": "precip_any"}

    def test_does_not_shadow_monthly_rain_ladder(self):
        """Positive control: the explicit daily-rain branch must not
        intercept KXRAIN*M monthly-ladder tickers (checked afterward in
        _parse_market_condition, but confirm no accidental substring
        collision either way)."""
        import weather_markets as wm

        cond = wm._parse_market_condition(
            {
                "ticker": "KXRAINSFOM-26JUL-7",
                "floor_strike": 7.0,
                "strike_type": "greater",
            }
        )
        assert cond == {"type": "precip_month_total", "threshold": 7.0}


class TestParseMarketConditionHolidayTemp:
    def _tmax(self, **overrides):
        base = {
            "ticker": "KXHOLIDAYTMAX-260704100-SFO",
            "floor_strike": 100,
            "cap_strike": None,
            "strike_type": "greater",
        }
        base.update(overrides)
        return base

    def _tmin(self, **overrides):
        base = {
            "ticker": "KXHOLIDAYTMIN-26070450-SFO",
            "floor_strike": None,
            "cap_strike": 50,
            "strike_type": "less",
        }
        base.update(overrides)
        return base

    def test_tmax_parses_as_above(self):
        import weather_markets as wm

        cond = wm._parse_market_condition(self._tmax())
        assert cond == {"type": "above", "threshold": 100.0, "prob_threshold": 100.5}

    def test_tmin_parses_as_below(self):
        import weather_markets as wm

        cond = wm._parse_market_condition(self._tmin())
        assert cond == {"type": "below", "threshold": 50.0, "prob_threshold": 49.5}

    def test_generic_text_keyword_branch_would_have_failed(self):
        """Confirms the real reason this needed its own branch, against the
        REAL production function: with the holiday branch disabled, a
        realistic holiday-temp market (yes_sub_title is just the city
        name, no "above"/"below" keyword) must fail closed via the generic
        T-type keyword detector further down, not silently succeed some
        other way."""
        import weather_markets as wm

        market = self._tmax()
        market["title"] = ""
        market["yes_sub_title"] = "San Francisco"
        real_series_set = wm._KXHOLIDAY_TEMP_SUFFIX_SERIES
        try:
            wm._KXHOLIDAY_TEMP_SUFFIX_SERIES = frozenset()
            cond = wm._parse_market_condition(market)
        finally:
            wm._KXHOLIDAY_TEMP_SUFFIX_SERIES = real_series_set
        assert cond is None

    def test_unexpected_strike_type_fails_closed(self, caplog):
        import weather_markets as wm

        cond = wm._parse_market_condition(self._tmax(strike_type="between"))
        assert cond is None
        assert "refusing to guess direction" in caplog.text

    def test_missing_strike_field_fails_closed(self, caplog):
        import weather_markets as wm

        cond = wm._parse_market_condition(self._tmax(floor_strike=None))
        assert cond is None
        assert "missing the floor_strike field" in caplog.text


# ── analyze_trade: rain track-only gate ──────────────────────────────────────


class TestAnalyzeTradeRainDailyTrackOnly:
    def _enriched(self, ticker, **overrides):
        base = {
            "ticker": ticker,
            "_forecast": {"forecast_temp": 70.0, "precip_in": 0.0},
            "_date": None,
            "_city": "SanFrancisco",
            "_hour": None,
        }
        base.update(overrides)
        return base

    def test_daily_rain_returns_none_without_computing_a_probability(self):
        import weather_markets as wm

        result = wm.analyze_trade(self._enriched("KXRAIN-26AUG24-SFO"))
        assert result is None

    def test_weekend_rain_returns_none(self):
        import weather_markets as wm

        result = wm.analyze_trade(self._enriched("KXRAINWKND-26AUG29-SFO"))
        assert result is None

    def test_gate_fires_with_its_own_distinct_counter_reason(self):
        """Positive control for the gate itself: confirms analyze_trade's
        gate counter increments under the specific
        "rain_daily_track_only_no_model" reason (not silently falling
        through some other unrelated guard, e.g. the hurricane blanket
        guard's "hurricane_not_supported" counter)."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade(self._enriched("KXRAIN-26AUG24-SFO"))
        counts = wm.get_gate_counts()
        assert counts.get("rain_daily_track_only_no_model") == 1
        assert "hurricane_not_supported" not in counts

    def test_positive_control_monthly_rain_not_caught_by_the_new_gate(self):
        """Critical positive control, against the REAL analyze_trade
        dispatch: the new track-only gate must be SERIES-EXACT (KXRAIN/
        KXRAINWKND only), not a substring match on "KXRAIN" -- a substring
        match would also silently swallow the UNRELATED, already-shipped
        KXRAIN*M monthly-ladder family (which DOES have a real model)
        since "KXRAIN" is a substring of every KXRAIN*M ticker too."""
        import weather_markets as wm

        wm.reset_gate_counts()
        # No real forecast/city/date data -- this will gate out for some
        # OTHER reason (no_forecast, no_date, etc.), which is fine; the
        # only thing under test is that it's NOT the new rain-track-only
        # gate specifically.
        wm.analyze_trade(self._enriched("KXRAINSFOM-26JUL-7"))
        counts = wm.get_gate_counts()
        assert "rain_daily_track_only_no_model" not in counts


# ── holiday-temp gate + counter ──────────────────────────────────────────────


class TestHolidayTempGatesActive:
    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("HOLIDAY_TEMP_TRADING_ENABLED", raising=False)
        assert wm._holiday_temp_gates_active() is False

    def test_false_when_env_var_set_but_under_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HOLIDAY_TEMP_TRADING_ENABLED", "1")
        monkeypatch.setattr(
            "tracker.count_settled_holiday_temp_predictions", lambda: 19
        )
        assert wm._holiday_temp_gates_active() is False

    def test_true_when_env_var_set_and_floor_cleared(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HOLIDAY_TEMP_TRADING_ENABLED", "1")
        monkeypatch.setattr(
            "tracker.count_settled_holiday_temp_predictions", lambda: 20
        )
        assert wm._holiday_temp_gates_active() is True

    def test_kept_separate_from_daily_temp_state(self, monkeypatch):
        """The dedicated-shadow-lane decision: this gate must NOT read the
        main daily-temp graduation counter, only its own."""
        import weather_markets as wm

        monkeypatch.setenv("HOLIDAY_TEMP_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_holiday_temp_predictions", lambda: 0)
        assert wm._holiday_temp_gates_active() is False


class TestCountSettledHolidayTempPredictions:
    """Opus-review-caught rewrite: the original version of this counter
    (and these tests) assumed KXHOLIDAYTMAX was single-threshold-per-city
    like KXHOLIDAYTMIN -- live-re-verified false (KXHOLIDAYTMAX has 3
    sibling threshold brackets per city per holiday). These tests use the
    REAL 3-bracket shape (SFO's actual Jul 4 2026 tickers: -100/-75/-85)
    to prove the counter dedupes by (city, date) EVENT, not by raw ticker."""

    def _make_env(self, tmp_path, monkeypatch):
        import tracker

        db_path = tmp_path / "test_predictions.db"
        monkeypatch.setattr(tracker, "DB_PATH", db_path)
        monkeypatch.setattr(tracker, "_db_initialized", False)
        return tracker

    def _log_settled(self, tracker, ticker, city, threshold, direction):
        analysis = {
            "condition": {"type": direction, "threshold": threshold},
            "forecast_prob": 0.6,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
            "n_members": 82,
            "local_hour": None,
        }
        tracker.log_prediction(
            ticker,
            city,
            date(2026, 7, 4),
            analysis,
            edge_calc_version="v1",
            signal_source="src",
            blend_sources={"icon_seamless": 1.0},
        )
        tracker.log_outcome(ticker, True)

    def test_counts_only_holiday_temp_tickers(self, tmp_path, monkeypatch):
        tracker = self._make_env(tmp_path, monkeypatch)
        before = tracker.count_settled_holiday_temp_predictions()
        self._log_settled(
            tracker, "KXHOLIDAYTMAX-260704100-SFO", "SanFrancisco", 100.0, "above"
        )
        self._log_settled(
            tracker, "KXHOLIDAYTMIN-26070450-SFO", "SanFrancisco", 50.0, "below"
        )
        # ordinary daily temp row -- must NOT count toward this gate
        self._log_settled(
            tracker, "KXHIGHSFO-26JUL04-T75", "SanFrancisco", 75.0, "above"
        )
        after = tracker.count_settled_holiday_temp_predictions()
        assert after == before + 2

    def test_sibling_threshold_brackets_collapse_to_one_event(
        self, tmp_path, monkeypatch
    ):
        """The real fix under test: 3 real KXHOLIDAYTMAX sibling tickers
        for the SAME city/holiday (live-verified SFO shape) settling from
        one real max-temp observation must count as 1, not 3."""
        tracker = self._make_env(tmp_path, monkeypatch)
        before = tracker.count_settled_holiday_temp_predictions()
        for ticker, threshold in (
            ("KXHOLIDAYTMAX-260704100-SFO", 100.0),
            ("KXHOLIDAYTMAX-26070475-SFO", 75.0),
            ("KXHOLIDAYTMAX-26070485-SFO", 85.0),
        ):
            self._log_settled(tracker, ticker, "SanFrancisco", threshold, "above")
        after = tracker.count_settled_holiday_temp_predictions()
        assert after == before + 1, (
            "3 sibling threshold brackets for the same (city, date) event "
            "must count as 1 real observation, not 3"
        )

    def test_distinguishes_cities_dates_and_series(self, tmp_path, monkeypatch):
        """Different cities, different dates, and different series (TMAX
        vs TMIN, genuinely separate questions even for the same city/date)
        must each count as their OWN distinct event."""
        tracker = self._make_env(tmp_path, monkeypatch)
        before = tracker.count_settled_holiday_temp_predictions()
        self._log_settled(
            tracker, "KXHOLIDAYTMAX-260704100-SFO", "SanFrancisco", 100.0, "above"
        )
        self._log_settled(tracker, "KXHOLIDAYTMAX-260704100-NYC", "NYC", 100.0, "above")
        self._log_settled(
            tracker, "KXHOLIDAYTMIN-26070450-SFO", "SanFrancisco", 50.0, "below"
        )
        after = tracker.count_settled_holiday_temp_predictions()
        assert after == before + 3, (
            "different city, and different series for the same city/date, "
            "must each count as distinct events"
        )

    def test_ignores_lookalike_series(self, tmp_path, monkeypatch):
        """A hypothetical lookalike series ("KXHOLIDAYTMAXX") must not
        false-positive past the coarse SQL LIKE pre-filter -- mirrors
        count_settled_hurricane_next_event_predictions's own test."""
        tracker = self._make_env(tmp_path, monkeypatch)
        before = tracker.count_settled_holiday_temp_predictions()
        self._log_settled(
            tracker, "KXHOLIDAYTMAXX-260704100-SFO", "SanFrancisco", 100.0, "above"
        )
        after = tracker.count_settled_holiday_temp_predictions()
        assert after == before

    def test_excludes_disputed(self, tmp_path, monkeypatch):
        tracker = self._make_env(tmp_path, monkeypatch)
        before = tracker.count_settled_holiday_temp_predictions()
        self._log_settled(
            tracker, "KXHOLIDAYTMAX-260704100-SFO", "SanFrancisco", 100.0, "above"
        )
        tracker.mark_outcome_disputed("KXHOLIDAYTMAX-260704100-SFO")
        after = tracker.count_settled_holiday_temp_predictions()
        assert after == before

    def test_unparseable_ticker_warns_and_is_excluded(
        self, tmp_path, monkeypatch, caplog
    ):
        """An unparseable settled holiday-temp ticker must at least log a
        warning, not silently vanish from the count -- same convention as
        count_settled_snow_predictions()."""
        import logging

        tracker = self._make_env(tmp_path, monkeypatch)
        self._log_settled(
            tracker, "KXHOLIDAYTMAX-badformat-SFO", "SanFrancisco", 100.0, "above"
        )
        with caplog.at_level(logging.WARNING):
            after = tracker.count_settled_holiday_temp_predictions()
        assert after == 0
        assert "could not parse city/date" in caplog.text


# ── consistency._group_markets exclusions ────────────────────────────────────


class TestGroupMarketsExclusionsBatch51:
    """Opus-review-corrected: the earlier versions of these 4 tests were
    vacuous -- they passed even with the exclusions they claimed to test
    removed, because _group_markets' own PRE-EXISTING generic-branch
    guards (`if not series or not date_str: continue` for a date-parse
    failure, `if not parsed: continue` when `_parse_threshold()` can't
    match a ticker's suffix) already independently drop every batch-51
    ticker shape before a group is ever formed. Rewritten to test the
    REAL, currently-observable difference the exclusions make (verified by
    direct mutation before writing these) rather than an unreachable
    "would collapse into one group" scenario."""

    def test_rain_daily_parse_threshold_already_fails_independently(self):
        """Characterizes WHY the rain exclusion is currently a redundant
        safety net, not the sole preventer: _parse_threshold() requires a
        "-T<n>"/"-B<n>" suffix, which a "-SFO"-suffixed rain ticker never
        has, so it already returns None on its own."""
        import consistency

        assert consistency._parse_threshold({"ticker": "KXRAIN-26AUG24-SFO"}) is None
        assert (
            consistency._parse_threshold({"ticker": "KXRAINWKND-26AUG29-SFO"}) is None
        )

    def test_rain_daily_and_weekend_excluded(self):
        """Confirms current behavior (empty groups) -- kept even though
        mutating the exclusion away currently produces the identical
        result via the independent guard above, matching this codebase's
        "explicit rather than relying on incidental behavior elsewhere"
        convention (same reasoning the production comment now documents)."""
        import consistency

        markets = [
            {
                "ticker": "KXRAIN-26AUG24-SFO",
                "yes_bid_dollars": "0.10",
                "yes_ask_dollars": "0.12",
            },
            {"ticker": "KXRAINWKND-26AUG29-SFO"},
        ]
        groups = consistency._group_markets(markets)
        assert groups == {}

    def test_holiday_temp_excluded_suppresses_the_date_parse_warning(self, caplog):
        """The REAL, mutation-sensitive effect of this exclusion: without
        it, the generic branch's date_str regex can't match this ticker
        shape at all and logs a WARNING per market -- the exclusion
        suppresses that (removing it, real behavior verified: the WARNING
        fires and groups still end up empty via the pre-existing
        `not date_str` guard, not via this exclusion)."""
        import logging

        import consistency

        markets = [
            {
                "ticker": "KXHOLIDAYTMAX-260704100-SFO",
                "floor_strike": 100,
                "strike_type": "greater",
            },
        ]
        with caplog.at_level(logging.WARNING):
            groups = consistency._group_markets(markets)
        assert groups == {}
        assert "could not extract date from ticker" not in caplog.text

    def test_holiday_temp_date_str_regex_genuinely_cannot_match(self):
        """Characterizes the underlying fact the exclusion's corrected
        comment relies on."""
        import re

        assert re.search(r"(\d{2}[A-Z]{3}\d{2})", "KXHOLIDAYTMAX-260704100-SFO") is None

    def test_ordinary_daily_temp_unaffected(self):
        """Positive control: the exclusions above must be series-specific,
        not a regression on the generic (series, date_str) grouping regular
        KXHIGH*/KXLOW* markets rely on."""
        import consistency

        markets = [
            {
                "ticker": "KXHIGHSFO-26AUG24-T75",
                "title": "above 75",
                "yes_bid_dollars": "0.40",
                "yes_ask_dollars": "0.42",
            },
            {
                "ticker": "KXHIGHSFO-26AUG24-T70",
                "title": "above 70",
                "yes_bid_dollars": "0.60",
                "yes_ask_dollars": "0.62",
            },
        ]
        groups = consistency._group_markets(markets)
        assert len(groups) == 1
        assert len(next(iter(groups.values()))) == 2


class TestComputeMarketImpliedDistributionsExclusionsBatch51:
    def test_holiday_temp_excluded_from_temp_event_pooling(self):
        """Real bug this prevents: without the exclusion, a holiday market
        would pool into the SAME (city, date) group as that city's ordinary
        daily ladder for the identical calendar date."""
        import weather_markets as wm

        markets = [
            {
                "ticker": "KXHOLIDAYTMAX-260704100-SFO",
                "floor_strike": 100,
                "strike_type": "greater",
            },
        ]
        results = wm.compute_market_implied_distributions(markets)
        assert results == {}

    def test_rain_daily_excluded(self):
        import weather_markets as wm

        markets = [{"ticker": "KXRAIN-26AUG24-SFO"}]
        results = wm.compute_market_implied_distributions(markets)
        assert results == {}


# ── check_series_drift: holiday-temp coverage ────────────────────────────────


def _mock_client(live_tickers=None, open_markets=None, events=None):
    client = MagicMock()
    client.get_series_list.return_value = [{"ticker": t} for t in (live_tickers or [])]
    client.get_markets.return_value = open_markets or []
    client.get_events.return_value = events or []
    return client


class TestCheckSeriesDriftHolidayTempCoverage:
    def test_holiday_temp_series_do_not_warn_as_unknown_when_live(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        import weather_markets as wm

        drift_path = tmp_path / "series_drift_check.json"
        monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

        client = _mock_client(live_tickers=list(wm.KNOWN_WEATHER_SERIES))
        with caplog.at_level(logging.WARNING):
            wm.check_series_drift(client)
        assert "KXHOLIDAYTMAX" not in caplog.text

    def test_live_holiday_temp_series_clears_its_own_missing_days_counter(
        self, tmp_path, monkeypatch
    ):
        """Opus-review-caught: the prior version of this class only tested
        the "no warning fires" direction, which passes vacuously even if
        _KXHOLIDAY_TEMP_SUFFIX_SERIES were never unioned into live_weather
        at all (both a missing union AND a correct one produce zero
        warnings when missing_days starts empty). This tests the other
        half: a series with an EXISTING missing-days count must have that
        count CLEARED once it's live again -- only reachable if the
        live_weather union at weather_markets.py:5182 actually includes
        _KXHOLIDAY_TEMP_SUFFIX_SERIES, not just the per-ticker loop filter."""
        import weather_markets as wm

        drift_path = tmp_path / "series_drift_check.json"
        monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

        yesterday = (_today() - timedelta(days=1)).isoformat()
        drift_path.write_text(
            json.dumps({"date": yesterday, "missing_days": {"KXHOLIDAYTMAX": 2}})
        )
        client = _mock_client(live_tickers=list(wm.KNOWN_WEATHER_SERIES))
        wm.check_series_drift(client)

        state = json.loads(drift_path.read_text())
        assert "KXHOLIDAYTMAX" not in state["missing_days"], (
            "a live KXHOLIDAYTMAX must clear its missing-days counter -- "
            "only possible if it's actually present in live_weather"
        )

    def test_holiday_temp_missing_days_tracked_not_silently_ignored(
        self, tmp_path, monkeypatch, caplog
    ):
        """Before this batch's fix, KXHOLIDAYTMAX/TMIN matched none of the
        missing-days loop's filter conditions and would be silently
        skipped forever, regardless of registration."""
        import logging

        import weather_markets as wm

        drift_path = tmp_path / "series_drift_check.json"
        monkeypatch.setattr(wm, "SERIES_DRIFT_PATH", drift_path)

        live_minus_holiday = [
            t for t in wm.KNOWN_WEATHER_SERIES if t not in ("KXHOLIDAYTMAX",)
        ]
        yesterday = (_today() - timedelta(days=1)).isoformat()
        drift_path.write_text(
            json.dumps({"date": yesterday, "missing_days": {"KXHOLIDAYTMAX": 2}})
        )
        client = _mock_client(live_tickers=live_minus_holiday)
        with caplog.at_level(logging.WARNING):
            wm.check_series_drift(client)
        assert (
            "KXHOLIDAYTMAX missing from Kalshi's live series list for 3" in caplog.text
        )


# ── check_catalog_and_settlement_drift (item 4) ──────────────────────────────


class TestCheckCatalogAndSettlementDrift:
    def test_first_run_creates_state_file_and_records_sources(
        self, tmp_path, monkeypatch
    ):
        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)

        client = _mock_client(
            events=[{"settlement_sources": [{"name": "The Weather Company"}]}]
        )
        wm.check_catalog_and_settlement_drift(client)

        assert drift_path.exists()
        state = json.loads(drift_path.read_text())
        assert state["last_run_date"] == _today().isoformat()
        assert state["settlement_sources"]["KXRAIN"] == ["The Weather Company"]

    def test_gated_to_run_once_per_week(self, tmp_path, monkeypatch):
        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)
        drift_path.write_text(
            json.dumps(
                {"last_run_date": _today().isoformat(), "settlement_sources": {}}
            )
        )

        client = _mock_client()
        wm.check_catalog_and_settlement_drift(client)
        client.get_markets.assert_not_called()
        client.get_events.assert_not_called()

    def test_runs_again_after_seven_days(self, tmp_path, monkeypatch):
        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)
        eight_days_ago = (_today() - timedelta(days=8)).isoformat()
        drift_path.write_text(
            json.dumps({"last_run_date": eight_days_ago, "settlement_sources": {}})
        )

        client = _mock_client(
            events=[{"settlement_sources": [{"name": "The Weather Company"}]}]
        )
        wm.check_catalog_and_settlement_drift(client)
        client.get_events.assert_called()

    def test_untracked_series_growing_volume_warns(self, tmp_path, monkeypatch, caplog):
        import logging

        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)

        # Deterministic pick (not next(iter(set))), which order-randomizes
        # under hash randomization -- opus-review-caught nondeterminism.
        untracked = sorted(wm.KNOWN_UNTRACKED_RAIN_SERIES)[0]

        def _get_markets(series_ticker, status):
            if series_ticker == untracked:
                return [{"ticker": f"{untracked}-26AUG24-SFO", "volume": 5000}]
            return []

        client = _mock_client()
        client.get_markets.side_effect = _get_markets
        client.get_events.return_value = []

        with caplog.at_level(logging.WARNING):
            wm.check_catalog_and_settlement_drift(client)

        assert untracked in caplog.text
        assert "now has" in caplog.text

    def test_zero_volume_untracked_series_does_not_warn(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)

        client = _mock_client(open_markets=[])
        with caplog.at_level(logging.WARNING):
            wm.check_catalog_and_settlement_drift(client)
        assert "now has" not in caplog.text

    def test_settlement_source_change_warns_on_second_run(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)

        client1 = _mock_client(
            events=[{"settlement_sources": [{"name": "The Weather Company"}]}]
        )
        wm.check_catalog_and_settlement_drift(client1)

        # Force the weekly gate open again for the second run.
        state = json.loads(drift_path.read_text())
        state["last_run_date"] = (_today() - timedelta(days=8)).isoformat()
        drift_path.write_text(json.dumps(state))

        client2 = _mock_client(events=[{"settlement_sources": [{"name": "Synoptic"}]}])
        with caplog.at_level(logging.WARNING):
            wm.check_catalog_and_settlement_drift(client2)

        assert "settlement_sources changed" in caplog.text
        assert "The Weather Company" in caplog.text
        assert "Synoptic" in caplog.text

    def test_no_prior_snapshot_does_not_warn(self, tmp_path, monkeypatch, caplog):
        """First-ever observation of a series' settlement source is not a
        'change' -- nothing to compare against yet."""
        import logging

        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)

        client = _mock_client(
            events=[{"settlement_sources": [{"name": "The Weather Company"}]}]
        )
        with caplog.at_level(logging.WARNING):
            wm.check_catalog_and_settlement_drift(client)
        assert "settlement_sources changed" not in caplog.text

    def test_one_failing_series_does_not_abort_the_sweep(self, tmp_path, monkeypatch):
        import weather_markets as wm

        drift_path = tmp_path / "catalog_drift.json"
        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", drift_path)

        client = _mock_client()
        client.get_markets.side_effect = Exception("API down")
        client.get_events.side_effect = Exception("API down")

        # Must not raise.
        wm.check_catalog_and_settlement_drift(client)
        assert drift_path.exists()

    def test_never_raises_on_total_failure(self, tmp_path, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr(wm, "CATALOG_DRIFT_PATH", Path("/nonexistent/dir/x.json"))
        client = _mock_client()
        wm.check_catalog_and_settlement_drift(client)  # must not raise


# ── paper.check_position_limits: shared manual-placement enforcement point ──


class TestCheckPositionLimitsBatch51:
    def test_rain_daily_unconditionally_blocked(self, monkeypatch):
        import paper

        result = paper.check_position_limits("KXRAIN-26AUG24-SFO", qty=1, price=0.10)
        assert result["ok"] is False
        assert "track-only" in result["reason"]

    def test_rain_weekend_unconditionally_blocked(self, monkeypatch):
        import paper

        result = paper.check_position_limits(
            "KXRAINWKND-26AUG29-SFO", qty=1, price=0.10
        )
        assert result["ok"] is False

    def test_rain_daily_stays_blocked_even_if_some_unrelated_gate_flips(
        self, monkeypatch
    ):
        """Positive control the unconditional design: unlike every other
        family's block, flipping ANY existing gate must not un-block this
        one -- there's no env var wired to it at all."""
        import paper

        monkeypatch.setattr("weather_markets._rain_gates_active", lambda: True)
        monkeypatch.setenv("RAIN_TRADING_ENABLED", "1")
        result = paper.check_position_limits("KXRAIN-26AUG24-SFO", qty=1, price=0.10)
        assert result["ok"] is False

    def test_holiday_temp_blocked_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("HOLIDAY_TEMP_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits(
            "KXHOLIDAYTMAX-260704100-SFO", qty=1, price=0.10
        )
        assert result["ok"] is False
        assert "HOLIDAY_TEMP_TRADING_ENABLED" in result["reason"]

    def test_holiday_temp_not_blocked_when_gate_active(self, monkeypatch):
        """Mutation-test proof the conditional is real, mirrors
        TestCheckPositionLimitsRainConditional's own pattern."""
        import paper

        monkeypatch.setattr("weather_markets._holiday_temp_gates_active", lambda: True)
        result = paper.check_position_limits(
            "KXHOLIDAYTMAX-260704100-SFO", qty=1, price=0.10
        )
        assert result["ok"] is True

    def test_ordinary_daily_temp_unaffected(self, monkeypatch):
        """Positive control: neither new block touches regular KXHIGH/KXLOW
        tickers, which share the same "above"/"below" condition_type."""
        import paper

        monkeypatch.delenv("HOLIDAY_TEMP_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits("KXHIGHSFO-26AUG24-T75", qty=1, price=0.10)
        assert result["ok"] is True


# ── main.py manual-placement guards (cmd_order / _quick_paper_buy / cmd_paper) ──


class TestMainOrderGuardsBatch51:
    def test_cmd_order_refuses_rain_daily_unconditionally(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        main.cmd_order(None, "buy", ["KXRAIN-26AUG24-SFO", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "track-only" in out

    def test_cmd_order_refuses_holiday_temp_when_gate_inactive(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("HOLIDAY_TEMP_TRADING_ENABLED", raising=False)
        main.cmd_order(None, "buy", ["KXHOLIDAYTMAX-260704100-SFO", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "HOLIDAY_TEMP_TRADING_ENABLED" in out

    def test_cmd_order_does_not_refuse_holiday_temp_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._holiday_temp_gates_active", lambda: True)
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_order(
                None, "buy", ["KXHOLIDAYTMAX-260704100-SFO", "yes", "1", "0.10"]
            )
        except Exception:
            pass  # downstream failure (no live market) is expected/irrelevant here
        assert not any(
            "holiday temperature markets are shadow-only" in p for p in printed
        )

    def test_quick_paper_buy_refuses_rain_weekend_unconditionally(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        mock_client = MagicMock()
        _inputs = iter(["KXRAINWKND-26AUG29-SFO"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "track-only" in out
        mock_client.get_market.assert_not_called()

    def test_quick_paper_buy_refuses_holiday_temp_when_gate_inactive(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("HOLIDAY_TEMP_TRADING_ENABLED", raising=False)
        mock_client = MagicMock()
        _inputs = iter(["KXHOLIDAYTMIN-26070450-SFO"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "HOLIDAY_TEMP_TRADING_ENABLED" in out
        mock_client.get_market.assert_not_called()

    def test_cmd_paper_buy_refuses_rain_daily_unconditionally(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        main.cmd_paper(["buy", "KXRAIN-26AUG24-SFO", "yes", "0.10", "1"])
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "track-only" in out
