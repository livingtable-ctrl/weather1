"""
Tests for backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" (KXTEMPxxxH).
Step 1 (schema + safe discovery) and Step 2 (real per-hour probability
model, gated to cached target hours) -- see
C:\\Users\\thesa\\.claude\\plans\\sunny-herding-cocoa.md for the Step 2 plan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAnalyzeTradeHourlyGuard:
    """analyze_trade() must return None immediately for KXTEMPxxxH tickers at
    a non-target hour (before condition parsing), and must not affect
    existing daily/precip/snow tickers. Every test here explicitly isolates
    HOURLY_TARGET_HOURS_PATH to an empty tmp cache so behavior doesn't
    depend on whatever the real data/hourly_target_hours.json happens to
    contain on this machine."""

    def _analyze(self, ticker: str, tmp_path, monkeypatch) -> dict | None:
        import weather_markets as wm

        monkeypatch.setattr(
            wm, "HOURLY_TARGET_HOURS_PATH", tmp_path / "hourly_target_hours.json"
        )
        return wm.analyze_trade({"ticker": ticker})

    def test_nyc_hourly_ticker_returns_none(self, tmp_path, monkeypatch):
        assert (
            self._analyze("KXTEMPNYCH-26JUL2008-T71.99", tmp_path, monkeypatch) is None
        )

    def test_austin_hourly_ticker_returns_none(self, tmp_path, monkeypatch):
        assert (
            self._analyze("KXTEMPAUSH-26JUL2008-T78.99", tmp_path, monkeypatch) is None
        )

    def test_chicago_hourly_ticker_returns_none(self, tmp_path, monkeypatch):
        assert (
            self._analyze("KXTEMPCHIH-26JUL2008-T85.99", tmp_path, monkeypatch) is None
        )

    def test_la_hourly_ticker_returns_none(self, tmp_path, monkeypatch):
        assert (
            self._analyze("KXTEMPLAXH-26JUL2008-T77.99", tmp_path, monkeypatch) is None
        )

    def test_dc_hourly_ticker_returns_none(self, tmp_path, monkeypatch):
        assert (
            self._analyze("KXTEMPDCH-26JUL2008-T82.99", tmp_path, monkeypatch) is None
        )

    def test_hourly_gate_counted(self, tmp_path, monkeypatch):
        """The skip is counted via the existing _count_gate mechanism (same
        pattern every other analyze_trade gate uses), for scan-cycle
        visibility -- not a silent no-op. Gate name is "hourly_not_target_
        hour" (Step 2 -- narrower than Step 1's blanket "hourly_not_yet_
        supported": only fires for non-target hours now)."""
        import weather_markets as wm

        wm.reset_gate_counts()
        self._analyze("KXTEMPNYCH-26JUL2008-T71.99", tmp_path, monkeypatch)
        counts = wm.get_gate_counts()
        assert counts.get("hourly_not_target_hour") == 1

    def test_daily_ticker_unaffected_by_hourly_guard(self, tmp_path, monkeypatch):
        """Regression: an ordinary daily-market enriched dict that would
        otherwise pass every gate must still reach the real temperature
        analysis path -- the hourly guard must not fire for it and must not
        alter its behavior. Mirrors tests/test_p0_11_retired_strategy.py's
        _make_enriched fixture shape."""
        import datetime

        import weather_markets as wm

        monkeypatch.setattr(
            wm, "HOURLY_TARGET_HOURS_PATH", tmp_path / "hourly_target_hours.json"
        )
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
        assert counts.get("hourly_not_target_hour", 0) == 0


