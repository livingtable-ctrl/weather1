"""Tests for weather_markets.py's hurricane-season-count model (backlog.txt
"HURRICANE MARKETS" -- season-count model, 2026-08-03): ticker/condition
parsing for the 5 season-total series (KXHURCTOT/KXHURCTOTMAJ/KXTROPSTORM/
KXHURRICANE/KXNAMEDSTORM), the shadow-only gate, the current-count-to-date
cache, and the full analyze_trade() dispatch.

See tests/test_hurricane_climatology.py for the underlying HURDAT2 parsing/
distribution math, and tests/test_hurricane_gating.py for the is_hurricane_
ticker() blanket-guard carve-out itself.
"""

from __future__ import annotations

import json

import pytest

# ── is_hurricane_count_ticker / _hurricane_count_key_from_ticker ────────────


class TestIsHurricaneCountTicker:
    @pytest.mark.parametrize(
        "ticker",
        [
            "KXHURCTOT-26DEC01-T9",
            "KXHURCTOTMAJ-26DEC01-T7",
            "KXTROPSTORM-26DEC01-T30",
            "KXHURRICANE-26DEC01EPACMAJ-8",
            "KXNAMEDSTORM-26DEC01CPACTOT-2",
        ],
    )
    def test_matches_all_5_real_series(self, ticker):
        import weather_markets as wm

        assert wm.is_hurricane_count_ticker(ticker) is True

    def test_kxhurctot_prefix_does_not_swallow_kxhurctotmaj(self):
        """The exact bug class this must avoid: KXHURCTOT is a strict
        string-prefix of KXHURCTOTMAJ -- a startswith/substring check would
        misclassify one as the other. Both individually match (checked
        above); this test only needs to confirm they're each their OWN
        series membership check, not a substring collision -- see
        _hurricane_count_key_from_ticker's own test for the stronger
        "resolves to the RIGHT count_type" assertion."""
        import weather_markets as wm

        assert wm.is_hurricane_count_ticker("KXHURCTOT-26DEC01-T9") is True
        assert wm.is_hurricane_count_ticker("KXHURCTOTMAJ-26DEC01-T7") is True

    @pytest.mark.parametrize(
        "ticker",
        [
            "KXHURCAT-26FAUSTO-T5",  # per-storm category -- still unsupported
            "KXHURMIA-26-SOMETHING",  # per-city landfall -- still unsupported
            "KXFIRSTHURRICANE-26DEC01ATL-WIL",  # storm-name-order -- unsupported
            "HURCAT-26FAUSTO-T5",  # legacy unprefixed -- unsupported
            "KXHIGHNY-26JUL20-T70",  # unrelated market entirely
        ],
    )
    def test_does_not_match_other_hurricane_or_unrelated_tickers(self, ticker):
        import weather_markets as wm

        assert wm.is_hurricane_count_ticker(ticker) is False


