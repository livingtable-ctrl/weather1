"""
Tests for backlog.txt "RAIN / SNOW / HURRICANE MARKETS":
  Snow Step 1 (schema + safe discovery for KXDENSNOWM, the one snow series
    among this bot's 21 tracked cities that has ever had a real market --
    zero live-trading behavior change, no probability model).
  Snow Step 2 (the real monthly-accumulation probability model, settlement,
    shadow-only rollout -- Step 1's unconditional analyze_trade() guard is
    gone, replaced by real close_time/days_out gating; see
    TestAnalyzeTradeMonthlySnowGating below for the current behavior).
    Mirrors test_rain_markets.py's Step 2 test shape exactly, via
    acis_snow.py instead of acis_precip.py.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _mock_client(live_tickers):
    client = MagicMock()
    client.get_series_list.return_value = [{"ticker": t} for t in live_tickers]
    return client


def _snow_market(
    ticker="KXDENSNOWM-26DEC-5.0",
    floor_strike=5.0,
    strike_type="greater",
    close_time=None,
    close_hours_from_now=10 * 24,
    yes_bid=0.30,
    yes_ask=0.35,
    volume_fp=500,
    open_interest_fp=500,
    now=None,
):
    """`now`, if given, anchors close_time instead of real wall-clock time --
    required whenever the caller also freezes weather_markets.datetime,
    mirroring _rain_market's identical helper in test_rain_markets.py.
    Explicit `close_time` overrides the relative-offset computation
    entirely, for tests that need a fixed calendar date."""
    if close_time is None:
        close_time = (
            ((now or datetime.now(UTC)) + timedelta(hours=close_hours_from_now))
            .isoformat()
            .replace("+00:00", "Z")
        )
    return {
        "ticker": ticker,
        "title": "Snow in Denver in Dec 2026?",
        "yes_sub_title": f"Above {floor_strike} inches",
        "floor_strike": floor_strike,
        "strike_type": strike_type,
        "close_time": close_time,
        "yes_bid_dollars": str(yes_bid),
        "yes_ask_dollars": str(yes_ask),
        "volume_fp": str(volume_fp),
        "open_interest_fp": str(open_interest_fp),
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


class TestParseMarketConditionMonthlySnow:
    """backlog.txt Snow Step 2: the real per-bracket threshold, read from
    floor_strike/strike_type directly -- mirrors rain's identical tests."""

    def test_floor_strike_happy_path(self):
        import weather_markets as wm

        market = {
            "ticker": "KXDENSNOWM-26DEC-5",
            "title": "Snow in Denver in Dec 2026?",
            "floor_strike": 5,
            "strike_type": "greater",
        }
        assert wm._parse_market_condition(market) == {
            "type": "snow_month_total",
            "threshold": 5.0,
        }

    def test_missing_floor_strike_returns_none(self):
        import weather_markets as wm

        market = {
            "ticker": "KXDENSNOWM-26DEC-5",
            "title": "Snow in Denver in Dec 2026?",
            "strike_type": "greater",
        }
        assert wm._parse_market_condition(market) is None

    def test_unexpected_strike_type_returns_none(self):
        import weather_markets as wm

        market = {
            "ticker": "KXDENSNOWM-26DEC-5",
            "title": "Snow in Denver in Dec 2026?",
            "floor_strike": 5,
            "strike_type": "less",
        }
        assert wm._parse_market_condition(market) is None

    def test_non_numeric_floor_strike_returns_none(self):
        import weather_markets as wm

        market = {
            "ticker": "KXDENSNOWM-26DEC-5",
            "title": "Snow in Denver in Dec 2026?",
            "floor_strike": "five",
            "strike_type": "greater",
        }
        assert wm._parse_market_condition(market) is None

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

    def test_rain_ticker_unaffected(self):
        """Regression control: the snow branch must not swallow a rain
        ticker (both are "-YYMON-N"-shaped, floor_strike/strike_type-based
        ladders -- the branch must key off ticker prefix, not field shape)."""
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