class TestAnalyzeTradeHourlyModel:
    """Step 2: the real per-hour probability model, reached only for a
    city's cached target hour. Every test isolates HOURLY_TARGET_HOURS_PATH
    and pins network-dependent sources (get_ensemble_temps, station bias,
    live observation) for deterministic assertions."""

    def _enriched(self, yes_bid_cents, yes_ask_cents, hour=14, threshold=75.99):
        import datetime

        target = datetime.date.today()
        ticker = (
            f"KXTEMPNYCH-{target.strftime('%y%b%d').upper()}{hour:02d}-T{threshold}"
        )
        close_time = (
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
        ).isoformat()
        return {
            "_city": "NYC",
            "_date": target,
            "_hour": hour,
            "_forecast": {"high_f": 78.0, "low_f": 60.0},
            "yes_bid": yes_bid_cents,
            "yes_ask": yes_ask_cents,
            "no_bid": 100 - yes_ask_cents,
            "volume": 5000,
            "open_interest": 1000,
            "ticker": ticker,
            "title": f"NYC temp above {threshold}F at {hour}:00",
            "series_ticker": "KXTEMPNYCH",
            "close_time": close_time,
        }

    def _cache_target_hour(self, tmp_path, monkeypatch, max_hour=14, min_hour=6):
        import weather_markets as wm

        cache_path = tmp_path / "hourly_target_hours.json"
        cache_path.write_text(
            json.dumps(
                {
                    "NYC": {
                        "date": "irrelevant-for-role-lookup",
                        "max_hour": max_hour,
                        "min_hour": min_hour,
                    }
                }
            )
        )
        monkeypatch.setattr(wm, "HOURLY_TARGET_HOURS_PATH", cache_path)

    def _pin_sources(self, monkeypatch, temps):
        import weather_markets as wm

        monkeypatch.setattr(wm, "get_ensemble_temps", lambda *a, **kw: temps)
        monkeypatch.setattr(wm, "_get_combined_station_bias", lambda *a, **kw: 0.0)
        from nws import get_live_observation as _real_get_live_obs  # noqa: F401

        monkeypatch.setattr(wm, "_get_live_obs", lambda *a, **kw: None, raising=False)

        # _compute_persistence_prob imports get_live_observation locally each
        # call -- patch the source module so that local import sees the stub.
        import nws

        monkeypatch.setattr(nws, "get_live_observation", lambda *a, **kw: None)

    def test_reaches_real_model_at_target_hour(self, tmp_path, monkeypatch):
        """A KXTEMP*H ticker at the cached max_hour must reach the real
        model (non-None result), not the hourly_not_target_hour gate."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(
            monkeypatch, temps=[64.0] * 14 + [66.0] * 6
        )  # well below T75.99 -> NO
        wm.reset_gate_counts()

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is not None
        assert wm.get_gate_counts().get("hourly_not_target_hour", 0) == 0
        assert result["condition"]["var"] == "max"
        assert result["method"].startswith("hourly_")

    def test_min_hour_gets_min_role(self, tmp_path, monkeypatch):
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch, max_hour=14, min_hour=6)
        self._pin_sources(monkeypatch, temps=[64.0] * 14 + [66.0] * 6)

        result = wm.analyze_trade(
            self._enriched(yes_bid_cents=22, yes_ask_cents=28, hour=6, threshold=60.99)
        )

        assert result is not None
        assert result["condition"]["var"] == "min"

    def test_recommends_no_when_ensemble_well_below_threshold(
        self, tmp_path, monkeypatch
    ):
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(
            monkeypatch, temps=[64.0] * 14 + [66.0] * 6
        )  # far below T75.99

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is not None
        assert result["recommended_side"] == "no"
        assert result["ensemble_prob"] < 0.1

    def test_recommends_yes_when_ensemble_well_above_threshold(
        self, tmp_path, monkeypatch
    ):
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(
            monkeypatch, temps=[84.0] * 14 + [86.0] * 6
        )  # far above T75.99

        result = wm.analyze_trade(self._enriched(yes_bid_cents=72, yes_ask_cents=78))

        assert result is not None
        assert result["recommended_side"] == "yes"
        assert result["ensemble_prob"] > 0.9

    def test_consensus_hardcoded_false_no_kelly_bonus(self, tmp_path, monkeypatch):
        """Caught in independent review: computing consensus as ensemble_prob
        vs blended_prob agreement would be near-tautological (blended is 85%
        ensemble_prob), granting _price_and_size()'s consensus Kelly bonus
        (x1.25, raised cap) to almost every hourly signal regardless of real
        independent confirmation. consensus must be hardcoded False until a
        genuinely independent second source exists for the hourly model."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        # Strongly one-sided ensemble -- exactly the case that would have
        # triggered the near-tautological consensus=True before the fix.
        self._pin_sources(monkeypatch, temps=[84.0] * 14 + [86.0] * 6)

        result = wm.analyze_trade(
            self._enriched(yes_bid_cents=72, yes_ask_cents=78, threshold=75.99)
        )

        assert result is not None
        assert result["consensus"] is False

    def test_thin_ensemble_gates_out(self, tmp_path, monkeypatch):
        """Fewer than 5 ensemble members must skip (hourly_thin_ensemble),
        not crash or fabricate a probability from a tiny/empty sample."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(monkeypatch, temps=[70.0, 71.0])
        wm.reset_gate_counts()

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is None
        assert wm.get_gate_counts().get("hourly_thin_ensemble") == 1

    def test_empty_ensemble_gates_out(self, tmp_path, monkeypatch):
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(monkeypatch, temps=[])
        wm.reset_gate_counts()

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is None
        assert wm.get_gate_counts().get("hourly_thin_ensemble") == 1

    def test_degenerate_ensemble_gates_out(self, tmp_path, monkeypatch):
        """All-identical members (>=10, so ensemble_stats runs) must be
        rejected as degenerate, not fed into EMOS/probability math."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(monkeypatch, temps=[70.0] * 15)
        wm.reset_gate_counts()

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is None
        assert wm.get_gate_counts().get("degenerate_ens") == 1

    def test_metar_lock_in_never_called_for_hourly(self, tmp_path, monkeypatch):
        """The exact contamination path found during plan review: _metar_
        lock_in()'s daily running-max/min shape must never be invoked for an
        hourly ticker that clears every gate."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(monkeypatch, temps=[64.0] * 14 + [66.0] * 6)
        calls = []
        monkeypatch.setattr(
            wm,
            "_metar_lock_in",
            lambda *a, **kw: calls.append((a, kw)) or (False, 0.0, {}),
        )

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is not None
        assert calls == [], "_metar_lock_in must never be called for an hourly ticker"

    def test_daily_path_still_calls_metar_lock_in(self, tmp_path, monkeypatch):
        """Companion regression: an ordinary daily ticker must still reach
        _metar_lock_in() as before -- confirms the skip above is hourly-
        specific, not an accidental blanket removal."""
        import datetime

        import weather_markets as wm

        monkeypatch.setattr(
            wm, "HOURLY_TARGET_HOURS_PATH", tmp_path / "hourly_target_hours.json"
        )
        calls = []
        monkeypatch.setattr(
            wm,
            "_metar_lock_in",
            lambda *a, **kw: calls.append((a, kw)) or (False, 0.0, {}),
        )
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        close_time = (
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=48)
        ).isoformat()
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
            "yes_bid": 40,
            "yes_ask": 45,
            "no_bid": 55,
            "volume": 5000,
            "open_interest": 1000,
            "close_time": close_time,
        }
        wm.analyze_trade(enriched)
        assert len(calls) == 1

    def test_liquidity_gate_still_applies_to_hourly(self, tmp_path, monkeypatch):
        """Gate-ordering regression from plan review: a target-hour hourly
        market with zero volume/OI must still return None via the existing
        liquidity gate, not reach the hourly model unchecked."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(monkeypatch, temps=[64.0] * 14 + [66.0] * 6)
        wm.reset_gate_counts()

        enriched = self._enriched(yes_bid_cents=22, yes_ask_cents=28)
        enriched["volume"] = 0
        enriched["open_interest"] = 0

        result = wm.analyze_trade(enriched)

        assert result is None
        assert wm.get_gate_counts().get("liquidity") == 1
        assert wm.get_gate_counts().get("hourly_not_target_hour", 0) == 0

    def test_non_target_hour_still_gates_out_even_with_good_liquidity(
        self, tmp_path, monkeypatch
    ):
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch, max_hour=14, min_hour=6)
        self._pin_sources(monkeypatch, temps=[64.0] * 14 + [66.0] * 6)
        wm.reset_gate_counts()

        result = wm.analyze_trade(
            self._enriched(yes_bid_cents=22, yes_ask_cents=28, hour=9)
        )

        assert result is None
        assert wm.get_gate_counts().get("hourly_not_target_hour") == 1

    def test_result_shape_has_required_downstream_fields(self, tmp_path, monkeypatch):
        """order_executor._prediction_kwargs_from_analysis / log_prediction
        read these keys unconditionally -- a missing one is a KeyError risk
        at real trade-placement/logging time, not caught by a None check."""
        import weather_markets as wm

        self._cache_target_hour(tmp_path, monkeypatch)
        self._pin_sources(monkeypatch, temps=[64.0] * 14 + [66.0] * 6)

        result = wm.analyze_trade(self._enriched(yes_bid_cents=22, yes_ask_cents=28))

        assert result is not None
        required = [
            "forecast_prob",
            "market_prob",
            "edge",
            "net_edge",
            "recommended_side",
            "condition",
            "forecast_temp",
            "method",
            "n_members",
            "ci_low",
            "ci_high",
            "ci_adjusted_kelly",
            "days_out",
            "city",
            "target_date",
        ]
        for key in required:
            assert key in result, f"missing required field {key!r}"