class TestHurricaneCountKeyFromTicker:
    def test_atl_series_map_to_correct_basin_and_count_type(self):
        import weather_markets as wm

        assert wm._hurricane_count_key_from_ticker("KXHURCTOT-26DEC01-T9") == (
            "ATL",
            "hurricane",
            2026,
        )
        assert wm._hurricane_count_key_from_ticker("KXHURCTOTMAJ-26DEC01-T7") == (
            "ATL",
            "major_hurricane",
            2026,
        )
        assert wm._hurricane_count_key_from_ticker("KXTROPSTORM-26DEC01-T30") == (
            "ATL",
            "tropical_storm",
            2026,
        )

    def test_kxhurricane_resolves_basin_and_maj_suffix_from_event_middle(self):
        import weather_markets as wm

        assert wm._hurricane_count_key_from_ticker("KXHURRICANE-26DEC01EPACMAJ-8") == (
            "EPAC",
            "major_hurricane",
            2026,
        )
        assert wm._hurricane_count_key_from_ticker("KXHURRICANE-26DEC01EPACTOT-5") == (
            "EPAC",
            "hurricane",
            2026,
        )
        assert wm._hurricane_count_key_from_ticker("KXHURRICANE-26DEC01CPACMAJ-3") == (
            "CPAC",
            "major_hurricane",
            2026,
        )
        assert wm._hurricane_count_key_from_ticker("KXHURRICANE-26DEC01CPACTOT-1") == (
            "CPAC",
            "hurricane",
            2026,
        )

    def test_kxnamedstorm_is_always_tropical_storm_count_type(self):
        import weather_markets as wm

        assert wm._hurricane_count_key_from_ticker(
            "KXNAMEDSTORM-26DEC01EPACTOT-20"
        ) == ("EPAC", "tropical_storm", 2026)
        assert wm._hurricane_count_key_from_ticker("KXNAMEDSTORM-26DEC01CPACTOT-2") == (
            "CPAC",
            "tropical_storm",
            2026,
        )

    def test_season_year_derived_from_2_digit_prefix(self):
        import weather_markets as wm

        assert wm._hurricane_count_key_from_ticker("KXHURCTOT-27DEC01-T9")[2] == 2027

    def test_returns_none_for_unrelated_ticker(self):
        import weather_markets as wm

        assert wm._hurricane_count_key_from_ticker("KXHIGHNY-26JUL20-T70") is None

    def test_returns_none_for_missing_basin_infix(self):
        """KXHURRICANE/KXNAMEDSTORM without a real EPAC/CPAC infix in the
        event-ticker middle segment must fail closed, not guess a basin."""
        import weather_markets as wm

        assert (
            wm._hurricane_count_key_from_ticker("KXHURRICANE-26DEC01XXXMAJ-8") is None
        )

    def test_returns_none_for_malformed_ticker(self):
        import weather_markets as wm

        assert wm._hurricane_count_key_from_ticker("KXHURCTOT") is None
        assert wm._hurricane_count_key_from_ticker("KXHURCTOT-2") is None

    def test_returns_none_for_unexpected_count_type_suffix(self):
        """Opus-review-caught (2026-08-03): the original `else "hurricane"`
        fallback failed OPEN -- any suffix other than the real "MAJ"/"TOT"
        (e.g. an almost-match like "MAJOR") would silently price a
        major-hurricane market against total-hurricane climatology, a
        materially different (much fatter) distribution, with no warning.
        Must fail closed instead."""
        import weather_markets as wm

        assert (
            wm._hurricane_count_key_from_ticker("KXHURRICANE-26DEC01EPACMAJOR-8")
            is None
        )
        assert (
            wm._hurricane_count_key_from_ticker("KXNAMEDSTORM-26DEC01EPACMAJ-8") is None
        )


# ── _parse_hurricane_count_condition ────────────────────────────────────────