class TestAnalyzeTradeMonthlySnowGating:
    """Snow Step 2: Step 1's unconditional return-None guard is gone.
    Snow tickers now reach a real close_time/days_out gate, then
    _analyze_monthly_snow_trade() -- gated on city/coords resolving and on
    close_time being in the future and within SNOW_MAX_DAYS_OUT, exactly
    like rain's identical gating."""

    def test_bare_ticker_dict_hits_no_city_not_the_old_guard(self):
        """Confirms the Step 1 guard is actually gone, not just renamed --
        a bare {"ticker": ...} dict (no _city enrichment) now fails at the
        generic no_city gate, the SAME gate a daily ticker would hit."""
        import weather_markets as wm

        wm.reset_gate_counts()
        assert wm.analyze_trade({"ticker": "KXDENSNOWM-26DEC-5.0"}) is None
        counts = wm.get_gate_counts()
        assert counts.get("no_city") == 1
        assert counts.get("monthly_snow_not_yet_supported") is None

    def test_past_close_time_gates_out(self):
        import weather_markets as wm

        m = _snow_market(close_hours_from_now=-2)
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        assert wm.get_gate_counts().get("monthly_snow_past_close") == 1

    def test_days_out_beyond_snow_max_gates_out(self):
        import weather_markets as wm

        m = _snow_market(close_hours_from_now=(wm.SNOW_MAX_DAYS_OUT + 5) * 24)
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        assert wm.analyze_trade(m) is None
        assert wm.get_gate_counts().get("days_out") == 1

    def test_days_out_at_snow_max_boundary_passes_days_out_gate(self, monkeypatch):
        """Off-by-one check: exactly SNOW_MAX_DAYS_OUT days out must NOT
        hit the days_out gate (> not >=). ACIS station-lookup mocked to
        None so the model bails immediately past the gate check, without a
        real network call."""
        import weather_markets as wm

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: None)
        m = _snow_market(close_hours_from_now=wm.SNOW_MAX_DAYS_OUT * 24)
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        wm.analyze_trade(m)
        assert wm.get_gate_counts().get("days_out") is None

    def test_no_forecast_no_date_past_date_gates_never_fire_for_snow(self, monkeypatch):
        """The daily-specific gates this ticker family is exempted from
        must genuinely never fire for it."""
        import weather_markets as wm

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: None)
        m = _snow_market()
        m["_city"] = "Denver"
        wm.reset_gate_counts()
        wm.analyze_trade(m)
        counts = wm.get_gate_counts()
        assert counts.get("no_forecast") is None
        assert counts.get("no_date") is None
        assert counts.get("past_date") is None

    def test_daily_high_ticker_unaffected(self):
        """Regression control: an ordinary daily HIGH ticker with no
        forecast data must still hit no_forecast normally."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXHIGHNY-26JUL20-T70", "_city": "NYC"})
        counts = wm.get_gate_counts()
        assert counts.get("no_forecast") == 1
        assert counts.get("monthly_snow_past_close") is None

    def test_rain_ticker_unaffected(self):
        """Regression control: the new snow gating must not collide with
        the existing monthly-rain ticker family."""
        import weather_markets as wm

        wm.reset_gate_counts()
        wm.analyze_trade({"ticker": "KXRAINDENM-26JUL-7"})
        assert wm.get_gate_counts().get("monthly_snow_past_close") is None


class TestSnowGatesActive:
    """backlog.txt Snow Step 2 shadow-only rollout: _snow_gates_active()
    mirrors _rain_gates_active()'s exact shape -- env var AND a settled-
    sample floor, both required."""

    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_snow_predictions", lambda: 999)
        assert wm._snow_gates_active() is False

    def test_false_when_env_var_set_but_below_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("SNOW_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_snow_predictions", lambda: 19)
        assert wm._snow_gates_active() is False

    def test_true_when_env_var_set_and_sample_floor_met(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("SNOW_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_snow_predictions", lambda: 20)
        assert wm._snow_gates_active() is True

    def test_false_when_sample_floor_met_but_env_var_unset(self, monkeypatch):
        """Both conditions are required -- neither alone suffices."""
        import weather_markets as wm

        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_snow_predictions", lambda: 500)
        assert wm._snow_gates_active() is False

    def test_never_raises_on_count_failure(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("SNOW_TRADING_ENABLED", "1")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("tracker.count_settled_snow_predictions", _boom)
        assert wm._snow_gates_active() is False

    def test_falsy_env_var_values_stay_false(self, monkeypatch):
        """Review-caught gap: only unset/"1" were ever exercised -- must
        confirm explicit falsy strings ("0"/"false"/"off"/"") don't
        accidentally parse as truthy."""
        import weather_markets as wm

        monkeypatch.setattr("tracker.count_settled_snow_predictions", lambda: 999)
        for falsy in ("0", "false", "off", ""):
            monkeypatch.setenv("SNOW_TRADING_ENABLED", falsy)
            assert wm._snow_gates_active() is False, f"{falsy!r} must not be truthy"

    def test_truthy_env_var_values_case_insensitive(self, monkeypatch):
        """Mirrors the falsy check above -- confirms the accepted truthy
        set really is case-insensitive, not just literal '1'."""
        import weather_markets as wm

        monkeypatch.setattr("tracker.count_settled_snow_predictions", lambda: 20)
        for truthy in ("1", "true", "TRUE", "yes", "Yes"):
            monkeypatch.setenv("SNOW_TRADING_ENABLED", truthy)
            assert wm._snow_gates_active() is True, f"{truthy!r} must be truthy"


class TestCheckPositionLimitsSnowConditional:
    """backlog.txt Snow Step 2: the Step 1 unconditional block became
    conditional on _snow_gates_active() -- must still block when the gate
    is inactive, and must NOT block once the gate fires, mutation-tested
    to prove the conditional is real."""

    def test_still_blocks_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits("KXDENSNOWM-26DEC-5.0", qty=1, price=0.10)
        assert result["ok"] is False
        assert "snow" in result["reason"].lower()

    def test_does_not_block_when_gate_active(self, monkeypatch, tmp_path):
        """Mutation-test proof: flipping _snow_gates_active() to True makes
        the block disappear -- confirms the conditional is real, not a
        hardcoded string check that always fires regardless.

        Review-caught: without isolating paper's account state (DATA_PATH/
        get_open_trades/get_total_exposure), this test falls through past
        the snow gate into the REAL exposure-cap checks against this
        machine's actual paper_trades.json, making it state-dependent and
        occasionally flaky (a large enough real exposure could legitimately
        return ok=False for reasons unrelated to the snow gate at all).
        Mirrors test_daily_ticker_unaffected's isolation below."""
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
                    monkeypatch.setattr(
                        "weather_markets._snow_gates_active", lambda: True
                    )
                    result = paper.check_position_limits(
                        "KXDENSNOWM-26DEC-5.0", qty=1, price=0.10
                    )
        assert result["ok"] is True

    def test_blocks_even_when_city_and_date_are_present(self, monkeypatch):
        import paper

        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)
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


