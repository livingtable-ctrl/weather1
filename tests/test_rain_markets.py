"""
Tests for backlog.txt "RAIN / SNOW / HURRICANE MARKETS":
  Step 1 (schema + safe discovery for KXRAIN*M monthly rain-total ladder
    markets -- zero live-trading behavior change, no probability model).
  Step 2 (the real monthly-accumulation probability model, settlement,
    shadow-only rollout -- Step 1's unconditional analyze_trade() guard is
    gone, replaced by real close_time/days_out gating; see
    TestAnalyzeTradeMonthlyRainGating below for the current behavior).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest


def _rain_market(
    ticker="KXRAINDENM-26JUL-7",
    floor_strike=7,
    strike_type="greater",
    close_hours_from_now=10 * 24,
    yes_bid=0.30,
    yes_ask=0.35,
    volume_fp=1000,
    open_interest_fp=1000,
    now=None,
):
    """`now`, if given, anchors close_time instead of real wall-clock time --
    required whenever the caller also freezes weather_markets.datetime (via
    _pin_today or an inline _FakeDT), so close_time stays fixed relative to
    that frozen "today" rather than drifting apart from it as real time
    passes (the exact fragility test_ticket_checked_after_month_end_does_not_
    crash's docstring already calls out for callers that bypass this
    helper entirely)."""
    close_time = (
        ((now or datetime.now(UTC)) + timedelta(hours=close_hours_from_now))
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "ticker": ticker,
        "title": "Rain in Denver in Jul 2026?",
        "floor_strike": floor_strike,
        "strike_type": strike_type,
        "close_time": close_time,
        "yes_bid_dollars": str(yes_bid),
        "yes_ask_dollars": str(yes_ask),
        "volume_fp": str(volume_fp),
        "open_interest_fp": str(open_interest_fp),
    }


class TestAnalyzeTradeMonthlyRainGating:
    """Step 2: Step 1's unconditional return-None guard is gone. Rain
    tickers now reach a real close_time/days_out gate, then
    _analyze_monthly_rain_trade() -- gated on city/coords resolving and on
    close_time being in the future and within RAIN_MAX_DAYS_OUT, exactly
    like every other market type's gates, not a blanket refusal."""

    def test_bare_ticker_dict_hits_no_city_not_the_old_guard(self):
        """Calling analyze_trade() directly with a bare {"ticker": ...} dict
        (no _city/_date enrichment) now fails at the generic no_city gate --
        the SAME gate a daily ticker would hit under identical bare input --
        not a rain-specific blanket refusal. Confirms the Step 1 guard is
        actually gone, not just renamed."""
        import weather_markets as wm

        wm.reset_gate_counts()
        assert wm.analyze_trade({"ticker": "KXRAINSEAM-26JUL-1"}) is None
        counts = wm.get_gate_counts()
        assert counts.get("no_city") == 1
        assert counts.get("monthly_rain_not_yet_supported") is None

    def test_past_close_time_gates_out(self):
        import weather_markets as wm

        m = _rain_market(close_hours_from_now=-2)
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        assert wm.get_gate_counts().get("monthly_rain_past_close") == 1

    def test_days_out_beyond_rain_max_gates_out(self):
        import weather_markets as wm

        m = _rain_market(close_hours_from_now=(wm.RAIN_MAX_DAYS_OUT + 5) * 24)
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        assert wm.get_gate_counts().get("days_out") == 1

    def test_days_out_at_rain_max_boundary_passes_days_out_gate(self, monkeypatch):
        """Off-by-one check: exactly RAIN_MAX_DAYS_OUT days out must NOT hit
        the days_out gate (> not >=). ACIS station-lookup mocked to None so
        the model bails immediately past the gate check, without making a
        real network call (test-hygiene fix: this used to hit the live
        ACIS API with no mock, review-caught)."""
        import weather_markets as wm

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: None)
        m = _rain_market(close_hours_from_now=wm.RAIN_MAX_DAYS_OUT * 24)
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        wm.analyze_trade(m)
        assert wm.get_gate_counts().get("days_out") is None

    def test_no_forecast_no_date_past_date_gates_never_fire_for_rain(self, monkeypatch):
        """The daily-specific gates this ticker family is exempted from
        must genuinely never fire for it, not just "return None via some
        gate" -- proves the bypass is real, not accidental. ACIS station-
        lookup mocked to None (test-hygiene fix: this used to hit the live
        ACIS API with no mock, review-caught) -- irrelevant to what this
        test actually checks (the daily-gate bypass, not the model itself)."""
        import weather_markets as wm

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: None)
        m = _rain_market()
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        wm.analyze_trade(m)
        counts = wm.get_gate_counts()
        assert counts.get("no_forecast") is None
        assert counts.get("no_date") is None
        assert counts.get("past_date") is None

    def test_daily_high_ticker_unaffected(self):
        """Regression control: an ordinary daily HIGH ticker with no
        forecast data must still hit no_forecast normally -- the new
        `not _is_monthly_rain and ...` guards must not have loosened the
        daily path's own gates."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXHIGHNY-26JUL20-T70", "_city": "NYC"})
        counts = wm.get_gate_counts()
        assert counts.get("no_forecast") == 1
        assert counts.get("monthly_rain_past_close") is None


class TestRainGatesActive:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item 7:
    _rain_gates_active() mirrors _hourly_gates_active()'s exact shape --
    env var AND a settled-sample floor, both required."""

    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_rain_predictions", lambda: 999)
        assert wm._rain_gates_active() is False

    def test_false_when_env_var_set_but_below_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("RAIN_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_rain_predictions", lambda: 19)
        assert wm._rain_gates_active() is False

    def test_true_when_env_var_set_and_sample_floor_met(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("RAIN_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_rain_predictions", lambda: 20)
        assert wm._rain_gates_active() is True

    def test_false_when_sample_floor_met_but_env_var_unset(self, monkeypatch):
        """Both conditions are required -- neither alone suffices."""
        import weather_markets as wm

        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_rain_predictions", lambda: 500)
        assert wm._rain_gates_active() is False

    def test_never_raises_on_count_failure(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("RAIN_TRADING_ENABLED", "1")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("tracker.count_settled_rain_predictions", _boom)
        assert wm._rain_gates_active() is False


class TestCheckPositionLimitsRainConditional:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2: the Step 1
    unconditional block became conditional on _rain_gates_active() -- must
    still block when the gate is inactive (matching Step 1's own tests,
    which run with the gate inactive by default), and must NOT block once
    the gate fires, mutation-tested to prove the conditional is real."""

    def test_still_blocks_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits("KXRAINDENM-26JUL-7", qty=1, price=0.10)
        assert result["ok"] is False

    def test_does_not_block_when_gate_active(self, monkeypatch):
        """Mutation-test proof: flipping _rain_gates_active() to True makes
        the block disappear -- confirms the conditional is real, not a
        hardcoded string check that always fires regardless."""
        import paper

        monkeypatch.setattr("weather_markets._rain_gates_active", lambda: True)
        result = paper.check_position_limits("KXRAINDENM-26JUL-7", qty=1, price=0.10)
        assert result["ok"] is True


class TestAuditSettlementMonthlyRain:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item 5:
    audit_settlement()'s new rain branch reads Kalshi's own expiration_value
    once status='finalized' -- no independent ground-truth re-derivation."""

    def test_finalized_writes_settled_value_not_settled_var(self, monkeypatch):
        import tracker

        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXRAINDENM-26JUL-7", 0),
            )

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "8.3"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        result = tracker.audit_settlement("KXRAINDENM-26JUL-7", settled_yes=True)
        assert result is True
        with tracker._conn() as con:
            row = con.execute(
                "SELECT settled_value, settled_var FROM outcomes WHERE ticker=?",
                ("KXRAINDENM-26JUL-7",),
            ).fetchone()
        assert row["settled_value"] == 8.3
        assert row["settled_var"] is None

    def test_not_finalized_returns_false_no_write(self, monkeypatch):
        """A market with a VALID expiration_value but status != 'finalized'
        must still be refused -- proves the finalized gate itself is real,
        not just the missing-expiration_value path (an earlier version of
        this test used expiration_value=None here too, which made it pass
        vacuously even if the finalized check were deleted)."""
        import tracker

        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXRAINDENM-26JUL-6", 0),
            )

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "active", "expiration_value": "8.3"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        result = tracker.audit_settlement("KXRAINDENM-26JUL-6", settled_yes=True)
        assert result is False
        with tracker._conn() as con:
            row = con.execute(
                "SELECT settled_value FROM outcomes WHERE ticker=?",
                ("KXRAINDENM-26JUL-6",),
            ).fetchone()
        assert row["settled_value"] is None

    def test_missing_expiration_value_returns_false(self, monkeypatch):
        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": None}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        assert tracker.audit_settlement("KXRAINDENM-26JUL-5", settled_yes=True) is False

    def test_non_numeric_expiration_value_returns_false(self, monkeypatch):
        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "not-a-number"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        assert tracker.audit_settlement("KXRAINDENM-26JUL-4", settled_yes=True) is False

    def test_fetch_exception_returns_false_not_raise(self, monkeypatch):
        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                raise RuntimeError("network down")

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        assert tracker.audit_settlement("KXRAINDENM-26JUL-3", settled_yes=True) is False

    def test_no_matching_outcomes_row_returns_false(self, monkeypatch):
        """Review-caught gap: the UPDATE could match zero rows (no prior
        outcomes row for this ticker) and the function still claimed
        success. Must check rowcount, not just that the statement ran."""
        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "5.0"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        # Deliberately no INSERT into outcomes for this ticker.
        result = tracker.audit_settlement("KXRAINDENM-26JUL-NOROW", settled_yes=True)
        assert result is False

    def test_rain_branch_reached_before_parse_city_date_early_return(self, monkeypatch):
        """The real regression this fix targets: parse_city_date() returns
        (city, None) for these tickers, which would hit the generic early
        return before the hourly-style branch further down is ever reached.
        Confirm the rain branch fires without ever calling parse_city_date."""
        import tracker

        called = []
        monkeypatch.setattr(
            "weather_markets.parse_city_date",
            lambda m: (called.append(m) or ("Denver", None)),
        )

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "1.4"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXRAINDENM-26JUN-1", 1),
            )
        result = tracker.audit_settlement("KXRAINDENM-26JUN-1", settled_yes=True)
        assert result is True
        assert called == [], "parse_city_date must never be called for a rain ticker"