class TestParseHurricaneCountCondition:
    def _market(self, **overrides):
        base = {
            "ticker": "KXHURCTOT-26DEC01-T9",
            "event_ticker": "KXHURCTOT-26DEC01",
            "floor_strike": 9,
            "strike_type": "greater",
        }
        base.update(overrides)
        return base

    def test_full_valid_market_parses_correctly(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_count_condition(self._market())
        assert cond == {
            "type": "hurricane_count",
            "basin": "ATL",
            "count_type": "hurricane",
            "threshold": 9.0,
            "strike_type": "greater",
            "season_year": 2026,
        }

    def test_missing_floor_strike_returns_none(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_count_condition(self._market(floor_strike=None))
        assert cond is None

    def test_unexpected_strike_type_fails_closed(self):
        """Confirmed live 2026-08-03: every one of these 5 series' open+
        settled markets uses strike_type="greater" -- anything else must
        refuse rather than guess a direction."""
        import weather_markets as wm

        cond = wm._parse_hurricane_count_condition(self._market(strike_type="less"))
        assert cond is None

    def test_greater_or_equal_is_accepted_defensively(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_count_condition(
            self._market(strike_type="greater_or_equal")
        )
        assert cond is not None
        assert cond["strike_type"] == "greater_or_equal"

    def test_non_numeric_floor_strike_returns_none(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_count_condition(
            self._market(floor_strike="not-a-number")
        )
        assert cond is None

    def test_non_hurricane_count_ticker_returns_none_silently(self, caplog):
        """Every other branch in _parse_market_condition returns None
        silently for a non-matching ticker (no warning log) -- this branch
        must match that convention, not warn on every single unrelated
        market analyzed."""
        import weather_markets as wm

        cond = wm._parse_hurricane_count_condition({"ticker": "KXHIGHNY-26JUL20-T70"})
        assert cond is None
        assert "could not derive" not in caplog.text

    def test_dispatches_via_parse_market_condition(self):
        """End-to-end through the real dispatcher, not just the dedicated
        function directly -- confirms the branch is actually wired in."""
        import weather_markets as wm

        cond = wm._parse_market_condition(self._market())
        assert cond is not None
        assert cond["type"] == "hurricane_count"

    def test_degraded_hurricane_count_market_fails_closed_at_dispatcher(self):
        """Opus-review-caught (2026-08-03, HIGH): a hurricane-count series
        ticker whose own fields fail to parse (missing floor_strike, or an
        unexpected strike_type) must return None from _parse_market_condition
        itself -- NOT fall through to the generic temperature-threshold
        parser further down, which would happily match this ticker family's
        real "-T9"/"-T30" suffix as a °F threshold (the exact KXHURCAT bug
        class this whole guard exists to prevent). Title/yes_sub_title text
        containing "above" is included deliberately -- without it, the
        generic branch's own title-fallback also returns None (no direction
        keyword), making this test pass for the wrong reason regardless of
        whether the fail-closed fix is in place. Reproduces the real bug:
        without the fix, this returned {"type": "above", "threshold": 9.0}
        instead of None."""
        import weather_markets as wm

        degraded = self._market(
            floor_strike=None, title="hurricane count above threshold"
        )
        cond = wm._parse_market_condition(degraded)
        assert cond is None

        degraded2 = self._market(
            strike_type="less", title="hurricane count above threshold"
        )
        cond2 = wm._parse_market_condition(degraded2)
        assert cond2 is None

    def test_degraded_hurricane_count_market_does_not_reach_temperature_pipeline(self):
        """Same finding as above, exercised through the full analyze_trade()
        dispatch: a degraded KXHURCTOT market must not reach the daily
        temperature pipeline (which would either crash on this file's own
        `assert city is not None` narrowing, or silently mis-score under
        `python -O`, where asserts are stripped)."""
        import weather_markets as wm

        enriched = wm.enrich_with_forecast(
            {
                "ticker": "KXHURCTOT-26DEC01-T9",
                "event_ticker": "KXHURCTOT-26DEC01",
                "floor_strike": None,  # degraded: missing
                "strike_type": "greater",
                "title": "Will there be more than 9 Atlantic hurricanes in 2026?",
                "yes_sub_title": "Above 9",
            },
            fetch_forecast=False,
        )
        wm.reset_gate_counts()
        result = wm.analyze_trade(enriched)
        assert result is None
        counts = wm.get_gate_counts()
        assert counts.get("hurricane_not_supported") is None
        # Must NOT reach the daily pipeline's later gates (no_forecast would
        # fire there since forecast/city/coords are None for this ticker).
        assert counts.get("condition_parse") == 1

    def test_season_year_mismatched_with_close_time_fails_closed(self):
        """Opus-review-caught (2026-08-03): season_year is derived from a
        bare 2-digit ticker substring with no cross-check -- a malformed/
        adversarial ticker could produce a wrong season_year, which would
        mis-key tracker.count_settled_hurricane_predictions()'s dedup (a
        real live gate, not just cosmetic). Cross-checked against the
        market's own close_time (these markets never span a year boundary)."""
        import weather_markets as wm

        market = self._market(
            ticker="KXHURCTOT-26DEC01-T9",
            event_ticker="KXHURCTOT-26DEC01",
            close_time="2030-12-02T04:59:00Z",  # real season_year would be 2026
        )
        cond = wm._parse_hurricane_count_condition(market)
        assert cond is None

    def test_season_year_within_one_year_of_close_time_is_accepted(self):
        """A 1-year mismatch (e.g. a market closing just after a UTC-vs-
        ticker-local year boundary) must still be accepted -- only a
        larger mismatch indicates real corruption."""
        import weather_markets as wm

        market = self._market(
            ticker="KXHURCTOT-26DEC01-T9",
            event_ticker="KXHURCTOT-26DEC01",
            close_time="2027-01-01T04:59:00Z",
        )
        cond = wm._parse_hurricane_count_condition(market)
        assert cond is not None
        assert cond["season_year"] == 2026

    def test_missing_close_time_does_not_block_the_parse(self):
        """The cross-check is defense-in-depth, not a hard requirement --
        a market with no close_time (or an unparseable one) must still
        parse normally, matching every other optional-field guard in this
        function."""
        import weather_markets as wm

        market = self._market(close_time="")
        cond = wm._parse_hurricane_count_condition(market)
        assert cond is not None


# ── _hurricane_count_gates_active ───────────────────────────────────────────


class TestHurricaneCountGatesActive:
    """Mirrors _rain_gates_active()'s/_snow_gates_active()'s exact test
    shape (tests/test_snow_markets.py::TestSnowGatesActive)."""

    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("HURRICANE_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 999)
        assert wm._hurricane_count_gates_active() is False

    def test_false_when_env_var_set_but_below_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 19)
        assert wm._hurricane_count_gates_active() is False

    def test_true_when_env_var_set_and_sample_floor_met(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 20)
        assert wm._hurricane_count_gates_active() is True

    def test_false_when_sample_floor_met_but_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("HURRICANE_TRADING_ENABLED", raising=False)
        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 500)
        assert wm._hurricane_count_gates_active() is False

    def test_never_raises_on_count_failure(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_TRADING_ENABLED", "1")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", _boom)
        assert wm._hurricane_count_gates_active() is False

    def test_falsy_env_var_values_stay_false(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 999)
        for falsy in ("0", "false", "off", ""):
            monkeypatch.setenv("HURRICANE_TRADING_ENABLED", falsy)
            assert wm._hurricane_count_gates_active() is False, (
                f"{falsy!r} must not be truthy"
            )

    def test_truthy_env_var_values_case_insensitive(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 20)
        for truthy in ("1", "true", "TRUE", "yes", "Yes"):
            monkeypatch.setenv("HURRICANE_TRADING_ENABLED", truthy)
            assert wm._hurricane_count_gates_active() is True, (
                f"{truthy!r} must be truthy"
            )


# ── Current-count-to-date cache (refresh_hurricane_count_to_date /
#    _get_cached_hurricane_count_to_date) ────────────────────────────────────


class TestHurricaneCountToDateCache:
    def _settled_market(self, event_ticker, result):
        return {"event_ticker": event_ticker, "result": result}

    def test_refresh_counts_settled_yes_per_basin(self, tmp_path, monkeypatch):
        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                assert series_ticker == "KXHURRICANENAMES"
                assert status == "settled"
                return [
                    self._m("KXHURRICANENAMES-26DEC01ATL", "yes"),
                    self._m("KXHURRICANENAMES-26DEC01ATL", "no"),
                    self._m("KXHURRICANENAMES-26DEC01EPAC", "yes"),
                    self._m("KXHURRICANENAMES-26DEC01EPAC", "yes"),
                    self._m("KXHURRICANENAMES-26DEC01CPAC", "no"),
                ]

            def _m(self, event_ticker, result):
                return {"event_ticker": event_ticker, "result": result}

        wm.refresh_hurricane_count_to_date(_FakeClient())
        cached = json.loads(cache_path.read_text())
        assert cached["ATL"]["count"] == 1
        assert cached["EPAC"]["count"] == 2
        assert cached["CPAC"]["count"] == 0

    def test_refresh_skips_basin_already_done_today(self, tmp_path, monkeypatch):
        from datetime import UTC, datetime

        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        today = datetime.now(UTC).date().isoformat()
        cache_path.write_text(
            json.dumps({"ATL": {"date": today, "season_year": 2026, "count": 7}})
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        calls = []

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                calls.append(1)
                return []

        wm.refresh_hurricane_count_to_date(_FakeClient())
        cached = json.loads(cache_path.read_text())
        # ATL untouched (still today's stale-but-cached 7), not overwritten with 0.
        assert cached["ATL"]["count"] == 7

    def test_refresh_never_raises_on_fetch_failure(self, tmp_path, monkeypatch):
        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                raise RuntimeError("network down")

        wm.refresh_hurricane_count_to_date(_FakeClient())  # must not raise
        assert not cache_path.exists()

    def test_get_cached_returns_none_when_missing(self, tmp_path, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", tmp_path / "nope.json")
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) is None

    def test_get_cached_returns_none_for_wrong_season_year(self, tmp_path, monkeypatch):
        """A stale prior-season cache entry must never silently tilt the
        CURRENT season's distribution."""
        import weather_markets as wm

        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps({"ATL": {"date": "2025-08-01", "season_year": 2025, "count": 5}})
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) is None

    def test_get_cached_returns_count_for_matching_season(self, tmp_path, monkeypatch):
        import weather_markets as wm

        # Dynamically-computed "today" (not hardcoded) so this stays valid
        # regardless of when the real suite runs -- the new staleness check
        # (opus-review-caught, below) would otherwise make a hardcoded past
        # date fail this test once enough real time has passed.
        today = wm.datetime.now(wm.UTC).date().isoformat()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps({"ATL": {"date": today, "season_year": 2026, "count": 3}})
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) == 3

    def test_get_cached_returns_none_for_stale_date(self, tmp_path, monkeypatch):
        """Opus-review-caught (2026-08-03, HIGH): the cache's `date` field
        was written but never checked on read -- a stalled refresh job
        (repeated fetch failures, or the process just not running) would
        silently serve an arbitrarily-old count-to-date forever, desynced
        from as_of_month_day (always derived from TODAY). Verified this can
        flip a probability from 0.99 to 0.01 with no warning -- must reject
        anything older than _HURRICANE_COUNT_CACHE_MAX_AGE_DAYS."""
        from datetime import timedelta

        import weather_markets as wm

        stale_date = (
            wm.datetime.now(wm.UTC).date()
            - timedelta(days=wm._HURRICANE_COUNT_CACHE_MAX_AGE_DAYS + 1)
        ).isoformat()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps({"ATL": {"date": stale_date, "season_year": 2026, "count": 3}})
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) is None

    def test_get_cached_accepts_recent_date_within_max_age(self, tmp_path, monkeypatch):
        from datetime import timedelta

        import weather_markets as wm

        recent_date = (
            wm.datetime.now(wm.UTC).date()
            - timedelta(days=wm._HURRICANE_COUNT_CACHE_MAX_AGE_DAYS)
        ).isoformat()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps({"ATL": {"date": recent_date, "season_year": 2026, "count": 3}})
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) == 3

    def test_get_cached_returns_none_for_corrupt_non_dict_entry(
        self, tmp_path, monkeypatch
    ):
        """Opus-review-caught: a corrupted cache with a non-dict basin
        entry must fail closed (return None), not raise AttributeError out
        of analyze_trade()."""
        import weather_markets as wm

        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps({"ATL": 5}))
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) is None

    def test_get_cached_returns_none_for_non_int_count(self, tmp_path, monkeypatch):
        import weather_markets as wm

        today = wm.datetime.now(wm.UTC).date().isoformat()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps(
                {"ATL": {"date": today, "season_year": 2026, "count": "not-a-number"}}
            )
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_hurricane_count_to_date("ATL", 2026) is None

    def test_refresh_leaves_basin_unwritten_when_no_markets_match(
        self, tmp_path, monkeypatch
    ):
        """Opus-review-caught (2026-08-03, MEDIUM-HIGH): an empty/no-match
        settled-markets response (series renamed, event-ticker format
        change, transient API filter change) is NOT an exception, so the
        fetch try/except doesn't catch it -- previously this wrote count=0
        for every basin, indistinguishable from a real "zero hurricanes so
        far" season. Must leave the basin's cache entry unwritten instead,
        so _get_cached_hurricane_count_to_date's missing-entry fallback
        (climatology-only) applies."""
        import weather_markets as wm

        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                return []  # nothing matched any event_ticker at all

        wm.refresh_hurricane_count_to_date(_FakeClient())
        assert not cache_path.exists() or json.loads(cache_path.read_text()) == {}