class TestCmdOrderSnowGuard:
    """backlog.txt Snow Step 2: main.py's cmd_order kept its own explicit
    refuse-outright guard (defense-in-depth against check_position_limits
    failing open on an exception), now conditional on _snow_gates_active()
    instead of unconditional."""

    def test_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)
        main.cmd_order(None, "buy", ["KXDENSNOWM-26DEC-5.0", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        # Review-caught gap: cmd_order's hurricane guard prints the same
        # "refusing to place this order" phrase -- assert specifically on
        # the snow-guard's own text so this can't pass via a misrouted
        # hurricane-guard hit.
        assert "refusing to place this order" in out
        assert "snow" in out.lower()
        assert "SNOW_TRADING_ENABLED" in out

    def test_does_not_refuse_when_gate_active(self, monkeypatch):
        """Mutation-test proof the conditional is real -- once
        _snow_gates_active() is True, cmd_order must proceed past this
        specific guard (it may still be stopped by something else further
        down, e.g. a live market fetch failure in this unit-test context --
        the point is only that THIS guard specifically doesn't fire)."""
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._snow_gates_active", lambda: True)
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_order(None, "buy", ["KXDENSNOWM-26DEC-5.0", "yes", "1", "0.10"])
        except Exception:
            pass  # downstream failure (no live market) is expected/irrelevant here
        assert not any("discovery-only" in p or "shadow-only" in p for p in printed)


class TestQuickPaperBuyAndCmdPaperSnowGuards:
    """Opus-review-caught gap (round 2): _quick_paper_buy() and cmd_paper()
    got the same hurricane-unconditional + snow-conditional-on-
    _snow_gates_active() guards cmd_order() already had (round-1 fix,
    since check_position_limits()'s own exception path deliberately fails
    open, and _quick_paper_buy specifically can place a REAL live maker
    order) -- but had zero test coverage of their own. Mirrors
    TestCmdOrderSnowGuard's assertions for both new call sites."""

    def test_quick_paper_buy_refuses_snow_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)
        mock_client = MagicMock()
        _inputs = iter(["KXDENSNOWM-26DEC-5.0"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "snow" in out.lower()
        assert "SNOW_TRADING_ENABLED" in out
        mock_client.get_market.assert_not_called()  # returned before any further work

    def test_quick_paper_buy_refuses_hurricane_unconditionally(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        mock_client = MagicMock()
        _inputs = iter(["KXHURCAT-26FAUSTO-T5"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "hurricane" in out.lower()

    def test_quick_paper_buy_does_not_refuse_snow_when_gate_active(self, monkeypatch):
        """Mutation-test proof: proceeds past THIS guard once the gate is
        active (may still stop later for unrelated reasons in this
        unit-test context, e.g. no real market to fetch)."""
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._snow_gates_active", lambda: True)
        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("no real market in test")
        _inputs = iter(["KXDENSNOWM-26DEC-5.0", "q"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main._quick_paper_buy(mock_client)
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)

    def test_cmd_paper_refuses_snow_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("SNOW_TRADING_ENABLED", raising=False)

        main.cmd_paper(["buy", "KXDENSNOWM-26DEC-5.0", "yes", "0.10", "1"])

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "snow" in out.lower()
        assert "SNOW_TRADING_ENABLED" in out

    def test_cmd_paper_refuses_hurricane_unconditionally(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)

        main.cmd_paper(["buy", "KXHURCAT-26FAUSTO-T5", "yes", "0.10", "1"])

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "hurricane" in out.lower()

    def test_cmd_paper_does_not_refuse_snow_when_gate_active(self, monkeypatch):
        """Mutation-test proof: proceeds past THIS guard once the gate is
        active."""
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._snow_gates_active", lambda: True)

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_paper(["buy", "KXDENSNOWM-26DEC-5.0", "yes", "0.10", "1"])
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)


class TestAuditSettlementMonthlySnow:
    """backlog.txt Snow Step 2: audit_settlement()'s new snow branch reads
    Kalshi's own expiration_value once status='finalized' -- mirrors rain's
    identical settlement path exactly."""

    def test_finalized_writes_settled_value_not_settled_var(self, monkeypatch):
        import tracker

        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXDENSNOWM-26DEC-5", 1),
            )

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "6.2"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        result = tracker.audit_settlement("KXDENSNOWM-26DEC-5", settled_yes=True)
        assert result is True
        with tracker._conn() as con:
            row = con.execute(
                "SELECT settled_value, settled_var FROM outcomes WHERE ticker=?",
                ("KXDENSNOWM-26DEC-5",),
            ).fetchone()
        assert row["settled_value"] == 6.2
        assert row["settled_var"] is None

    def test_not_finalized_returns_false_no_write(self, monkeypatch):
        import tracker

        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXDENSNOWM-26DEC-10", 0),
            )

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "active", "expiration_value": "6.2"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        result = tracker.audit_settlement("KXDENSNOWM-26DEC-10", settled_yes=True)
        assert result is False
        with tracker._conn() as con:
            row = con.execute(
                "SELECT settled_value FROM outcomes WHERE ticker=?",
                ("KXDENSNOWM-26DEC-10",),
            ).fetchone()
        assert row["settled_value"] is None

    def test_missing_expiration_value_returns_false(self, monkeypatch, caplog):
        import logging

        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": None}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        with caplog.at_level(logging.WARNING):
            result = tracker.audit_settlement("KXDENSNOWM-26DEC-15", settled_yes=True)
        assert result is False
        # Pins that the snow branch itself fired (not e.g. a fallthrough to
        # the generic city/date early-return, which also returns False but
        # logs nothing).
        assert any(
            "finalized but no expiration_value" in r.message for r in caplog.records
        )

    def test_non_numeric_expiration_value_returns_false(self, monkeypatch, caplog):
        import logging

        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "not-a-number"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        with caplog.at_level(logging.WARNING):
            result = tracker.audit_settlement("KXDENSNOWM-26DEC-20", settled_yes=True)
        assert result is False
        assert any("non-numeric expiration_value" in r.message for r in caplog.records)

    def test_fetch_exception_returns_false_not_raise(self, monkeypatch, caplog):
        import logging

        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                raise RuntimeError("network down")

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        with caplog.at_level(logging.WARNING):
            result = tracker.audit_settlement("KXDENSNOWM-26DEC-25", settled_yes=True)
        assert result is False
        assert any("snow market fetch failed" in r.message for r in caplog.records)

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
        result = tracker.audit_settlement("KXDENSNOWM-26DEC-NOROW", settled_yes=True)
        assert result is False

    def test_snow_branch_reached_before_parse_city_date_early_return(self, monkeypatch):
        """The real regression this fix targets: parse_city_date() returns
        (city, None) for these tickers, which would hit the generic early
        return before the hourly-style branch further down is ever reached.
        Confirm the snow branch fires without ever calling parse_city_date."""
        import tracker

        called = []
        monkeypatch.setattr(
            "weather_markets.parse_city_date",
            lambda m: (called.append(m) or ("Denver", None)),
        )

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "1.0"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXDENSNOWM-26DEC-30", 1),
            )
        result = tracker.audit_settlement("KXDENSNOWM-26DEC-30", settled_yes=True)
        assert result is True
        assert called == [], "parse_city_date must never be called for a snow ticker"

    def test_rain_and_snow_registries_are_prefix_disjoint(self):
        """Real regression-control invariant: _KXRAIN_MONTHLY_CITY and
        _KXSNOW_MONTHLY_CITY prefixes must never overlap or prefix-shadow
        each other -- opus review noted the two registries' current keys
        happen to be disjoint (neither is a prefix of the other), so no
        plausible mutation of the settlement code alone can make a rain
        ticker reach the snow branch or vice versa. This test pins that
        registry-level invariant directly, rather than relying on the
        settlement smoke test below to catch a future registry collision."""
        import weather_markets as wm

        rain_prefixes = tuple(wm._KXRAIN_MONTHLY_CITY)
        snow_prefixes = tuple(wm._KXSNOW_MONTHLY_CITY)
        for r in rain_prefixes:
            for s in snow_prefixes:
                assert not r.startswith(s) and not s.startswith(r), (
                    f"rain prefix {r!r} and snow prefix {s!r} overlap -- "
                    "a ticker could ambiguously match both settlement branches"
                )

    def test_rain_settlement_still_works_alongside_snow_branch(self, monkeypatch):
        """Settlement smoke test: a rain ticker still takes the rain branch
        (checked first in source order) and settles correctly with the
        snow branch present right after it in the same function."""
        import tracker

        class _FakeClient:
            def get_market(self, ticker):
                return {"status": "finalized", "expiration_value": "3.3"}

        monkeypatch.setattr(
            "tracker._get_settlement_kalshi_client", lambda: _FakeClient()
        )
        tracker.init_db()
        with tracker._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at) "
                "VALUES (?, ?, datetime('now'))",
                ("KXRAINDENM-26AUG-3", 1),
            )
        result = tracker.audit_settlement("KXRAINDENM-26AUG-3", settled_yes=True)
        assert result is True
        with tracker._conn() as con:
            row = con.execute(
                "SELECT settled_value FROM outcomes WHERE ticker=?",
                ("KXRAINDENM-26AUG-3",),
            ).fetchone()
        assert row["settled_value"] == 3.3


class TestAnalyzeMonthlySnowTradeEndToEnd:
    """backlog.txt Snow Step 2: the real bootstrap model, exercised end-to-
    end with mocked ACIS/Open-Meteo calls (no live network) -- proves the
    full analyze_trade() -> _analyze_monthly_snow_trade() wiring produces a
    real, well-shaped result. Mirrors test_rain_markets.py's identical
    end-to-end test class via acis_snow instead of acis_precip."""

    def _history_all_years_value(self, value, years=20, month=12, days_in_month=31):
        return {
            2000 + y: {month * 100 + d: value for d in range(1, days_in_month + 1)}
            for y in range(years)
        }

    def test_full_pipeline_produces_real_result(self, monkeypatch):
        import weather_markets as wm

        frozen_now = datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
        m = _snow_market(
            ticker="KXDENSNOWM-26DEC-5.0",
            floor_strike=5.0,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 12, 2, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        # 20 years, every year totalling 1.0*31=31.0in for the full month --
        # a market with a 5in threshold should come back near-certain YES.
        history = self._history_all_years_value(1.0, years=20)

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow", lambda sid: history
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        result = wm.analyze_trade(m)
        assert result is not None
        assert result["condition"]["type"] == "snow_month_total"
        assert result["method"] in (
            "monthly_snow_bootstrap",
            "monthly_snow_bootstrap_tilted",
        )
        assert result["forecast_prob"] > 0.9  # every historical year exceeded 5in
        assert result["consensus"] is False  # hardcoded, never computed
        assert result["n_historical_years"] == 20
        assert result["accrual_month"] == "2026-12"
        assert result["blend_sources"] == {"acis_snow_empirical": 1.0}
        # Exposure-cap decision: target_date is the close_time date, not the
        # accrual month.
        assert result["target_date"] != "2026-12-01"

    def test_bias_correction_keyed_on_close_dt_month_not_accrual_month(
        self, monkeypatch
    ):
        """Mirrors rain's identical resolved decision: get_quintile_bias
        must be called with close_dt.month, not the ticker's accrual
        month. A hardcoded close_dt of July, against a December-accrual
        ticker, guarantees the two can never coincidentally match."""
        import weather_markets as wm

        ticker = "KXDENSNOWM-26DEC-5"
        enriched = {
            "ticker": ticker,
            "title": "Snow in Denver in Dec 2026?",
            "_city": "Denver",
        }
        condition = {"type": "snow_month_total", "threshold": 5.0}
        coords = wm.CITY_COORDS["Denver"]
        close_dt = datetime(2026, 7, 15, tzinfo=UTC)
        history = self._history_all_years_value(1.0, years=20)

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow", lambda sid: history
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        calls = []
        monkeypatch.setattr(
            "tracker.get_quintile_bias",
            lambda city, month, prob, condition_type=None: (
                calls.append((city, month)) or 0.0
            ),
        )

        result = wm._analyze_monthly_snow_trade(
            enriched, condition, "Denver", coords, close_dt, days_out=10
        )
        assert result is not None
        assert len(calls) == 1
        called_city, called_month = calls[0]
        assert called_city == "Denver"
        assert called_month == 7, (
            f"expected close_dt.month (7, July) to be passed, got {called_month} "
            f"-- if this is 12 (December), the accrual month leaked in instead"
        )

    def test_seasonal_tilt_applied_reaches_full_pipeline_with_cm_to_mm_conversion(
        self, monkeypatch
    ):
        """Real regression for the cm->mm conversion this call site owns:
        Open-Meteo's snowfall_mean is in cm, not mm like rain's
        precipitation_mean -- passing the raw cm value into
        apply_seasonal_tilt (which expects mm) would silently be wrong by
        10x. A seasonal_mean_cm of 500 (50cm) is deliberately far above the
        historical baseline (mean ~31in*25.4=787mm) so the tilt's ratio
        clamp only saturates in one specific, verifiable direction if the
        raw cm value leaked in unconverted -- 500mm (unconverted) vs
        5000mm (correctly converted from 500cm) against a clim mean of
        787mm produces opposite-direction clamp outcomes, making a missed
        x10 conversion detectable by the tilt's sign/magnitude rather than
        merely by tilt_applied being True either way."""
        import weather_markets as wm

        m = _snow_market(
            ticker="KXDENSNOWM-26DEC-5.0",
            floor_strike=5.0,
            close_hours_from_now=5 * 24,
        )
        m["_city"] = "Denver"
        history = {
            2000 + y: {1200 + d: 1.0 + (y % 3) * 0.5 for d in range(1, 32)}
            for y in range(20)
        }

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow", lambda sid: history
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: 500.0,
        )

        captured = {}
        import acis_snow as _acis_snow_mod

        real_apply_seasonal_tilt = _acis_snow_mod.apply_seasonal_tilt

        def _spy_apply_seasonal_tilt(
            remaining_sums, full_month_sums, seasonal_mean_mm, *a, **k
        ):
            captured["seasonal_mean_mm"] = seasonal_mean_mm
            return real_apply_seasonal_tilt(
                remaining_sums, full_month_sums, seasonal_mean_mm, *a, **k
            )

        monkeypatch.setattr("acis_snow.apply_seasonal_tilt", _spy_apply_seasonal_tilt)

        result = wm.analyze_trade(m)
        assert result is not None
        assert result["seasonal_tilt_applied"] is True
        assert result["method"] == "monthly_snow_bootstrap_tilted"
        # 500cm -> 5000mm, not 500mm -- proves the call site's x10 conversion
        # actually ran rather than passing the raw cm value straight through.
        assert captured["seasonal_mean_mm"] == 5000.0

    def test_too_few_historical_years_returns_none(self, monkeypatch):
        import weather_markets as wm

        m = _snow_market(ticker="KXDENSNOWM-26DEC-5.0", floor_strike=5.0)
        m["_city"] = "Denver"
        thin_history = self._history_all_years_value(1.0, years=5)  # < 15

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow", lambda sid: thin_history
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is None

    def test_no_historical_data_returns_none(self, monkeypatch):
        import weather_markets as wm

        m = _snow_market(ticker="KXDENSNOWM-26DEC-5.0", floor_strike=5.0)
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr("acis_snow.fetch_historical_daily_snow", lambda sid: None)

        assert wm.analyze_trade(m) is None

    def test_unmapped_city_station_returns_none(self, monkeypatch):
        import weather_markets as wm

        m = _snow_market(ticker="KXDENSNOWM-26DEC-5.0", floor_strike=5.0)
        m["_city"] = "Denver"
        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: None)

        assert wm.analyze_trade(m) is None

    def test_month_to_date_fetch_failure_fails_closed_not_zero(self, monkeypatch):
        """fetch_month_to_date_actual_snow() returns (None, 0) both when
        nothing has accrued yet (through_day < 1, legitimate 0.0) and on a
        genuine fetch failure (through_day >= 1). Must fail closed (no
        trade), not silently coerce to 0.0.

        "Today" must be pinned INSIDE the ticker's Dec accrual window --
        otherwise (whenever the suite runs outside December) this would
        take the "before month starts" branch, which never calls
        fetch_month_to_date_actual_snow at all, making the mock below
        never exercised and the test vacuously pass for the wrong reason."""
        import weather_markets as wm

        frozen_now = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 12, 10, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 12, 10, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        m = _snow_market(
            ticker="KXDENSNOWM-26DEC-5.0",
            floor_strike=5.0,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (None, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is None

    def test_month_to_date_any_missing_day_fails_closed(self, monkeypatch):
        """Opus-review-caught HIGH finding: fetch_month_to_date_actual_snow
        returns (sum, n_missing) -- a fetch that comes back present but
        with any "M" (missing) sentinel days must not silently understate
        month_to_date_actual with zero guard. Reproduced live against real
        cached Denver history: the entire month's snow was concentrated in
        2 of 31 days -- only 6.5% missing, comfortably under a naive 20%
        fractional threshold, yet enough to flip a STRONG "no"
        recommendation to what should be "yes". Round-2 review caught that
        a fractional threshold is the wrong statistic for a value added
        1:1 into every bootstrap sample (unlike the historical path's
        30-year dilution) -- the real guard is zero-tolerance: even ONE
        missing day-to-date must refuse to trade."""
        import weather_markets as wm

        frozen_now = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 12, 31, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 12, 31, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        m = _snow_market(
            ticker="KXDENSNOWM-26DEC-5.0",
            floor_strike=5.0,
            close_hours_from_now=1 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        # through_day=30 (Dec 31 - 1), only 1 of 30 days missing -- must
        # still refuse under zero-tolerance, even though a real (non-None)
        # sum came back and the fraction (3.3%) is small.
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.5, 1),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is None

    def test_month_to_date_zero_missing_still_trades(self, monkeypatch):
        """Control for the guard above: zero missing days must NOT be
        refused -- confirms the guard doesn't over-trigger on ordinary,
        fully-complete data."""
        import weather_markets as wm

        frozen_now = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 12, 10, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 12, 10, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        m = _snow_market(
            ticker="KXDENSNOWM-26DEC-5.0",
            floor_strike=5.0,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        # through_day=9 (Dec 10 - 1), 0 days missing -- fully complete
        # data, must not be refused under zero-tolerance.
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (2.0, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        assert wm.analyze_trade(m) is not None

    def test_after_month_end_mostly_missing_fails_closed(self, monkeypatch):
        """Opus-review-caught HIGH finding, exact reproduction scenario:
        the ticket is analyzed after its accrual month has ended but
        before the market closes/finalizes ("today" = Jan 1, market
        closes Jan 2, accrual month = December) -- the OTHER month-to-date
        branch (remaining_start_day = days_in_month + 1), not the in-month
        "else" branch the tests above already cover. Calls
        _analyze_monthly_snow_trade() directly with an explicit close_dt,
        mirroring test_ticket_checked_after_month_end_does_not_crash's
        rain-side precedent, to avoid a wall-clock race between this
        test's frozen "now" and analyze_trade()'s independently-derived
        close_time."""
        import weather_markets as wm

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2027, 1, 1, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)
        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        # through_day=31 (full December), 29 of 31 days missing -- far
        # above the 20% threshold.
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.5, 29),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow",
            lambda sid: self._history_all_years_value(1.0, years=20),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        enriched = {
            "ticker": "KXDENSNOWM-26DEC-5.0",
            "title": "Snow in Denver in Dec 2026?",
            "_city": "Denver",
        }
        condition = {"type": "snow_month_total", "threshold": 5.0}
        coords = wm.CITY_COORDS["Denver"]
        close_dt = datetime(2027, 1, 2, tzinfo=UTC)

        result = wm._analyze_monthly_snow_trade(
            enriched, condition, "Denver", coords, close_dt, days_out=1
        )
        assert result is None

    def test_exact_threshold_total_not_counted_as_exceeding(self, monkeypatch):
        """Opus-review-caught gap: the exceedance comparison (`t > threshold`)
        is strict, not `>=` -- real Denver history has years whose December
        total lands exactly on an integer (e.g. 12.0, 4.0, 7.0, 13.0), so
        this off-by-one direction is not a hypothetical edge case. A
        fabricated year whose total equals the threshold exactly must NOT
        count toward exceedance."""
        import weather_markets as wm

        frozen_now = datetime(2026, 12, 2, 12, 0, tzinfo=UTC)

        class _FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    datetime(2026, 12, 2, 12, 0, tzinfo=tz)
                    if tz
                    else datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
                )

        monkeypatch.setattr("weather_markets.datetime", _FakeDT)

        m = _snow_market(
            ticker="KXDENSNOWM-26DEC-5.0",
            floor_strike=5.0,
            close_hours_from_now=5 * 24,
            now=frozen_now,
        )
        m["_city"] = "Denver"

        # Every one of 20 years totals EXACTLY 5.0 over the remaining days
        # (threshold == 5.0) -- if the comparison were `>=`, forecast_prob
        # would be ~0.99 (clamped); with the correct strict `>`, it must be
        # the 0.01 floor (zero years strictly exceed).
        history = {
            2000 + y: {1200 + d: 5.0 / 30 for d in range(1, 32)} for y in range(20)
        }

        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")
        monkeypatch.setattr(
            "acis_snow.fetch_month_to_date_actual_snow",
            lambda sid, year, month, through_day: (0.0, 0),
        )
        monkeypatch.setattr(
            "acis_snow.fetch_historical_daily_snow", lambda sid: history
        )
        monkeypatch.setattr(
            "acis_snow.fetch_seasonal_snow_mean_cm",
            lambda lat, lon, tz, year, month: None,
        )

        result = wm.analyze_trade(m)
        assert result is not None
        assert result["forecast_prob"] == pytest.approx(0.01), (
            "an exact-threshold total must not count as exceeding it -- "
            f"got forecast_prob={result['forecast_prob']}, which would only "
            "happen if the comparison were >= instead of >"
        )

    def test_unparseable_ticker_month_returns_none(self, monkeypatch, caplog):
        """Opus-review-caught gap: asserting only `is None` would also pass
        if the market were rejected earlier at an unrelated gate (condition
        parse, liquidity, etc.) -- assert the specific log line this
        function's own failure path emits, pinning that THIS is actually
        what rejected it."""
        import logging

        import weather_markets as wm

        m = _snow_market(ticker="KXDENSNOWM-badformat", floor_strike=5.0)
        m["_city"] = "Denver"
        monkeypatch.setattr("acis_snow._station_sid_for_city", lambda city: "DEN")

        with caplog.at_level(logging.WARNING):
            result = wm.analyze_trade(m)
        assert result is None
        assert any(
            "could not parse accrual month from ticker" in r.message
            for r in caplog.records
        )


class TestFetchHistoricalDailySnowEmptyResponse:
    """Opus-review-caught gap (round 2, identical to acis_precip.py's
    cloned bug): ACIS can return HTTP 200 with an empty "data" array --
    this parses to result={}, which is not None, so it silently bypasses
    the existing fail-open _load_stale_cache_or_none path and gets
    written to disk as the 30-day cache AND the process-lifetime
    mem-cache from one transient response."""

    def test_empty_data_falls_back_to_stale_cache_not_written_as_empty(
        self, tmp_path, monkeypatch
    ):
        import json as _json
        import os
        import time as _time

        import acis_snow

        monkeypatch.setattr(acis_snow, "DATA_DIR", tmp_path)
        monkeypatch.setattr(acis_snow, "_MEM_CACHE", {})
        sid = "TESTEMPTYSNOW"
        cache_path = tmp_path / f"acis_snow_{sid}.json"
        cache_path.write_text('{"2020": {"1201": 4.3}}')
        old_time = _time.time() - acis_snow.CACHE_MAX_AGE - 1
        os.utime(cache_path, (old_time, old_time))

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": [], "error": "no data available"}
        fake_resp.raise_for_status.return_value = None
        with patch("acis_snow._session.post", return_value=fake_resp):
            result = acis_snow.fetch_historical_daily_snow(sid, years=5, force=True)

        assert result == {2020: {1201: 4.3}}, (
            "an empty live ACIS response must fall back to the stale cache, "
            "not overwrite it with an empty dict"
        )
        on_disk = _json.loads(cache_path.read_text())
        assert on_disk == {"2020": {"1201": 4.3}}
        assert acis_snow._MEM_CACHE.get(sid) != {}


class TestAcisSnowModule:
    """Unit tests for acis_snow.py's own sentinel-parsing and cache-key
    isolation from acis_precip.py -- the two design decisions this module
    exists specifically to get right (2026-07-30)."""

    def test_parse_snow_value_trace_sentinel(self):
        import acis_snow

        assert acis_snow._parse_snow_value("T") == 0.0

    def test_parse_snow_value_missing_sentinel(self):
        import acis_snow

        assert acis_snow._parse_snow_value("M") is None
        assert acis_snow._parse_snow_value("") is None

    def test_parse_snow_value_accumulated_sentinel(self):
        import acis_snow

        assert acis_snow._parse_snow_value("S") is None

    def test_parse_snow_value_numeric(self):
        import acis_snow

        assert acis_snow._parse_snow_value("4.3") == 4.3
        assert acis_snow._parse_snow_value(2.1) == 2.1

    def test_parse_snow_value_unparseable_returns_none(self):
        import acis_snow

        assert acis_snow._parse_snow_value("garbage") is None
        assert acis_snow._parse_snow_value(None) is None

    def test_seasonal_cache_is_isolated_from_precip(self, monkeypatch):
        """Real regression: both modules cache on the same (lat, lon, tz,
        year, month) key shape -- if they shared one ForecastCache
        instance, a precip lookup and a snow lookup for the same city/month
        would silently collide. Confirms they're genuinely separate
        objects, not aliases of one shared cache."""
        import acis_precip
        import acis_snow

        assert acis_snow._seasonal_cache is not acis_precip._seasonal_cache

        key = (39.7392, -104.9903, "America/Denver", 2026, 12)
        acis_precip._seasonal_cache.set(key, 111.0)
        acis_snow._seasonal_cache.set(key, 222.0)

        precip_val, precip_hit, _ = acis_precip._seasonal_cache.get_with_ts(key)
        snow_val, snow_hit, _ = acis_snow._seasonal_cache.get_with_ts(key)
        assert precip_hit and precip_val == 111.0
        assert snow_hit and snow_val == 222.0

    def test_circuit_breakers_are_isolated_from_precip(self):
        import acis_precip
        import acis_snow

        assert acis_snow._acis_snow_cb is not acis_precip._acis_cb
        assert acis_snow._acis_snow_cb.name != acis_precip._acis_cb.name
        assert acis_snow._om_seasonal_snow_cb is not acis_precip._om_seasonal_cb

    def test_cache_path_is_distinct_from_precip(self):
        import acis_precip
        import acis_snow

        assert acis_snow._cache_path("DEN") != acis_precip._cache_path("DEN")
        assert "snow" in acis_snow._cache_path("DEN").name
        assert "pcpn" in acis_precip._cache_path("DEN").name

    def test_math_functions_are_the_same_imported_objects_not_copies(self):
        """Confirms the user-confirmed design decision actually landed:
        acis_snow reuses acis_precip's bootstrap/tilt math by import, it
        does not duplicate the logic."""
        import acis_precip
        import acis_snow

        assert (
            acis_snow.historical_remaining_and_full_month_sums
            is acis_precip.historical_remaining_and_full_month_sums
        )
        assert (
            acis_snow.bootstrap_ci_month_total is acis_precip.bootstrap_ci_month_total
        )
        assert acis_snow.apply_seasonal_tilt is acis_precip.apply_seasonal_tilt


class TestFetchSeasonalSnowMeanCmUnitValidation:
    """Opus-review-caught gap: the "cm, not mm" claim was inferred from one
    value being merely plausible as cm, never validated against what the
    API actually reports. fetch_seasonal_snow_mean_cm must check the
    response's own monthly_units field and refuse the value (not silently
    mis-tilt the bootstrap by 10x) if Open-Meteo ever changes it."""

    def _mock_response(self, monkeypatch, unit, value=15.82):
        import acis_snow

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "monthly_units": {"time": "iso8601", "snowfall_mean": unit},
                    "monthly": {
                        "time": ["2026-11-30"],
                        "snowfall_mean": [value],
                    },
                }

        monkeypatch.setattr("acis_snow._session.get", lambda *a, **kw: _FakeResp())
        acis_snow._seasonal_cache._store.clear()

    def test_correct_cm_unit_returns_value(self, monkeypatch):
        import acis_snow

        self._mock_response(monkeypatch, "cm")
        result = acis_snow.fetch_seasonal_snow_mean_cm(
            39.7392, -104.9903, "America/Denver", 2026, 11
        )
        assert result == pytest.approx(15.82)

    def test_unexpected_unit_refuses_value(self, monkeypatch, caplog):
        """If Open-Meteo ever reports mm (or anything else) instead of cm,
        this must fail closed and log loudly, not silently return the raw
        value for the caller to mis-convert by 10x."""
        import logging

        import acis_snow

        self._mock_response(monkeypatch, "mm")
        with caplog.at_level(logging.WARNING):
            result = acis_snow.fetch_seasonal_snow_mean_cm(
                39.7392, -104.9903, "America/Denver", 2026, 11
            )
        assert result is None
        assert any("refusing to use this value" in r.message for r in caplog.records)

    def test_unexpected_unit_refusal_is_cached_not_refetched(self, monkeypatch):
        """Opus-review-caught gap (round 2): the refusal path calls
        _seasonal_cache.set(cache_key, None), matching every other None
        result this function caches -- but nothing proved it actually
        works. A second call for the same (lat, lon, tz, year, month) must
        hit the cache, not re-fetch and re-refuse."""
        import acis_snow

        call_count = {"n": 0}

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                call_count["n"] += 1
                return {
                    "monthly_units": {"time": "iso8601", "snowfall_mean": "mm"},
                    "monthly": {"time": ["2026-11-30"], "snowfall_mean": [15.82]},
                }

        monkeypatch.setattr("acis_snow._session.get", lambda *a, **kw: _FakeResp())
        acis_snow._seasonal_cache._store.clear()

        first = acis_snow.fetch_seasonal_snow_mean_cm(
            39.7392, -104.9903, "America/Denver", 2026, 11
        )
        second = acis_snow.fetch_seasonal_snow_mean_cm(
            39.7392, -104.9903, "America/Denver", 2026, 11
        )
        assert first is None
        assert second is None
        assert call_count["n"] == 1, (
            "the second call should have hit the cache, not re-fetched -- "
            f"got {call_count['n']} real fetches"
        )

    def test_missing_units_field_does_not_crash(self, monkeypatch, caplog):
        """Older/degraded responses without monthly_units at all must not
        crash -- opus-review-caught (L-1, this test predates the fix and
        wasn't updated when it landed): the unit check now fails CLOSED on
        a MISSING field too, not just an explicit mismatch (acis_snow.py's
        own comment: "`is not None and !=` used to treat an absent
        monthly_units key the same as a confirmed 'cm', defeating this
        guard's own purpose"). This test's real, still-valid intent (per
        its own name) is "does not crash", not "returns the raw value" --
        a missing field must refuse gracefully (None + a warning), the
        same shape test_unexpected_unit_refuses_value already proves for
        an explicit mismatch."""
        import logging

        import acis_snow

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"monthly": {"time": ["2026-11-30"], "snowfall_mean": [15.82]}}

        monkeypatch.setattr("acis_snow._session.get", lambda *a, **kw: _FakeResp())
        acis_snow._seasonal_cache._store.clear()
        with caplog.at_level(logging.WARNING):
            result = acis_snow.fetch_seasonal_snow_mean_cm(
                39.7392, -104.9903, "America/Denver", 2026, 11
            )
        assert result is None
        assert any("refusing to use this value" in r.message for r in caplog.records)


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