class TestParseMarketConditionMonthlyRain:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item 2:
    the real per-bracket threshold, read from floor_strike/strike_type
    directly, replacing the old collapse-to-precip_any behavior."""

    def test_floor_strike_happy_path(self):
        import weather_markets as wm

        market = {
            "ticker": "KXRAINDENM-26JUL-7",
            "title": "Rain in Denver in Jul 2026?",
            "floor_strike": 7,
            "strike_type": "greater",
        }
        assert wm._parse_market_condition(market) == {
            "type": "precip_month_total",
            "threshold": 7.0,
        }

    def test_missing_floor_strike_returns_none(self, caplog):
        import weather_markets as wm

        market = {
            "ticker": "KXRAINDENM-26JUL-7",
            "title": "Rain in Denver in Jul 2026?",
            "strike_type": "greater",
        }
        assert wm._parse_market_condition(market) is None

    def test_unexpected_strike_type_returns_none(self):
        import weather_markets as wm

        market = {
            "ticker": "KXRAINDENM-26JUL-7",
            "title": "Rain in Denver in Jul 2026?",
            "floor_strike": 7,
            "strike_type": "less",
        }
        assert wm._parse_market_condition(market) is None

    def test_non_numeric_floor_strike_returns_none(self):
        import weather_markets as wm

        market = {
            "ticker": "KXRAINDENM-26JUL-7",
            "title": "Rain in Denver in Jul 2026?",
            "floor_strike": "seven",
            "strike_type": "greater",
        }
        assert wm._parse_market_condition(market) is None

    def test_nyc_four_bracket_ladder_all_parse(self):
        import weather_markets as wm

        for n in (1, 2, 3, 4):
            market = {
                "ticker": f"KXRAINNYCM-26JUL-{n}",
                "title": "Rain in NYC in Jul 2026?",
                "floor_strike": n,
                "strike_type": "greater",
            }
            assert wm._parse_market_condition(market) == {
                "type": "precip_month_total",
                "threshold": float(n),
            }

    def test_ordinary_temperature_ticker_unaffected(self):
        """Regression control: branch ordering must not swallow a normal
        temperature ticker."""
        import weather_markets as wm

        market = {
            "ticker": "KXHIGHNY-26JUL20-T70",
            "title": "Will the high in NYC be above 70?",
        }
        assert wm._parse_market_condition(market) == {
            "type": "above",
            "threshold": 70.0,
            "prob_threshold": 70.5,
        }


class TestAnalyzeMonthlyRainTradeEndToEnd:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item 1:
    the real bootstrap model, exercised end-to-end with mocked ACIS/Open-
    Meteo calls (no live network) -- proves the full analyze_trade() ->
    _analyze_monthly_rain_trade() wiring produces a real, well-shaped
    result, not just that the pieces individually work."""

    def _history_all_years_value(self, value, years=20, month=7, days_in_month=31):
        return {
            2000 + y: {month * 100 + d: value for d in range(1, days_in_month + 1)}
            for y in range(years)
        }

    def test_full_pipeline_produces_real_result(self, monkeypatch):
        import weather_markets as wm

        frozen_now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        # 20 years, every year totalling 1.0*31=31.0in for the full month --
        # a market with a 7in threshold should come back near-certain YES,
        # PROVIDED enough days remain in the accrual month for that rate to
        # clear the threshold. _analyze_monthly_rain_trade sums only the
        # REMAINING days (today_local.day onward) against real history, so
        # this test must pin "today" to early in the accrual month --
        # otherwise it silently depends on which day of the month the suite
        # happens to run on (e.g. 6 remaining days * 1.0in/day = 6.0in, which
        # does NOT clear a 7in threshold, even though the full-month total
        # does), and fails only in the back half of the month.
        # Subclass (not a bare stub) so analyze_trade's other datetime.* calls
        # (e.g. _safe_parse_close_time's datetime.fromisoformat) keep working --
        # a bare stub class only exposing now() breaks the first fromisoformat
        # call with AttributeError.
        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                # Honor the requested tz (opus review caught the earlier
                # version silently returning UTC regardless of tz) so this
                # fixture can't mask a genuine local-date bug in the
                # datetime.now(_ZoneInfo(tz)).date() call under test -- it's
                # coincidentally harmless for Denver specifically (2026-07-02
                # 12:00 UTC is still day 2 there), but would not be for every
                # city/instant combination.
                return (
                    datetime(2026, 7, 2, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        history = self._history_all_years_value(1.0, years=20)

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr("acis_precip.fetch_historical_daily", lambda sid: history)
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        result = wm.analyze_trade(m)
        assert result is not None
        assert result["condition"]["type"] == "precip_month_total"
        assert result["method"] in (
            "monthly_rain_bootstrap",
            "monthly_rain_bootstrap_tilted",
        )
        assert result["forecast_prob"] > 0.9  # every historical year exceeded 7in
        assert result["consensus"] is False  # item 6: hardcoded, never computed
        assert result["n_historical_years"] == 20
        assert result["accrual_month"] == "2026-07"
        # Exposure-cap decision: target_date is the close_time date, not the
        # accrual month.
        assert result["target_date"] != "2026-07-01"

    def test_bias_correction_keyed_on_close_dt_month_not_accrual_month(
        self, monkeypatch
    ):
        """Resolved-decision #3 (backlog.txt Step 2 plan): get_quintile_bias
        must be called with close_dt.month, the same month value that ends
        up stored in predictions.market_date -- NOT the ticker's accrual
        month. Passing the accrual month would permanently mismatch what's
        stored and silently return 0.0 bias forever.

        Calls _analyze_monthly_rain_trade() directly (not through
        analyze_trade(), which derives close_dt from wall-clock "now" +
        close_hours_from_now -- too fragile here, since whatever month the
        test happens to run in could coincidentally match the ticker's
        July accrual month, making the accrual-vs-close distinction
        untestable by luck rather than by design). A hardcoded close_dt of
        December (month=12), against a July-accrual ticker, guarantees the
        two can never coincidentally match."""
        import weather_markets as wm

        ticker = "KXRAINDENM-26JUL-7"
        enriched = {
            "ticker": ticker,
            "title": "Rain in Denver in Jul 2026?",
            "_city": "Denver",
        }
        condition = {"type": "precip_month_total", "threshold": 7.0}
        coords = wm.CITY_COORDS["Denver"]
        close_dt = datetime(2026, 12, 15, tzinfo=UTC)
        history = self._history_all_years_value(1.0, years=20)

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr("acis_precip.fetch_historical_daily", lambda sid: history)
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        calls = []
        monkeypatch.setattr(
            "tracker.get_quintile_bias",
            lambda city, month, prob, condition_type=None: (
                calls.append((city, month)) or 0.0
            ),
        )

        result = wm._analyze_monthly_rain_trade(
            enriched, condition, "Denver", coords, close_dt, days_out=10
        )
        assert result is not None
        assert len(calls) == 1
        called_city, called_month = calls[0]
        assert called_city == "Denver"
        assert called_month == 12, (
            f"expected close_dt.month (12, December) to be passed, got "
            f"{called_month} -- if this is 7 (July), the accrual month "
            f"leaked in instead"
        )

    def test_seasonal_tilt_applied_reaches_full_pipeline(self, monkeypatch):
        """Review-caught gap: every other end-to-end test mocks
        fetch_seasonal_precip_mean_mm to None, so tilt_applied=True /
        method=='monthly_rain_bootstrap_tilted' was never actually driven
        through the full analyze_trade() -> _analyze_monthly_rain_trade()
        pipeline (only unit-tested in isolation via
        TestApplySeasonalTilt)."""
        import weather_markets as wm

        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
        )
        m["_city"] = "Denver"
        # Mixed history (not every year identical) so apply_seasonal_tilt's
        # mean(full_month_sums) is meaningfully nonzero and the ratio/shift
        # math actually has something to act on.
        history = {
            2000 + y: {700 + d: 1.0 + (y % 3) * 0.5 for d in range(1, 32)}
            for y in range(20)
        }

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr("acis_precip.fetch_historical_daily", lambda sid: history)
        # A real (non-None) seasonal mean -- drives apply_seasonal_tilt's
        # real branch instead of its None-input no-op.
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: 200.0,
        )

        result = wm.analyze_trade(m)
        assert result is not None
        assert result["seasonal_tilt_applied"] is True
        assert result["method"] == "monthly_rain_bootstrap_tilted"

    def test_too_few_historical_years_returns_none(self, monkeypatch):
        import weather_markets as wm

        m = _rain_market(ticker="KXRAINDENM-26JUL-7", floor_strike=7)
        m["_city"] = "Denver"
        thin_history = self._history_all_years_value(1.0, years=5)  # < 15

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_historical_daily", lambda sid: thin_history
        )
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is None

    def test_month_to_date_any_missing_day_fails_closed(self, monkeypatch):
        """Opus-review-caught HIGH finding (Snow Step 2 review, identical
        gap in this already-shipped rain code): fetch_month_to_date_actual
        returns (sum, n_missing) -- a fetch that comes back present but
        with any "M" (missing) sentinel days must not silently understate
        month_to_date_actual with zero guard. Round-2 review caught that a
        fractional threshold is the wrong statistic for a value added 1:1
        into every bootstrap sample (unlike the historical path's 30-year
        dilution) -- real data can concentrate an entire month's total in
        a small number of days, so the real guard is zero-tolerance: even
        ONE missing day-to-date must refuse to trade."""
        import weather_markets as wm

        frozen_now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 7, 30, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=1 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        # through_day=29 (Jul 30 - 1), only 1 of 29 days missing -- must
        # still refuse under zero-tolerance, even though a real (non-None)
        # sum came back and the fraction (~3.4%) is small.
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.5, 1),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_historical_daily",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is None

    def test_month_to_date_zero_missing_still_trades(self, monkeypatch):
        """Control for the guard above: zero missing days must NOT be
        refused -- confirms the guard doesn't over-trigger on ordinary,
        fully-complete data."""
        import weather_markets as wm

        frozen_now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 7, 10, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        # through_day=9 (Jul 10 - 1), 0 days missing -- fully complete
        # data, must not be refused under zero-tolerance.
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (2.0, 0),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_historical_daily",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is not None

    def test_no_historical_data_returns_none(self, monkeypatch):
        import weather_markets as wm

        m = _rain_market(ticker="KXRAINDENM-26JUL-7", floor_strike=7)
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr("acis_precip.fetch_historical_daily", lambda sid: None)

        assert wm.analyze_trade(m) is None

    def test_unmapped_city_station_returns_none(self, monkeypatch):
        import weather_markets as wm

        m = _rain_market(ticker="KXRAINDENM-26JUL-7", floor_strike=7)
        m["_city"] = "Denver"
        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: None)

        assert wm.analyze_trade(m) is None

    def test_month_to_date_fetch_failure_fails_closed_not_zero(self, monkeypatch):
        """Review-caught gap: fetch_month_to_date_actual() returns (None, 0)
        both when nothing has accrued yet (through_day < 1, legitimate 0.0)
        and on a genuine fetch failure (through_day >= 1). Coercing the
        latter to 0.0 would silently underestimate a real accrued total --
        must fail closed (no trade) instead."""
        import weather_markets as wm

        m = _rain_market(ticker="KXRAINDENM-26JUL-7", floor_strike=7)
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (None, 0),
        )
        # Historical data present and sufficient -- isolates the failure to
        # specifically the month-to-date fetch, not a missing-history bail.
        monkeypatch.setattr(
            "acis_precip.fetch_historical_daily",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is None


class TestRainForecastBlendSignal:
    """backlog.txt "RAIN MARKETS -- MONTHLY MODEL HAS NO DAY-SPECIFIC
    FORECAST SIGNAL": the new shadow/log-only ensemble-forecast blend.
    Never changes forecast_prob/method/ci_low/ci_high/pricing -- only adds
    (or omits) a "signals" key on the result dict."""

    def _history_all_years_value(self, value, years=20, month=7, days_in_month=31):
        return {
            2000 + y: {month * 100 + d: value for d in range(1, days_in_month + 1)}
            for y in range(years)
        }

    def _pin_today(self, monkeypatch, day):
        """Freeze weather_markets.datetime.now() to 2026-07-<day> 12:00,
        honoring the requested tz (same discipline as
        TestAnalyzeMonthlyRainTradeEndToEnd's own _FakeDT -- an opus review
        already caught a version of this that silently returned UTC
        regardless of tz).

        Returns the frozen instant so callers can pass it to _rain_market()
        as `now=`, keeping the market's close_time anchored to this same
        frozen "today" instead of real wall-clock time (which drifts apart
        from it as real time passes and eventually trips the days_out gate)."""
        frozen_now = datetime(2026, 7, day, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 7, day, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 7, day, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)
        return frozen_now

    def _mock_acis(self, monkeypatch, years=20):
        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_historical_daily",
            lambda sid: self._history_all_years_value(1.0, years=years),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

    def test_full_coverage_logs_signal_without_changing_forecast_prob(
        self, monkeypatch
    ):
        """Remaining window (Jul 20-31 = 12 days) fits entirely inside the
        16-day forecast horizon -- signal must be computed and logged, and
        forecast_prob/method/ci_low/ci_high must be byte-identical to a run
        with no ensemble mock at all (proves zero behavior change to the
        existing bootstrap-only calculation)."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 20)
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)
        # Non-zero month-to-date so the mtd + member sum actually matters
        # (opus-review-caught: the original version left mtd at _mock_acis's
        # default 0.0, so the test's own hardcoded "0.0 +" expected-value
        # formula couldn't have caught a wrong mtd term either).
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (2.0, 0),
        )

        # 30 members straddling the 7.0in threshold (mtd=2.0 + member must
        # exceed 7.0, i.e. member > 5.0) -- members 4.0..18.5in, so roughly
        # 90% cross and 10% don't. Opus-review-caught: the original members
        # (1.0-6.0in) never exceeded 7.0 even before adding mtd, so the
        # fraction was always 0 -> collapsed to the 0.01 clamp floor
        # regardless of whether the real formula was even used (verified by
        # mutation: replacing the whole computation with a hardcoded 0.0
        # passed this assertion unchanged).
        members = [4.0 + i * 0.5 for i in range(30)]  # 4.0..18.5in totals

        calls = []

        def _capture(*a, **kw):
            calls.append(a)
            return members

        monkeypatch.setattr(wm, "_fetch_ensemble_precip_multiday", _capture)
        result_with_blend = wm.analyze_trade(m)
        # Opus-review-caught gap: no prior test pinned the actual date range
        # passed to the fetch -- an off-by-one on remaining_start_day, or
        # swapped lat/lon/tz, would have been invisible.
        assert len(calls) == 1
        called_lat, called_lon, called_tz, called_start, called_end = calls[0]
        assert (called_lat, called_lon, called_tz) == wm.CITY_COORDS["Denver"]
        assert called_start == date(2026, 7, 20)  # today itself, per _pin_today
        assert called_end == date(2026, 7, 31)  # accrual month-end
        assert result_with_blend is not None
        assert "signals" in result_with_blend
        expected_prob = sum(1 for v in members if 2.0 + v > 7.0) / len(members)
        expected_prob = max(0.01, min(0.99, expected_prob))
        assert 0.01 < expected_prob < 0.99, (
            "test fixture itself must land strictly inside the clamp range "
            "or this assertion can't distinguish a real computation from "
            "the clamp floor/ceiling"
        )
        assert result_with_blend["signals"][
            "rain_forecast_blend_prob"
        ] == pytest.approx(expected_prob)

        # Same scenario with the ensemble fetch failing (returns None) --
        # forecast_prob/method/ci must match exactly, proving the new
        # signal is purely additive and never perturbs the existing calc.
        monkeypatch.setattr(
            wm, "_fetch_ensemble_precip_multiday", lambda *a, **kw: None
        )
        result_no_blend = wm.analyze_trade(m)
        assert result_no_blend is not None
        assert "signals" not in result_no_blend
        for key in ("forecast_prob", "method", "ci_low", "ci_high", "ci_width"):
            assert result_with_blend[key] == result_no_blend[key], key

    def test_remaining_window_exceeds_16_days_skips_signal(self, monkeypatch):
        """Remaining window (Jul 1-31 = 31 days) exceeds the 16-day forecast
        horizon -- the fetch must never even be attempted this cycle (no
        partial-coverage complexity in this pass), and no signal is logged.

        Uses a call-counter, not a raising mock: the new block wraps the
        fetch in a defensive try/except (see test_fetch_exception_fails_
        open_not_raised), which would silently swallow a raise and make a
        raising-mock version of this test pass for the wrong reason even if
        the scope-boundary check were deleted entirely -- mutation-tested
        and confirmed vacuous in exactly that way before switching to this
        counter-based version."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 1)
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)

        call_count = {"n": 0}

        def _count_call(*a, **kw):
            call_count["n"] += 1
            return [3.0] * 20  # would produce a real signal if reached

        monkeypatch.setattr(wm, "_fetch_ensemble_precip_multiday", _count_call)

        result = wm.analyze_trade(m)
        assert result is not None
        assert call_count["n"] == 0, (
            "_fetch_ensemble_precip_multiday must not be called when the "
            "remaining window exceeds the 16-day forecast horizon"
        )
        assert "signals" not in result

    def test_boundary_just_over_16_days_skips_fetch(self, monkeypatch):
        """Opus-review-caught gap: only two widely-separated points (11 and
        30 days via (remaining_end_date - today_local).days) were tested,
        so the exact `<= 15` boundary itself had no real coverage
        (mutation-verified: `<= 14`, `<= 16`, and `<= 25` all previously
        passed the full suite unnoticed). today=Jul 15 -> remaining_end_date
        (Jul 31) minus today = 16 days -- one past the boundary, must NOT
        fetch."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 15)  # (Jul 31 - Jul 15).days == 16
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)

        call_count = {"n": 0}

        def _count_call(*a, **kw):
            call_count["n"] += 1
            return None

        monkeypatch.setattr(wm, "_fetch_ensemble_precip_multiday", _count_call)

        result = wm.analyze_trade(m)
        assert result is not None
        assert call_count["n"] == 0, "16 days past today must NOT trigger a fetch"
        assert "signals" not in result

    def test_boundary_exactly_16_day_horizon_does_fetch(self, monkeypatch):
        """Inverse of the above: today=Jul 16 -> (Jul 31 - Jul 16).days == 15,
        exactly at the `<= 15` boundary -- must fetch."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 16)  # (Jul 31 - Jul 16).days == 15
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)

        call_count = {"n": 0}

        def _count_call(*a, **kw):
            call_count["n"] += 1
            return None

        monkeypatch.setattr(wm, "_fetch_ensemble_precip_multiday", _count_call)

        result = wm.analyze_trade(m)
        assert result is not None
        assert call_count["n"] == 1, "15 days past today (the boundary) must fetch"

    def test_ticket_checked_after_month_end_does_not_crash(self, monkeypatch):
        """Opus-review-caught reachability: a July-accrual ticket can be
        analyzed after the accrual month has ended but before the market
        closes/finalizes (_analyze_monthly_rain_trade's own "already past
        month-end" branch, remaining_start_day = days_in_month + 1). The new
        block's date() construction must not raise in this real, reachable
        state -- proves the belt-and-suspenders try/except placement (moved
        inside per this same review) actually protects it, and that the
        signal is correctly just absent rather than crashing the ticket.

        Calls _analyze_monthly_rain_trade() directly with an explicit
        close_dt, not through analyze_trade() (whose close_time is derived
        from real wall-clock "now" + close_hours_from_now, independent of
        this test's frozen "now" -- the two could races against each other
        near a UTC day boundary and spuriously hit the past-close gate,
        exactly the fragility TestAnalyzeMonthlyRainTradeEndToEnd's own
        test_bias_correction_keyed_on_close_dt_month_not_accrual_month
        already avoids for the identical reason)."""
        import weather_markets as wm

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 8, 2, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)
        self._mock_acis(monkeypatch)

        call_count = {"n": 0}

        def _count_call(*a, **kw):
            call_count["n"] += 1
            return None

        monkeypatch.setattr(wm, "_fetch_ensemble_precip_multiday", _count_call)

        enriched = {
            "ticker": "KXRAINDENM-26JUL-7",
            "title": "Rain in Denver in Jul 2026?",
            "_city": "Denver",
        }
        condition = {"type": "precip_month_total", "threshold": 7.0}
        coords = wm.CITY_COORDS["Denver"]
        close_dt = datetime(2026, 8, 10, tzinfo=UTC)

        result = wm._analyze_monthly_rain_trade(
            enriched, condition, "Denver", coords, close_dt, days_out=8
        )  # must not raise
        assert result is not None
        assert call_count["n"] == 0  # remaining_start_date is None in this branch
        assert "signals" not in result

    def test_after_month_end_any_missing_day_fails_closed(self, monkeypatch):
        """Opus-review-caught test gap (round 2): the "already past
        month-end" branch (remaining_start_day = days_in_month + 1) had
        ZERO test coverage of its own missing-data guard -- mutation-
        confirmed that widening its threshold left the entire suite green.
        Mirrors test_ticket_checked_after_month_end_does_not_crash's direct
        _analyze_monthly_rain_trade() call (avoiding the wall-clock race
        with analyze_trade()'s independently-derived close_time) plus
        snow's identical after-month-end test."""
        import weather_markets as wm

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 8, 2, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)
        monkeypatch.setattr("acis_precip._station_sid_for_city", lambda city: "DEN")
        # through_day=31 (full July), 1 of 31 days missing -- must refuse
        # even though a real (non-None) sum came back.
        monkeypatch.setattr(
            "acis_precip.fetch_month_to_date_actual",
            lambda sid, year, month, through_day: (0.5, 1),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_historical_daily",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_precip.fetch_seasonal_precip_mean_mm",
            lambda lat, lon, tz, year, month: None,
        )

        enriched = {
            "ticker": "KXRAINDENM-26JUL-7",
            "title": "Rain in Denver in Jul 2026?",
            "_city": "Denver",
        }
        condition = {"type": "precip_month_total", "threshold": 7.0}
        coords = wm.CITY_COORDS["Denver"]
        close_dt = datetime(2026, 8, 10, tzinfo=UTC)

        result = wm._analyze_monthly_rain_trade(
            enriched, condition, "Denver", coords, close_dt, days_out=8
        )
        assert result is None

    def test_ensemble_fetch_none_fails_open(self, monkeypatch):
        """Fetch failure / fully-outside-horizon (returns None) must not
        affect the trade decision at all -- no signal logged, everything
        else unchanged."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 20)
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)
        monkeypatch.setattr(
            wm, "_fetch_ensemble_precip_multiday", lambda *a, **kw: None
        )

        result = wm.analyze_trade(m)
        assert result is not None
        assert "signals" not in result

    def test_thin_member_count_fails_open(self, monkeypatch):
        """Fewer than 15 members (the bootstrap_ci_month_total-matching
        trust floor) must fail open exactly like a None fetch result."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 20)
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)
        monkeypatch.setattr(
            wm, "_fetch_ensemble_precip_multiday", lambda *a, **kw: [3.0] * 5
        )

        result = wm.analyze_trade(m)
        assert result is not None
        assert "signals" not in result

    def test_fetch_exception_fails_open_not_raised(self, monkeypatch):
        """A raw exception inside the ensemble fetch must be caught by the
        new block's own defensive try/except -- never propagate up and take
        down the whole (already-working) bootstrap-only analysis."""
        import weather_markets as wm

        frozen_now = self._pin_today(monkeypatch, 20)
        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"
        self._mock_acis(monkeypatch)

        def _boom(*a, **kw):
            raise RuntimeError("simulated unexpected failure")

        monkeypatch.setattr(wm, "_fetch_ensemble_precip_multiday", _boom)

        result = wm.analyze_trade(m)  # must not raise
        assert result is not None
        assert "signals" not in result
        assert result["forecast_prob"] is not None  # existing calc unaffected