# ── _analyze_hurricane_count_trade (full dispatch, mocked climatology) ──────


class TestAnalyzeHurricaneCountTrade:
    def _enriched(self, **overrides):
        base = {
            "ticker": "KXHURCTOT-26DEC01-T7",
            "event_ticker": "KXHURCTOT-26DEC01",
            "floor_strike": 7,
            "strike_type": "greater",
            "close_time": "2026-12-02T04:59:00Z",
            "yes_bid_dollars": 0.20,
            "yes_ask_dollars": 0.24,
        }
        base.update(overrides)
        return base

    def _condition(self, **overrides):
        base = {
            "type": "hurricane_count",
            "basin": "ATL",
            "count_type": "hurricane",
            "threshold": 7.0,
            "strike_type": "greater",
            "season_year": 2026,
        }
        base.update(overrides)
        return base

    def test_returns_none_when_hurdat2_unavailable(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms", lambda basin: None
        )
        result = wm._analyze_hurricane_count_trade(
            self._enriched(),
            self._condition(),
            __import__("datetime").datetime(2026, 12, 2),
            30,
        )
        assert result is None

    def test_returns_none_when_storms_list_is_empty(self, monkeypatch):
        """Opus-review-caught (2026-08-03): season_end_total_distribution
        always returns exactly window_years entries now (the calendar-year
        window fix), so an empty `storms` list can no longer be caught via
        a "too few totals" check downstream -- it must be caught explicitly
        right after load_basin_storms(), same as the None (fetch-failed)
        case."""
        import weather_markets as wm

        monkeypatch.setattr("hurricane_climatology.load_basin_storms", lambda basin: [])
        result = wm._analyze_hurricane_count_trade(
            self._enriched(),
            self._condition(),
            __import__("datetime").datetime(2026, 12, 2),
            30,
        )
        assert result is None

    def test_full_analysis_with_mocked_climatology(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        # 30 synthetic seasons, half above the threshold(7)/half at-or-below
        # -> a clean, hand-verifiable 50% unconditional probability.
        fake_storms = [{"year": 2000 + i, "basin": "AL"} for i in range(30)]
        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms", lambda basin: fake_storms
        )
        counts = [8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8] + [3] * 15

        def _fake_season_end_totals(storms, count_type, **kwargs):
            assert count_type == "hurricane"
            return list(counts)

        monkeypatch.setattr(
            hc, "season_end_total_distribution", _fake_season_end_totals
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )

        from datetime import datetime as _dt

        result = wm._analyze_hurricane_count_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 2), 30
        )
        assert result is not None
        assert result["forecast_prob"] == 0.5  # 15/30 strictly > 7
        assert result["basin"] == "ATL"
        assert result["count_type"] == "hurricane"
        assert result["season_year"] == 2026
        assert result["city"] == "HUR_ATL"
        assert result["target_date"] == "2026-12-02"
        assert result["method"] == "hurricane_count_bootstrap"  # no tilt applied
        assert result["n_historical_seasons"] == 30

    def test_tilt_only_applied_for_hurricane_count_type(self, monkeypatch):
        """major_hurricane/tropical_storm must never call the current-count
        cache -- confirmed scoped to count_type="hurricane" only (backlog.txt
        resolution note: no clean per-basin current-count source exists yet
        for the other two)."""
        import hurricane_climatology as hc
        import weather_markets as wm

        fake_storms = [{"year": 2000 + i, "basin": "AL"} for i in range(20)]
        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms", lambda basin: fake_storms
        )
        monkeypatch.setattr(
            hc,
            "season_end_total_distribution",
            lambda storms, count_type, **kwargs: [3] * 20,
        )

        calls = []

        def _fail_if_called(basin, year):
            calls.append((basin, year))
            return 5

        monkeypatch.setattr(wm, "_get_cached_hurricane_count_to_date", _fail_if_called)

        from datetime import datetime as _dt

        wm._analyze_hurricane_count_trade(
            self._enriched(),
            self._condition(count_type="major_hurricane"),
            _dt(2026, 12, 2),
            30,
        )
        assert calls == []  # never called for major_hurricane

    def test_recommended_side_follows_edge_direction(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        fake_storms = [{"year": 2000 + i, "basin": "AL"} for i in range(20)]
        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms", lambda basin: fake_storms
        )
        # All 20 seasons exceed the threshold -> forecast_prob clamps to 0.99,
        # far above a cheap market price -> recommended_side must be "yes".
        monkeypatch.setattr(
            hc,
            "season_end_total_distribution",
            lambda storms, count_type, **kwargs: [100] * 20,
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )

        from datetime import datetime as _dt

        result = wm._analyze_hurricane_count_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 2), 30
        )
        assert result["forecast_prob"] == 0.99
        assert result["recommended_side"] == "yes"


