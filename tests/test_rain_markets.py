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

from datetime import UTC, datetime, timedelta


def _rain_market(
    ticker="KXRAINDENM-26JUL-7",
    floor_strike=7,
    strike_type="greater",
    close_hours_from_now=10 * 24,
    yes_bid=0.30,
    yes_ask=0.35,
    volume_fp=1000,
    open_interest_fp=1000,
):
    close_time = (
        (datetime.now(UTC) + timedelta(hours=close_hours_from_now))
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

        m = _rain_market(
            ticker="KXRAINDENM-26JUL-7",
            floor_strike=7,
            close_hours_from_now=5 * 24,
        )
        m["_city"] = "Denver"

        # 20 years, every year totalling 1.0*31=31.0in for the full month --
        # a market with a 7in threshold should come back near-certain YES.
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