class TestComputeMarketImpliedExcludesMonthlySnow:
    """compute_market_implied_distributions() groups by (city, target_date,
    var) independently of analyze_trade() -- this exclusion was already prefix-
    based (not model-existence-based) at Step 1, so it needs no changes for
    Step 2, but must keep working now that snow tickers carry real target
    values downstream."""

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

        assert fit_daily_only[("NYC", "2026-07-20", "max")] is not None
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

        # Prefix-matched, not exact-key-matched: the temperature key is a
        # 3-tuple now, so asserting the old 2-tuple's absence would pass
        # vacuously no matter what the snow market did.
        assert not [k for k in result if k[:2] == ("Denver", "2026-12-01")], (
            "snow market reached event-grouping despite a now-parseable date -- "
            "the explicit prefix exclusion isn't doing real work"
        )
        # Positive control: the daily ladder DID reach grouping in this same
        # call, so the assertion above is about the snow market's exclusion and
        # not about compute_market_implied_distributions() returning nothing.
        assert ("NYC", "2026-07-20", "max") in result


class TestGroupMarketsExcludesMonthlySnow:
    def test_snow_market_excluded_no_warning(self, caplog):
        import logging

        import consistency

        with caplog.at_level(logging.WARNING):
            groups = consistency._group_markets([_snow_market()])
        assert groups == {}
        assert not any("date" in r.message.lower() for r in caplog.records)