# ── check_position_limits() / cmd_order() guard conditional (mirrors
#    tests/test_snow_markets.py::TestCheckPositionLimitsSnowConditional and
#    TestCmdOrderSnowGuard exactly) ───────────────────────────────────────────


class TestCheckPositionLimitsHurricaneCountConditional:
    def test_still_blocks_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("HURRICANE_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits("KXHURCTOT-26DEC01-T9", qty=1, price=0.10)
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()

    def test_does_not_block_when_gate_active(self, monkeypatch, tmp_path):
        """Mutation-test proof: flipping _hurricane_count_gates_active() to
        True makes the block disappear."""
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
                        "weather_markets._hurricane_count_gates_active",
                        lambda: True,
                    )
                    result = paper.check_position_limits(
                        "KXHURCTOT-26DEC01-T9", qty=1, price=0.10
                    )
        assert result["ok"] is True

    def test_other_hurricane_shapes_still_unconditionally_blocked(self, monkeypatch):
        """KXHURCAT (per-storm category, still unsupported) must stay
        blocked regardless of the hurricane-count gate's state."""
        import paper

        monkeypatch.setattr(
            "weather_markets._hurricane_count_gates_active", lambda: True
        )
        result = paper.check_position_limits("KXHURCAT-26FAUSTO-T5", qty=1, price=0.10)
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()


class TestCmdOrderHurricaneCountGuard:
    def test_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("HURRICANE_TRADING_ENABLED", raising=False)
        main.cmd_order(None, "buy", ["KXHURCTOT-26DEC01-T9", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "hurricane season-count" in out.lower()
        assert "HURRICANE_TRADING_ENABLED" in out

    def test_does_not_refuse_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._hurricane_count_gates_active", lambda: True)
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_order(None, "buy", ["KXHURCTOT-26DEC01-T9", "yes", "1", "0.10"])
        except Exception:
            pass  # downstream failure (no live market) is expected/irrelevant here
        assert not any(
            "hurricane season-count markets are shadow-only" in p for p in printed
        )

    def test_other_hurricane_shapes_still_unconditionally_refused(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._hurricane_count_gates_active", lambda: True)
        main.cmd_order(None, "buy", ["KXHURCAT-26FAUSTO-T5", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "hurricane markets are not supported yet" in out