class TestHourlyGatesActive:
    """backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff
    item 5: _hourly_gates_active() mirrors _below_gates_active()'s exact
    shape -- env var AND a settled-sample floor, both required."""

    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("HOURLY_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_hourly_predictions", lambda: 999)
        assert wm._hourly_gates_active() is False

    def test_false_when_env_var_set_but_below_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HOURLY_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_hourly_predictions", lambda: 19)
        assert wm._hourly_gates_active() is False

    def test_true_when_env_var_set_and_sample_floor_met(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HOURLY_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_hourly_predictions", lambda: 20)
        assert wm._hourly_gates_active() is True

    def test_false_when_sample_floor_met_but_env_var_unset(self, monkeypatch):
        """Both conditions are required -- neither alone suffices."""
        import weather_markets as wm

        monkeypatch.delenv("HOURLY_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_hourly_predictions", lambda: 500)
        assert wm._hourly_gates_active() is False

    def test_accepts_true_yes_case_insensitive(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr("tracker.count_settled_hourly_predictions", lambda: 20)
        for value in ("1", "true", "True", "yes", "YES"):
            monkeypatch.setenv("HOURLY_TRADING_ENABLED", value)
            assert wm._hourly_gates_active() is True, f"expected True for {value!r}"

    def test_never_raises_on_count_failure(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HOURLY_TRADING_ENABLED", "1")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("tracker.count_settled_hourly_predictions", _boom)
        assert wm._hourly_gates_active() is False


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