class TestFetchEnsemblePrecipMultiday:
    """Unit tests for _fetch_ensemble_precip_multiday itself, mocking
    _om_request directly (mirrors test_weather_markets.py's existing
    _fake_om_request pattern for sibling ensemble-fetch functions)."""

    def _fake_resp(self, daily):
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"daily": daily}
        return resp

    def test_sums_per_member_across_requested_range(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            if model == "icon_seamless":
                daily = {
                    "time": ["2026-07-20", "2026-07-21", "2026-07-22"],
                    "precipitation_sum_member01": [1.0, 2.0, 3.0],
                    "precipitation_sum_member02": [0.5, 0.5, 0.5],
                }
            else:
                daily = {
                    "time": [],
                }
            return self._fake_resp(daily)

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless"])

        totals = wm._fetch_ensemble_precip_multiday(
            39.86,
            -104.67,
            "America/Denver",
            date(2026, 7, 20),
            date(2026, 7, 22),
        )
        assert totals is not None
        assert sorted(totals) == pytest.approx(sorted([6.0, 1.5]))  # 1+2+3, 0.5*3
        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()

    def test_partial_coverage_member_excluded_not_truncated(self, monkeypatch):
        """Opus-review-caught bug (2026-07-28, verified via a live Open-Meteo
        API call): a model's response uses a FULL-length `time` array padded
        with null values past that model's own real forecast horizon -- it
        does NOT truncate the array. The original version of this function
        summed whatever non-null values were present per member regardless
        of count, so a member covering only 2 of 3 requested days (its
        model's horizon fell short) got pooled as if its 2-day total were
        equivalent to a full 3-day total from another member -- silently
        biasing the whole signal low. This reproduces the real null-padded
        shape directly (not the genuinely-short array this test used to
        fake, which the real API doesn't produce) and proves the
        short-horizon member is excluded entirely, not truncated-summed."""
        import weather_markets as wm

        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            if model == "icon_seamless":
                daily = {
                    # Full-length time array (real API shape) -- member01's
                    # own horizon only reaches day 2 of 3, day 3 is null-
                    # padded, not absent from the array.
                    "time": ["2026-07-20", "2026-07-21", "2026-07-22"],
                    "precipitation_sum_member01": [1.0, 2.0, None],
                    "precipitation_sum_member02": [0.5, 0.5, 0.5],  # full coverage
                }
            else:
                daily = {"time": []}
            return self._fake_resp(daily)

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless"])

        totals = wm._fetch_ensemble_precip_multiday(
            39.86,
            -104.67,
            "America/Denver",
            date(2026, 7, 20),
            date(2026, 7, 22),
        )
        assert totals is not None
        # member01 (partial coverage) excluded entirely; member02 (full
        # coverage) is the only one counted, at its real 3-day total.
        assert totals == pytest.approx([1.5])
        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()

    def test_genuinely_short_time_array_treated_same_as_no_coverage(self, monkeypatch):
        """Belt-and-suspenders: even if a response's `time` array were
        genuinely shorter than the requested range (not the real null-padded
        shape, but defend against it anyway), every member must still be
        excluded rather than summed over whatever's present."""
        import weather_markets as wm

        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            model = kwargs.get("params", {}).get("models")
            if model == "icon_seamless":
                daily = {
                    "time": ["2026-07-20", "2026-07-21"],  # only 2 of 3 requested days
                    "precipitation_sum_member01": [1.0, 2.0],
                }
            else:
                daily = {"time": []}
            return self._fake_resp(daily)

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless"])

        totals = wm._fetch_ensemble_precip_multiday(
            39.86,
            -104.67,
            "America/Denver",
            date(2026, 7, 20),
            date(2026, 7, 22),
        )
        assert totals is None  # icon was the only model, contributed nothing
        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()

    def test_all_null_model_excluded_via_circuit_breaker_failure(self, monkeypatch):
        """Opus-review-caught gap: the original version only made
        icon_seamless all-null while ecmwf_ifs025 (unconditionally called
        regardless of the ENSEMBLE_MODELS mock) returned an empty range and
        called record_success() -- which resets _ensemble_cb's failure
        counter, so the test could never actually observe that icon's
        failure had been recorded, only that the final totals were None
        (which an unrelated bug could also produce). Making EVERY model
        respond all-null means the failure count survives to the final
        assertion instead of being silently reset."""
        from datetime import date

        import weather_markets as wm

        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        wm._ensemble_cb.record_success()
        _before = wm._ensemble_cb.failure_count

        def _fake_om_request(method, url, **kwargs):
            daily = {
                "time": ["2026-07-20", "2026-07-21"],
                "precipitation_sum_member01": [None, None],
            }
            return self._fake_resp(daily)

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless"])

        totals = wm._fetch_ensemble_precip_multiday(
            39.86,
            -104.67,
            "America/Denver",
            date(2026, 7, 20),
            date(2026, 7, 21),
        )
        assert totals is None  # every model was all-null -> nothing usable
        assert wm._ensemble_cb.failure_count > _before, (
            "all-null response must actually record a circuit-breaker "
            "failure, not just happen to return None for an unrelated reason"
        )
        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        wm._ensemble_cb.record_success()  # leave the shared breaker clean

    def test_circuit_open_short_circuits_without_network_call(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        called = []

        def _fake_om_request(method, url, **kwargs):
            called.append(1)
            raise AssertionError("must not be called while circuit is open")

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm._ensemble_cb, "is_open", lambda: True)

        totals = wm._fetch_ensemble_precip_multiday(
            39.86,
            -104.67,
            "America/Denver",
            date(2026, 7, 20),
            date(2026, 7, 21),
        )
        assert totals is None
        assert called == []

    def test_no_model_covers_range_returns_none(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()
        wm._ensemble_cb.record_success()

        def _fake_om_request(method, url, **kwargs):
            # Every model returns dates entirely outside the requested range.
            daily = {
                "time": ["2027-01-01"],
                "precipitation_sum_member01": [1.0],
            }
            return self._fake_resp(daily)

        monkeypatch.setattr(wm, "_om_request", _fake_om_request)
        monkeypatch.setattr(wm, "ENSEMBLE_MODELS", ["icon_seamless"])

        totals = wm._fetch_ensemble_precip_multiday(
            39.86,
            -104.67,
            "America/Denver",
            date(2026, 7, 20),
            date(2026, 7, 21),
        )
        assert totals is None
        wm._PRECIP_ENSEMBLE_MULTIDAY_CACHE.clear()


class TestComputeMarketImpliedGroupsMonthlyRain:
    """backlog.txt "RAIN MARKETS -- LADDER/SIBLING GROUPING FOR MARKET-
    IMPLIED DISTRIBUTION IS A BLANKET EXCLUSION, NOT REAL (city, month)
    GROUPING" (resolved 2026-07-31): compute_market_implied_distributions()
    used to blanket-exclude every KXRAIN*M ticker; it now groups them by
    (city, "RAIN", year, month) via market_implied_rain_event_key() and
    fits them with fit_market_implied_distribution()'s rain-appropriate
    sigma_bounds, structurally distinct from temperature's (city, date_iso)
    key so the two can never collide in the same returned dict. Renamed
    from TestComputeMarketImpliedExcludesMonthlyRain, whose 3 tests all
    asserted the exclusion this fix removed."""

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
        # strike_type="greater" matches every real KXRAIN*M bracket
        # (_parse_market_condition refuses to guess any other direction) --
        # bid/ask must decrease as floor_strike increases, same reasoning as
        # _daily_market above, for the fit to have a real CDF-shaped input
        # to converge on rather than a degenerate one.
        return {
            "ticker": f"KXRAINSEAM-26JUL-{int(floor_strike)}",
            "title": "Rain in Seattle in Jul 2026?",
            "close_time": "2026-08-01T03:59:59Z",
            "strike_type": "greater",
            "yes_bid": bid,
            "yes_ask": ask,
            "floor_strike": floor_strike,
            "volume_fp": 500,
        }

    def test_mixed_list_daily_fit_unaffected_by_rain_siblings(self):
        """Rain siblings must not leak into the temperature event's own fit
        -- they're grouped under a completely separate (city, "RAIN", year,
        month) key, never pooled with (city, date_iso) temperature events."""
        import weather_markets as wm

        daily_only = [
            self._daily_market(70.0, "70", 75, 80),
            self._daily_market(75.0, "75", 45, 50),
            self._daily_market(80.0, "80", 15, 20),
        ]
        rain_extra = [
            self._rain_market(1, 80, 85),
            self._rain_market(4, 45, 50),
            self._rain_market(7, 10, 15),
        ]

        fit_daily_only = wm.compute_market_implied_distributions(daily_only)
        fit_mixed = wm.compute_market_implied_distributions(daily_only + rain_extra)

        assert fit_daily_only[("NYC", "2026-07-20")] is not None, (
            "test fixture itself is degenerate (fit didn't converge) -- "
            "this assertion isn't testing anything real"
        )
        assert (
            fit_mixed[("NYC", "2026-07-20")] == fit_daily_only[("NYC", "2026-07-20")]
        ), (
            "monthly-rain siblings changed the daily market-implied fit -- "
            "they leaked into the temperature event's group"
        )

    def test_rain_only_list_produces_a_real_distribution(self):
        """The actual regression this backlog entry fixes: a rain-only
        ladder must now be grouped by (city, "RAIN", year, month) and fit a
        real distribution -- previously this returned {} unconditionally."""
        import weather_markets as wm

        rain_only = [
            self._rain_market(1, 80, 85),
            self._rain_market(4, 45, 50),
            self._rain_market(7, 10, 15),
        ]
        result = wm.compute_market_implied_distributions(rain_only)

        assert list(result.keys()) == [("Seattle", "RAIN", 2026, 7)]
        assert result[("Seattle", "RAIN", 2026, 7)] is not None, (
            "test fixture itself is degenerate (fit didn't converge) -- "
            "this assertion isn't testing anything real"
        )
        fitted_sigma = result[("Seattle", "RAIN", 2026, 7)]["implied_sigma"]
        assert (
            wm._RAIN_IMPLIED_SIGMA_BOUNDS[0]
            <= fitted_sigma
            <= wm._RAIN_IMPLIED_SIGMA_BOUNDS[1]
        ), (
            "fitted sigma outside the rain-specific sigma_bounds -- "
            "the °F-tuned default bounds were used instead"
        )

    def test_rain_key_used_even_if_parse_city_date_were_patched(self, monkeypatch):
        """Regression guard for the routing order: rain tickers must be
        routed to market_implied_rain_event_key() BEFORE parse_city_date()
        is ever consulted, not merely because parse_city_date() happens to
        return None for them today. Patches parse_city_date() to return a
        real (city, date) for a rain ticker (as if Kalshi ever added a day
        component to the ticker format) and confirms the rain ticker is
        still grouped under its (city, "RAIN", year, month) key, never a
        (city, date_iso) one -- proving the routing is structural, not
        coincidental."""
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
            "rain market was grouped under a (city, date_iso) key despite "
            "the routing order -- parse_city_date() was consulted for a "
            "rain ticker instead of the rain-specific key builder"
        )
        assert ("Seattle", "RAIN", 2026, 7) in result, (
            "rain market did not reach its own (city, RAIN, year, month) group at all"
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


class TestQuickPaperBuyAndCmdPaperRainGuards:
    """Opus-review-caught gap (Snow Step 2 round-2 review): the new
    hurricane/snow guards added to _quick_paper_buy()/cmd_paper() apply
    with EQUAL force to rain -- unlike hurricane/snow, rain's shadow gate
    (_rain_gates_active()) is live and accumulating real settled
    predictions today, so this is not a theoretical gap for it. Mirrors
    test_snow_markets.py's TestQuickPaperBuyAndCmdPaperSnowGuards exactly."""

    def test_quick_paper_buy_refuses_rain_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)
        mock_client = MagicMock()
        _inputs = iter(["KXRAINDENM-26JUL-7"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "rain" in out.lower()
        assert "RAIN_TRADING_ENABLED" in out
        mock_client.get_market.assert_not_called()

    def test_quick_paper_buy_does_not_refuse_rain_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._rain_gates_active", lambda: True)
        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("no real market in test")
        _inputs = iter(["KXRAINDENM-26JUL-7", "q"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main._quick_paper_buy(mock_client)
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)

    def test_cmd_paper_refuses_rain_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("RAIN_TRADING_ENABLED", raising=False)

        main.cmd_paper(["buy", "KXRAINDENM-26JUL-7", "yes", "0.10", "1"])

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "rain" in out.lower()
        assert "RAIN_TRADING_ENABLED" in out

    def test_cmd_paper_does_not_refuse_rain_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._rain_gates_active", lambda: True)

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_paper(["buy", "KXRAINDENM-26JUL-7", "yes", "0.10", "1"])
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)
