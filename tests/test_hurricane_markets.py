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

    # ── batch-59 item 3: last_yes_close_time ────────────────────────────────

    def test_refresh_records_latest_yes_close_time_per_basin(
        self, tmp_path, monkeypatch
    ):
        """The cache must carry WHEN the most recent qualifying storm was
        confirmed, per basin, taken from the latest "yes"-settled market's
        close_time — and must ignore "no"-settled markets' close_times even
        when those are later (the real ATL batch settled 2026-08-21, weeks
        after EPAC's real "yes" markets closed 2026-07-29)."""
        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                return [
                    # EPAC: two "yes" markets, the later one must win.
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01EPAC",
                        "result": "yes",
                        "close_time": "2026-07-29T14:45:58Z",
                    },
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01EPAC",
                        "result": "yes",
                        "close_time": "2026-07-29T14:46:04Z",
                    },
                    # ATL: only "no" markets, settled LATER than EPAC's yes —
                    # must not be mistaken for a confirmed storm.
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01ATL",
                        "result": "no",
                        "close_time": "2026-08-21T15:40:37Z",
                    },
                ]

        wm.refresh_hurricane_count_to_date(_FakeClient())
        cached = json.loads(cache_path.read_text())

        assert cached["EPAC"]["count"] == 2
        assert cached["EPAC"]["last_yes_close_time"].startswith("2026-07-29T14:46:04")
        assert cached["ATL"]["count"] == 0
        assert cached["ATL"]["last_yes_close_time"] is None

    def test_refresh_skips_unparseable_close_time_without_dropping_the_basin(
        self, tmp_path, monkeypatch
    ):
        """A malformed close_time must not raise, must not poison the value,
        and must not stop the count itself from being written."""
        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                return [
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01ATL",
                        "result": "yes",
                        "close_time": "garbage",
                    },
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01ATL",
                        "result": "yes",
                        "close_time": "2026-08-21T15:40:37Z",
                    },
                ]

        wm.refresh_hurricane_count_to_date(_FakeClient())
        cached = json.loads(cache_path.read_text())
        assert cached["ATL"]["count"] == 2
        assert cached["ATL"]["last_yes_close_time"].startswith("2026-08-21T15:40:37")

    def test_refresh_survives_a_mixed_naive_and_aware_close_time(
        self, tmp_path, monkeypatch
    ):
        """A naive close_time alongside an aware one must not abort the whole
        refresh.

        Opus review finding LM8: `max()` over a list mixing naive and aware
        datetimes raises TypeError, and the function-level `except Exception`
        wraps the atomic_write_json too — so EVERY basin would go unwritten,
        losing the count/storms_named refresh as well, with only a DEBUG
        trace. After the 2-day staleness cap every hurricane reader would
        then degrade to no-signal."""
        from datetime import UTC, datetime

        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                return [
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01ATL",
                        "result": "yes",
                        "close_time": "2026-07-29T14:45:58",  # naive
                    },
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01ATL",
                        "result": "yes",
                        "close_time": "2026-08-21T15:40:37Z",  # aware
                    },
                    # A second basin proves the abort would have been global,
                    # not confined to the basin carrying the bad value.
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01EPAC",
                        "result": "yes",
                        "close_time": "2026-07-29T14:46:04Z",
                    },
                ]

        wm.refresh_hurricane_count_to_date(_FakeClient())
        assert cache_path.exists(), "a mixed-tz close_time must not abort the write"
        cached = json.loads(cache_path.read_text())
        assert cached["ATL"]["count"] == 2
        assert cached["EPAC"]["count"] == 1
        season = datetime.now(UTC).date().year
        assert wm._get_cached_last_hurricane_event_time("ATL", season) == datetime(
            2026, 8, 21, 15, 40, 37, tzinfo=UTC
        )

    def test_get_cached_last_event_time_reads_back_what_refresh_wrote(
        self, tmp_path, monkeypatch
    ):
        """End-to-end round trip through the real writer and the real reader,
        rather than asserting against a hand-built cache file."""
        from datetime import UTC, datetime

        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                return [
                    {
                        "event_ticker": "KXHURRICANENAMES-26DEC01ATL",
                        "result": "yes",
                        "close_time": "2026-08-21T15:40:37Z",
                    }
                ]

        wm.refresh_hurricane_count_to_date(_FakeClient())
        season = datetime.now(UTC).date().year
        got = wm._get_cached_last_hurricane_event_time("ATL", season)
        assert got == datetime(2026, 8, 21, 15, 40, 37, tzinfo=UTC)

    def test_get_cached_last_event_time_none_on_legacy_cache_without_field(
        self, tmp_path, monkeypatch
    ):
        """A cache written before this field existed must read as None
        (unknown), not raise and not fabricate a timestamp."""
        from datetime import UTC, datetime

        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        season = datetime.now(UTC).date().year
        cache_path.write_text(
            json.dumps(
                {
                    "ATL": {
                        "date": datetime.now(UTC).date().isoformat(),
                        "season_year": season,
                        "count": 2,
                        "storms_named": 3,
                    }
                }
            )
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        # Positive control: the same entry DOES resolve for the pre-existing
        # count reader, so None below is about the missing field specifically,
        # not about the entry being rejected wholesale by the shared guards.
        assert wm._get_cached_hurricane_count_to_date("ATL", season) == 2
        assert wm._get_cached_last_hurricane_event_time("ATL", season) is None

    def test_get_cached_last_event_time_normalizes_a_naive_timestamp(
        self, tmp_path, monkeypatch
    ):
        """A hand-edited naive value must come back tz-aware — comparing naive
        to aware at the anchoring site would raise TypeError."""
        from datetime import UTC, datetime

        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        season = datetime.now(UTC).date().year
        cache_path.write_text(
            json.dumps(
                {
                    "ATL": {
                        "date": datetime.now(UTC).date().isoformat(),
                        "season_year": season,
                        "count": 1,
                        "storms_named": 1,
                        "last_yes_close_time": "2026-08-21T15:40:37",
                    }
                }
            )
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        got = wm._get_cached_last_hurricane_event_time("ATL", season)
        assert got is not None and got.tzinfo is not None
        assert got == datetime(2026, 8, 21, 15, 40, 37, tzinfo=UTC)

    def test_get_cached_last_event_time_none_on_corrupt_value(
        self, tmp_path, monkeypatch
    ):
        from datetime import UTC, datetime

        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        season = datetime.now(UTC).date().year
        cache_path.write_text(
            json.dumps(
                {
                    "ATL": {
                        "date": datetime.now(UTC).date().isoformat(),
                        "season_year": season,
                        "count": 1,
                        "storms_named": 1,
                        "last_yes_close_time": "not-a-timestamp",
                    }
                }
            )
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_last_hurricane_event_time("ATL", season) is None

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


# ── storms-named-to-date cache (backlog.txt "HURRICANE MARKETS" -- storm-
#    order model, 2026-08-07): refresh_hurricane_count_to_date extended to
#    also write `storms_named`, read back via
#    _get_cached_storms_named_to_date. Opus-review-caught (2026-08-07, LOW):
#    every _analyze_storm_order_trade test monkeypatches
#    _get_cached_storms_named_to_date directly -- nothing exercised the real
#    writer -> real JSON file -> real reader round-trip, so a field-name
#    typo or a dropped write would degrade silently to storms_named_so_far=0
#    forever. Closed here with real (not monkeypatched) reads/writes,
#    mirroring TestHurricaneCountToDateCache's own shape for the sibling
#    `count` field. ─────────────────────────────────────────────────────────


class TestStormsNamedToDateCache:
    def test_refresh_writes_storms_named_per_basin(self, tmp_path, monkeypatch):
        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                assert series_ticker == "KXHURRICANENAMES"
                assert status == "settled"
                return [
                    self._m("KXHURRICANENAMES-26DEC01ATL", "no"),
                    self._m("KXHURRICANENAMES-26DEC01ATL", "no"),
                    self._m("KXHURRICANENAMES-26DEC01ATL", "yes"),
                    self._m("KXHURRICANENAMES-26DEC01EPAC", "no"),
                ]

            def _m(self, event_ticker, result):
                return {"event_ticker": event_ticker, "result": result}

        wm.refresh_hurricane_count_to_date(_FakeClient())
        cached = json.loads(cache_path.read_text())
        assert cached["ATL"]["storms_named"] == 3
        assert cached["ATL"]["count"] == 1  # sibling field, same source data
        assert cached["EPAC"]["storms_named"] == 1
        assert "CPAC" not in cached  # zero matched markets -- left unwritten

    def test_get_cached_storms_named_returns_none_when_missing(
        self, tmp_path, monkeypatch
    ):
        import weather_markets as wm

        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", tmp_path / "nope.json")
        assert wm._get_cached_storms_named_to_date("ATL", 2026) is None

    def test_get_cached_storms_named_round_trips_through_real_refresh(
        self, tmp_path, monkeypatch
    ):
        """The real end-to-end path: refresh_hurricane_count_to_date's
        actual write, read back by _get_cached_storms_named_to_date's own
        actual read -- no monkeypatching of either function itself."""
        import weather_markets as wm

        cache_path = tmp_path / "hurricane_count_to_date.json"
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)

        class _FakeClient:
            def get_markets(self, series_ticker, status):
                return [
                    {"event_ticker": "KXHURRICANENAMES-26DEC01ATL", "result": "no"},
                    {"event_ticker": "KXHURRICANENAMES-26DEC01ATL", "result": "no"},
                ]

        wm.refresh_hurricane_count_to_date(_FakeClient())
        season_year = wm.datetime.now(wm.UTC).date().year
        assert wm._get_cached_storms_named_to_date("ATL", season_year) == 2

    def test_get_cached_storms_named_returns_none_for_non_int(
        self, tmp_path, monkeypatch
    ):
        import weather_markets as wm

        today = wm.datetime.now(wm.UTC).date().isoformat()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "ATL": {
                        "date": today,
                        "season_year": 2026,
                        "count": 0,
                        "storms_named": "not-a-number",
                    }
                }
            )
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_storms_named_to_date("ATL", 2026) is None

    def test_get_cached_storms_named_shares_staleness_guard_with_count(
        self, tmp_path, monkeypatch
    ):
        """Both readers delegate to the same _get_cached_hurricane_names_
        entry helper -- a stale cache must fail closed for storms_named the
        same way TestHurricaneCountToDateCache already proves for count."""
        from datetime import timedelta

        import weather_markets as wm

        stale_date = (
            wm.datetime.now(wm.UTC).date()
            - timedelta(days=wm._HURRICANE_COUNT_CACHE_MAX_AGE_DAYS + 1)
        ).isoformat()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "ATL": {
                        "date": stale_date,
                        "season_year": 2026,
                        "count": 0,
                        "storms_named": 5,
                    }
                }
            )
        )
        monkeypatch.setattr(wm, "HURRICANE_COUNT_TO_DATE_PATH", cache_path)
        assert wm._get_cached_storms_named_to_date("ATL", 2026) is None


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


# ═══════════════════════════════════════════════════════════════════════════
# Time-to-next-event model (backlog.txt "HURRICANE MARKETS" -- time-to-
# next-event model, 2026-08-07): KXNEXTHURDATE/KXNEXTCAT5HURDATE. See
# tests/test_hurricane_climatology.py for the underlying
# first_occurrence_day/next_event_outcomes math.
# ═══════════════════════════════════════════════════════════════════════════


def test_next_event_type_values_are_a_subset_of_climatology_thresholds():
    """Opus-review-caught: `_analyze_hurricane_next_event_trade` does a bare
    `hc.NEXT_EVENT_THRESHOLDS_KT[event_type]` subscript with no guard --
    every event_type value weather_markets._HURRICANE_NEXT_EVENT_TYPE can
    produce must have a matching key in hurricane_climatology.
    NEXT_EVENT_THRESHOLDS_KT, or a future 3rd series added to one dict but
    not the other raises KeyError inside analyze_trade(), which the scan
    loop's broad except-continue silently swallows."""
    import hurricane_climatology as hc
    import weather_markets as wm

    assert set(wm._HURRICANE_NEXT_EVENT_TYPE.values()) <= set(
        hc.NEXT_EVENT_THRESHOLDS_KT
    )


class TestIsHurricaneNextEventTicker:
    @pytest.mark.parametrize(
        "ticker",
        [
            "KXNEXTHURDATE-26DEC01-26SEP15",
            "KXNEXTCAT5HURDATE-26DEC01-26SEP01",
        ],
    )
    def test_matches_both_real_series(self, ticker):
        import weather_markets as wm

        assert wm.is_hurricane_next_event_ticker(ticker) is True

    @pytest.mark.parametrize(
        "ticker",
        [
            "KXNEXTHURDATE",  # bare series alone, no event suffix, still exact match
            "KXHURCTOT-26DEC01-T9",  # a different hurricane-count series
            "KXHURCAT-26FAUSTO-T5",  # per-storm category -- still unsupported
            "KXHIGHNY-26JUL20-T70",  # unrelated market entirely
        ],
    )
    def test_membership_is_series_exact(self, ticker):
        import weather_markets as wm

        expected = ticker == "KXNEXTHURDATE"
        assert wm.is_hurricane_next_event_ticker(ticker) is expected

    def test_still_caught_by_blanket_is_hurricane_ticker(self):
        """Both series contain "HUR" as a substring -- confirms the blanket
        guard's bypass extension in analyze_trade() is actually necessary,
        not dead code."""
        import weather_markets as wm

        assert wm.is_hurricane_ticker("KXNEXTHURDATE-26DEC01-26SEP15") is True
        assert wm.is_hurricane_ticker("KXNEXTCAT5HURDATE-26DEC01-26SEP01") is True


class TestParseHurricaneNextEventCondition:
    def _market(self, **overrides):
        base = {
            "ticker": "KXNEXTHURDATE-26DEC01-26SEP15",
            "close_time": "2026-09-15T03:59:00Z",
        }
        base.update(overrides)
        return base

    def test_hurricane_series_parses_correctly(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_next_event_condition(self._market())
        assert cond == {
            "type": "hurricane_next_event",
            "basin": "ATL",
            "event_type": "hurricane",
        }

    def test_cat5_series_parses_correctly(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_next_event_condition(
            self._market(
                ticker="KXNEXTCAT5HURDATE-26DEC01-26SEP01",
                close_time="2026-09-01T03:59:00Z",
            )
        )
        assert cond == {
            "type": "hurricane_next_event",
            "basin": "ATL",
            "event_type": "cat5_hurricane",
        }

    def test_no_kt_field_in_condition(self):
        """kt is deliberately derived downstream from event_type via
        hurricane_climatology.NEXT_EVENT_THRESHOLDS_KT, not carried in the
        condition dict -- avoids a second place that could drift out of
        sync with the single source of truth."""
        import weather_markets as wm

        cond = wm._parse_hurricane_next_event_condition(self._market())
        assert "kt" not in cond

    def test_missing_close_time_fails_closed(self, caplog):
        import weather_markets as wm

        cond = wm._parse_hurricane_next_event_condition(self._market(close_time=""))
        assert cond is None
        assert "missing/unparseable close_time" in caplog.text

    def test_unparseable_close_time_fails_closed(self):
        import weather_markets as wm

        cond = wm._parse_hurricane_next_event_condition(
            self._market(close_time="not-a-real-timestamp")
        )
        assert cond is None

    def test_non_next_event_ticker_returns_none_silently(self, caplog):
        import weather_markets as wm

        cond = wm._parse_hurricane_next_event_condition(
            {"ticker": "KXHIGHNY-26JUL20-T70"}
        )
        assert cond is None
        assert caplog.text == ""

    def test_dispatches_via_parse_market_condition(self):
        """End-to-end through the real dispatcher, confirms the branch is
        actually wired in."""
        import weather_markets as wm

        cond = wm._parse_market_condition(self._market())
        assert cond is not None
        assert cond["type"] == "hurricane_next_event"

    def test_degraded_market_fails_closed_at_dispatcher_not_fallthrough(self):
        """Same KXHURCAT-bug-class concern the hurricane-count branch's own
        test documents: a next-event-series ticker whose own close_time is
        unparseable must return None from _parse_market_condition itself,
        never fall through to the generic threshold parser below (this
        family has no floor_strike/strike_type at all, but a future Kalshi
        field change could still introduce one -- fail closed regardless)."""
        import weather_markets as wm

        degraded = self._market(close_time="garbage")
        cond = wm._parse_market_condition(degraded)
        assert cond is None


# ── _hurricane_next_event_gates_active ──────────────────────────────────────


class TestHurricaneNextEventGatesActive:
    """Mirrors TestHurricaneCountGatesActive's exact test shape -- own env
    var, own counter, kept fully separate from the count model's gate."""

    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", raising=False)
        monkeypatch.setattr(
            "tracker.count_settled_hurricane_next_event_predictions", lambda: 999
        )
        assert wm._hurricane_next_event_gates_active() is False

    def test_false_when_env_var_set_but_below_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", "1")
        monkeypatch.setattr(
            "tracker.count_settled_hurricane_next_event_predictions", lambda: 19
        )
        assert wm._hurricane_next_event_gates_active() is False

    def test_true_when_env_var_set_and_sample_floor_met(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", "1")
        monkeypatch.setattr(
            "tracker.count_settled_hurricane_next_event_predictions", lambda: 20
        )
        assert wm._hurricane_next_event_gates_active() is True

    def test_never_raises_on_count_failure(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", "1")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "tracker.count_settled_hurricane_next_event_predictions", _boom
        )
        assert wm._hurricane_next_event_gates_active() is False

    def test_independent_of_hurricane_count_gate(self, monkeypatch):
        """The two gates must not share state -- flipping the count model's
        gate/env var must not activate this one, and vice versa."""
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 999)
        monkeypatch.delenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", raising=False)
        assert wm._hurricane_count_gates_active() is True
        assert wm._hurricane_next_event_gates_active() is False


# ── _analyze_hurricane_next_event_trade (full dispatch, mocked climatology) ─


class TestAnalyzeHurricaneNextEventTrade:
    def _enriched(self, **overrides):
        base = {
            "ticker": "KXNEXTHURDATE-26DEC01-26SEP15",
            "close_time": "2026-09-15T03:59:00Z",
            # batch-59 item 3: the real open_time this whole ladder carries
            # (live-verified 2026-08-24) -- these markets roll over, so
            # issuance is ~3 months after the season's own start, and
            # occurred_this_season is now anchored to it.
            "open_time": "2026-08-06T14:00:00Z",
            "yes_bid_dollars": 0.40,
            "yes_ask_dollars": 0.45,
        }
        base.update(overrides)
        return base

    def _condition(self, **overrides):
        base = {
            "type": "hurricane_next_event",
            "basin": "ATL",
            "event_type": "hurricane",
        }
        base.update(overrides)
        return base

    def test_returns_none_when_hurdat2_unavailable(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms", lambda basin: None
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert result is None

    def test_returns_none_when_storms_list_is_empty(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr("hurricane_climatology.load_basin_storms", lambda basin: [])
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert result is None

    # -- batch-59 item 3: issuance anchoring -----------------------------
    # backlog.txt "hurricane occurred_this_season is season-scoped, not
    # issuance-scoped": a >=1 season count used to be enough to price the
    # market at 0.99, even when the storm predated the market's own issuance.
    # These markets roll over, so that is the common case, not the exception.
    #
    # Final shape (after opus review found the first attempt did not actually
    # change the outcome): the only per-event timing available is a SETTLEMENT
    # timestamp, which lags formation, so it can prove a storm predates
    # issuance but never that it followed it. Any count >= 1 therefore yields
    # NO SIGNAL rather than a probability.

    def _anchor_run(self, monkeypatch, *, count, last_event, enriched=None):
        """Drive _analyze_hurricane_next_event_trade with a controlled count /
        last-event pair, capturing whether the climatology branch was reached
        at all. Returns (result, captured)."""
        from datetime import UTC
        from datetime import datetime as _dt

        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: count
        )
        monkeypatch.setattr(
            wm, "_get_cached_last_hurricane_event_time", lambda basin, year: last_event
        )
        captured = {}

        def _fake_outcomes(storms, kt, target_month_day, *, as_of_month_day=None, **kw):
            captured["as_of_month_day"] = as_of_month_day
            return [True] * 9 + [False] * 6

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        result = wm._analyze_hurricane_next_event_trade(
            enriched if enriched is not None else self._enriched(),
            self._condition(),
            _dt(2026, 9, 15, tzinfo=UTC),
            39,
        )
        return result, captured

    @pytest.mark.allow_network
    def test_climatology_fallback_would_not_have_been_a_fail_safe(
        self, tmp_path, monkeypatch
    ):
        """The evidence behind returning no signal at all (opus review HIGH 1).

        The unconditional climatology this branch used to fall through to
        answers "did the season's FIRST hurricane occur on or before target",
        which for any late-season strike is ~always true. Measured against the
        repo's REAL HURDAT2 data, not a fixture: for the live ladder's own
        Sep 15 / Oct 1 / Dec 1 strikes it is 30/30 -> probability 0.99 with a
        ZERO-width CI, i.e. the same number the "confirmed" branch emits but
        with a tighter CI and therefore a LARGER Kelly stake. Pinned here so
        nobody reinstates that fallback believing it is conservative."""
        import hurricane_climatology as hc

        # The one test in this repo that genuinely needs the network, hence the
        # explicit @pytest.mark.allow_network above. It is pinned against the
        # REAL HURDAT2 distribution on purpose (see the docstring: a hand-built
        # fixture could be rigged to produce the very 0.99 this test exists to
        # expose), and data/ is gitignored -- so on a fresh CI checkout the
        # only way to have that data is to fetch it, exactly as this test did
        # before the default-deny guard existed. Blocking it instead would have
        # turned a real assertion into a permanent silent skip on CI
        # (opus-review-caught). On a dev machine the on-disk cache means no
        # fetch actually happens.
        #
        # What the above did NOT account for: fetch_hurdat2_raw CACHES what it
        # fetches, writing data/hurdat2_ATL.txt -- so on CI, where the fetch is
        # the whole point, the prod-data guard blocked the write and failed the
        # test. Allowing the network is not the same as allowing a production
        # write.
        #
        # Redirecting DATA_DIR alone would fix the write and break the rest:
        # a cold tmp_path means a dev machine loses its cache hit and starts
        # fetching on every run. That is precisely the regression
        # conftest.isolate_climatology_data_dir's docstring records for the
        # climatology archives. So seed tmp_path from the real cache when one
        # exists -- reads of data/ are permitted by the guard, only writes are
        # not. Both documented properties then survive: cache hit and zero
        # network on a dev machine, fetch-and-cache-to-tmp on CI.
        _real_cache = hc.DATA_DIR / "hurdat2_ATL.txt"
        if _real_cache.exists():
            (tmp_path / "hurdat2_ATL.txt").write_text(
                _real_cache.read_text(encoding="utf-8"), encoding="utf-8"
            )
        monkeypatch.setattr(hc, "DATA_DIR", tmp_path)

        storms = hc.load_basin_storms("ATL")
        if not storms:
            pytest.skip("HURDAT2 unavailable (no cache and no network)")
        kt = hc.NEXT_EVENT_THRESHOLDS_KT["hurricane"]
        for month_day in ((9, 15), (10, 1), (12, 1)):
            outcomes = hc.next_event_outcomes(storms, kt, month_day)
            assert hc.next_event_probability(outcomes) == pytest.approx(0.99)
            lo, hi = hc.bootstrap_ci_next_event(outcomes)
            assert hi - lo == pytest.approx(0.0), (
                f"target {month_day}: unconditional climatology CI is "
                "zero-width, so it is not a conservative fallback"
            )
        # Positive control: the same function DOES discriminate for an early
        # strike, so the 0.99 above is a real property of late targets rather
        # than this helper always returning 0.99.
        early = hc.next_event_outcomes(storms, kt, (9, 1))
        assert hc.next_event_probability(early) < 0.99

    def test_storm_confirmed_before_issuance_yields_no_signal(self, monkeypatch):
        """The entry's core case: a storm settled 2026-07-29, a week BEFORE
        this market's 2026-08-06 issuance. It cannot be this market's "next"
        hurricane, and no probability can be justified -- so no signal."""
        from datetime import UTC
        from datetime import datetime as _dt

        result, captured = self._anchor_run(
            monkeypatch, count=2, last_event=_dt(2026, 7, 29, 14, 45, tzinfo=UTC)
        )
        assert result is None
        assert "as_of_month_day" not in captured, (
            "must not reach the climatology branch at all"
        )

    def test_storm_settled_after_issuance_also_yields_no_signal(self, monkeypatch):
        """The unsound-positive case (opus review MEDIUM-HIGH 2): settlement
        lands days-to-weeks after formation and in batches, so "settled after
        issuance" does NOT establish "formed after issuance". Live-verified --
        the ATL name markets settled 2026-08-21, fifteen days after that
        ladder's 2026-08-06 open_time. Since this is the aggressive direction
        (0.99), it must not be taken on that evidence."""
        from datetime import UTC
        from datetime import datetime as _dt

        result, _ = self._anchor_run(
            monkeypatch, count=2, last_event=_dt(2026, 8, 21, 15, 40, tzinfo=UTC)
        )
        assert result is None

    def test_unanchorable_when_no_event_timestamp_is_cached(self, monkeypatch):
        """A cache written before last_yes_close_time existed reads None --
        unknown, not a negative -- and still yields no signal."""
        result, _ = self._anchor_run(monkeypatch, count=2, last_event=None)
        assert result is None

    def test_unanchorable_when_market_has_no_open_time(self, monkeypatch):
        """Symmetric gap on the market side."""
        from datetime import UTC
        from datetime import datetime as _dt

        enriched = self._enriched()
        del enriched["open_time"]
        result, _ = self._anchor_run(
            monkeypatch,
            count=2,
            last_event=_dt(2026, 8, 21, tzinfo=UTC),
            enriched=enriched,
        )
        assert result is None

    def test_count_of_one_takes_the_no_signal_path_not_the_false_branch(
        self, monkeypatch
    ):
        """count == 1 is the boundary between "nothing happened this season"
        (False -> conditional mode) and "something did" (no signal).

        Opus review finding M5: every other test used count in {0, 2, None},
        so mutating `_current_count < 1` to `< 2` survived the whole suite --
        and with count == 1 that mutant conditions climatology on "the
        season's first hurricane hasn't happened yet" when one demonstrably
        has. count == 1 is a live value today for the CPAC basin."""
        from datetime import UTC
        from datetime import datetime as _dt

        result, captured = self._anchor_run(
            monkeypatch, count=1, last_event=_dt(2026, 7, 29, tzinfo=UTC)
        )
        assert result is None
        assert "as_of_month_day" not in captured

    def test_zero_count_still_uses_conditional_mode_without_any_anchor(
        self, monkeypatch
    ):
        """Positive control for the anchoring branch: count==0 needs no
        issuance anchoring at all (nothing happened this season, so nothing
        happened since issuance either) and must still reach conditional mode
        with a real as_of_month_day — proving the new branch didn't swallow
        the pre-existing False path."""
        result, captured = self._anchor_run(monkeypatch, count=0, last_event=None)
        assert result is not None
        assert result["occurred_this_season"] is False
        assert captured["as_of_month_day"] is not None

    def test_not_yet_occurred_uses_conditional_mode(self, monkeypatch):
        """occurred_this_season=False (live cache confirms 0 so far) must
        pass a real as_of_month_day through to next_event_outcomes --
        conditional mode, not unconditional."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: 0
        )

        captured = {}

        def _fake_outcomes(storms, kt, target_month_day, *, as_of_month_day=None, **kw):
            captured["as_of_month_day"] = as_of_month_day
            captured["kt"] = kt
            captured["target_month_day"] = target_month_day
            return [True] * 9 + [False] * 6  # 15 outcomes (meets the floor), 60% True

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert result is not None
        assert captured["as_of_month_day"] is not None  # conditional mode
        assert captured["kt"] == 64  # "hurricane" event_type
        # Midnight UTC Sep 15 is 8pm EDT Sep 14 -- target_month_day is ET-derived.
        assert captured["target_month_day"] == (9, 14)
        assert result["forecast_prob"] == 0.6
        assert result["method"] == "hurricane_next_event_climatology_tilted"
        assert result["occurred_this_season"] is False
        assert result["n_members"] == 15

    def test_unknown_cache_state_uses_unconditional_mode_not_assumed_false(
        self, monkeypatch
    ):
        """A missing/stale cache (occurred_this_season=None, genuinely
        UNKNOWN) must run unconditional mode, not silently assume "hasn't
        happened yet" -- the exact stale-cache "flips a probability with no
        warning" failure mode this codebase already fixed once for the
        count model's own current-count cache."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )

        captured = {}

        def _fake_outcomes(storms, kt, target_month_day, *, as_of_month_day=None, **kw):
            captured["as_of_month_day"] = as_of_month_day
            return [True] * 30

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert captured["as_of_month_day"] is None  # unconditional mode
        assert result["method"] == "hurricane_next_event_climatology"
        assert result["occurred_this_season"] is None

    def test_as_of_month_day_uses_et_not_utc_during_rollover_window(self, monkeypatch):
        """LOW/INFO sweep item (a): as_of_month_day ("today") must be
        derived from the SAME America/New_York conversion target_month_day
        already uses, not raw UTC "now" -- otherwise 20:00-24:00 ET (already
        the next UTC calendar day) makes as_of_month_day one day ahead of
        target_month_day's own reference frame for the identical moment.

        Frozen instant: 2026-09-14 23:30 UTC = 2026-09-14 19:30 EDT. UTC's
        date is Sep 14 too here, so pick a moment where UTC has already
        rolled to Sep 15 while ET is still Sep 14 evening: 2026-09-15 02:30
        UTC = 2026-09-14 22:30 EDT.
        """
        from datetime import UTC
        from datetime import datetime as _dt

        import hurricane_climatology as hc
        import weather_markets as wm

        class _FrozenDT(_dt):
            @classmethod
            def now(cls, tz=None):
                _instant = _dt(2026, 9, 15, 2, 30, tzinfo=UTC)
                if tz is None:
                    return _instant.replace(tzinfo=None)
                return _instant.astimezone(tz)

        monkeypatch.setattr(wm, "datetime", _FrozenDT)
        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: 0
        )

        captured = {}

        def _fake_outcomes(storms, kt, target_month_day, *, as_of_month_day=None, **kw):
            captured["as_of_month_day"] = as_of_month_day
            return [True] * 15

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)

        wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 39
        )
        # UTC "now" is Sep 15; ET "now" (the real local wall-clock moment)
        # is still Sep 14 evening -- must reflect ET, not UTC.
        assert captured["as_of_month_day"] == (9, 14), (
            f"expected ET-derived (9, 14), got {captured['as_of_month_day']} "
            f"-- as_of_month_day is using raw UTC 'now' instead of the ET "
            f"conversion target_month_day already applies"
        )

    def test_cat5_never_calls_the_count_to_date_cache(self, monkeypatch):
        """cat5_hurricane has no live "already occurred" signal in this
        pass -- must never call _get_cached_hurricane_count_to_date at all,
        confirmed scoped exactly like major_hurricane/tropical_storm are for
        the count model."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        calls = []

        def _fail_if_called(basin, year):
            calls.append((basin, year))
            return 5

        monkeypatch.setattr(wm, "_get_cached_hurricane_count_to_date", _fail_if_called)
        monkeypatch.setattr(hc, "next_event_outcomes", lambda *a, **k: [False] * 20)
        from datetime import UTC
        from datetime import datetime as _dt

        wm._analyze_hurricane_next_event_trade(
            self._enriched(),
            self._condition(event_type="cat5_hurricane"),
            _dt(2026, 9, 1, tzinfo=UTC),
            25,
        )
        assert calls == []

    def test_cat5_kt_derived_correctly(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        captured = {}

        def _fake_outcomes(storms, kt, target_month_day, **kw):
            captured["kt"] = kt
            return [False] * 20

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        wm._analyze_hurricane_next_event_trade(
            self._enriched(),
            self._condition(event_type="cat5_hurricane"),
            _dt(2026, 9, 1, tzinfo=UTC),
            25,
        )
        assert captured["kt"] == 137

    def test_recommended_side_follows_edge_direction(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(hc, "next_event_outcomes", lambda *a, **k: [True] * 20)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert result["forecast_prob"] == 0.99
        assert result["recommended_side"] == "yes"  # cheap market, high prob

    def test_exposure_cap_key_matches_count_model(self, monkeypatch):
        """Deliberately the SAME "HUR_<basin>" key as the season-count
        model, not a separate one -- correlated Atlantic storm activity must
        cap together across both hurricane sub-models."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(hc, "next_event_outcomes", lambda *a, **k: [True] * 20)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert result["city"] == "HUR_ATL"

    def test_unanimous_outcomes_produce_a_real_nonzero_kelly(self, monkeypatch):
        """Opus-review-caught (2026-08-07, HIGH), verified end-to-end at the
        analyzer level (not just hurricane_climatology's own unit test): a
        unanimous [True]*N outcome set must NOT collapse ci_adjusted_kelly
        to exactly 0.0 -- before the [0.01,0.99] clamp was added to
        bootstrap_ci_next_event, this was the common case (e.g. every recent
        Atlantic season has a hurricane by mid-September) and silently
        blocked every real order for the model's own highest-confidence
        signals, plus permanently froze the settled-prediction counter at 0
        since shadow logging shares the same size-then-log validator."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(hc, "next_event_outcomes", lambda *a, **k: [True] * 30)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(
                yes_bid_dollars=0.30, yes_ask_dollars=0.35
            ),  # cheap enough for a real edge
            self._condition(),
            _dt(2026, 9, 15, tzinfo=UTC),
            39,
        )
        assert result["ci_low"] == result["ci_high"] == 0.99
        assert result["ci_adjusted_kelly"] > 0.0

    def test_conditional_mode_falls_back_to_unconditional_below_sample_floor(
        self, monkeypatch
    ):
        """Opus-review-caught (2026-08-07, HIGH): occurred_this_season=False
        (live-confirmed "not yet happened") alone is not sufficient to trust
        conditional mode -- if the eligible set next_event_outcomes actually
        returns is too small (<15, matching bootstrap_ci_next_event's own
        floor), the analyzer must fall back to the unconditional baseline
        rather than compute (or shadow-log) a full-strength signal off a
        handful of data points."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: 0
        )

        calls = []

        def _fake_outcomes(storms, kt, target_month_day, *, as_of_month_day=None, **kw):
            calls.append(as_of_month_day)
            if as_of_month_day is not None:
                return [True, True, False]  # only 3 eligible years -- below floor
            return [True] * 30

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert len(calls) == 2  # conditional attempt, then unconditional fallback
        assert calls[0] is not None  # first call was conditional
        assert calls[1] is None  # fallback call was unconditional
        assert result["n_members"] == 30
        assert result["method"] == "hurricane_next_event_climatology"  # not "_tilted"

    def test_conditional_mode_kept_when_sample_floor_met(self, monkeypatch):
        """The fallback in the test above must not fire when the eligible
        set is actually large enough to trust."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: 0
        )

        calls = []

        def _fake_outcomes(storms, kt, target_month_day, *, as_of_month_day=None, **kw):
            calls.append(as_of_month_day)
            return [True] * 12 + [False] * 3  # exactly 15 -- meets the floor

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_hurricane_next_event_trade(
            self._enriched(), self._condition(), _dt(2026, 9, 15, tzinfo=UTC), 39
        )
        assert len(calls) == 1  # no fallback call
        assert result["n_members"] == 15
        assert result["method"] == "hurricane_next_event_climatology_tilted"

    def test_target_month_day_uses_eastern_time_not_utc(self, monkeypatch):
        """Opus-review-caught (2026-08-07): close_dt is UTC, but Kalshi's
        "Before <date>" wording is an ET calendar date -- close_time
        "2026-09-15T03:59Z" (23:59 ET on Sep 14) must resolve to target
        (9, 14), not the naive UTC (9, 15), or the model counts a storm
        crossing threshold anywhere in the Sep-15-UTC day as a YES when
        ~20 of those 24 hours are actually past the real ET cutoff."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_hurricane_count_to_date", lambda basin, year: None
        )
        captured = {}

        def _fake_outcomes(storms, kt, target_month_day, **kw):
            captured["target_month_day"] = target_month_day
            return [True] * 30

        monkeypatch.setattr(hc, "next_event_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        wm._analyze_hurricane_next_event_trade(
            self._enriched(close_time="2026-09-15T03:59:00Z"),
            self._condition(),
            _dt(2026, 9, 15, 3, 59, tzinfo=UTC),
            39,
        )
        assert captured["target_month_day"] == (9, 14)


class TestHurricaneNextEventConditionConfidence:
    def test_has_its_own_entry_not_the_max_default(self):
        """Opus-review-caught: this key was originally missing from
        _CONDITION_CONFIDENCE entirely, so edge_confidence()/_price_and_size's
        `.get(condition_type, 1.0)` fallback silently gave the least-
        validated model in the codebase the MAXIMUM confidence multiplier --
        on par with same-day temperature markets and above the sibling count
        model's own deliberately-low 0.55."""
        import weather_markets as wm

        assert "hurricane_next_event" in wm._CONDITION_CONFIDENCE
        assert (
            wm._CONDITION_CONFIDENCE["hurricane_next_event"]
            < wm._CONDITION_CONFIDENCE["hurricane_count"]
        )


# ── check_position_limits() / cmd_order() guard conditional (mirrors
#    TestCheckPositionLimitsHurricaneCountConditional/
#    TestCmdOrderHurricaneCountGuard exactly) ────────────────────────────────


class TestCheckPositionLimitsHurricaneNextEventConditional:
    def test_still_blocks_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits(
            "KXNEXTHURDATE-26DEC01-26SEP15", qty=1, price=0.10
        )
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()

    def test_does_not_block_when_gate_active(self, monkeypatch, tmp_path):
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
                        "weather_markets._hurricane_next_event_gates_active",
                        lambda: True,
                    )
                    result = paper.check_position_limits(
                        "KXNEXTHURDATE-26DEC01-26SEP15", qty=1, price=0.10
                    )
        assert result["ok"] is True

    def test_other_hurricane_shapes_still_unconditionally_blocked(self, monkeypatch):
        import paper

        monkeypatch.setattr(
            "weather_markets._hurricane_next_event_gates_active", lambda: True
        )
        result = paper.check_position_limits("KXHURCAT-26FAUSTO-T5", qty=1, price=0.10)
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()

    def test_count_model_gate_state_does_not_affect_this_one(self, monkeypatch):
        """The two hurricane sub-models' gates must not cross-activate each
        other."""
        import paper

        monkeypatch.setattr(
            "weather_markets._hurricane_count_gates_active", lambda: True
        )
        monkeypatch.setattr(
            "weather_markets._hurricane_next_event_gates_active", lambda: False
        )
        result = paper.check_position_limits(
            "KXNEXTHURDATE-26DEC01-26SEP15", qty=1, price=0.10
        )
        assert result["ok"] is False


class TestCmdOrderHurricaneNextEventGuard:
    def test_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", raising=False)
        main.cmd_order(
            None, "buy", ["KXNEXTHURDATE-26DEC01-26SEP15", "yes", "1", "0.10"]
        )
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "time-to-next-event" in out.lower()
        assert "HURRICANE_NEXT_EVENT_TRADING_ENABLED" in out

    def test_does_not_refuse_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._hurricane_next_event_gates_active", lambda: True)
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_order(
                None, "buy", ["KXNEXTHURDATE-26DEC01-26SEP15", "yes", "1", "0.10"]
            )
        except Exception:
            pass  # downstream failure (no live market) is expected/irrelevant here
        assert not any(
            "hurricane time-to-next-event markets are shadow-only" in p for p in printed
        )

    def test_other_hurricane_shapes_still_unconditionally_refused(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._hurricane_next_event_gates_active", lambda: True)
        main.cmd_order(None, "buy", ["KXHURCAT-26FAUSTO-T5", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "hurricane markets are not supported yet" in out


class TestQuickPaperBuyAndCmdPaperHurricaneNextEventGuards:
    """Opus-review-caught gap: only cmd_order and check_position_limits had
    direct test coverage for the next-event family's guards -- _quick_
    paper_buy and cmd_paper's own direct refuse-outright checks (added
    alongside cmd_order's, for the same "check_position_limits()'s own
    exception path deliberately fails open" reason rain/snow/hurricane-
    count's own guards already document) were untested. Mirrors
    test_rain_markets.py's TestQuickPaperBuyAndCmdPaperRainGuards exactly.
    cmd_today's own "[P] Place" path has the identical guard too but no
    existing test anywhere in this codebase reaches that function for ANY
    market family (rain/snow/hurricane-count included) -- building a novel
    test harness for it is out of scope here; this closes the two sites
    that already have an established pattern to mirror."""

    def test_quick_paper_buy_refuses_when_gate_inactive(self, monkeypatch, capsys):
        from unittest.mock import MagicMock

        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", raising=False)
        mock_client = MagicMock()
        _inputs = iter(["KXNEXTHURDATE-26DEC01-26SEP15"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "time-to-next-event" in out.lower()
        assert "HURRICANE_NEXT_EVENT_TRADING_ENABLED" in out
        mock_client.get_market.assert_not_called()

    def test_quick_paper_buy_does_not_refuse_when_gate_active(self, monkeypatch):
        from unittest.mock import MagicMock

        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._hurricane_next_event_gates_active", lambda: True)
        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("no real market in test")
        _inputs = iter(["KXNEXTHURDATE-26DEC01-26SEP15", "q"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main._quick_paper_buy(mock_client)
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)

    def test_cmd_paper_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", raising=False)

        main.cmd_paper(["buy", "KXNEXTHURDATE-26DEC01-26SEP15", "yes", "0.10", "1"])

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "time-to-next-event" in out.lower()
        assert "HURRICANE_NEXT_EVENT_TRADING_ENABLED" in out

    def test_cmd_paper_does_not_refuse_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._hurricane_next_event_gates_active", lambda: True)

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_paper(["buy", "KXNEXTHURDATE-26DEC01-26SEP15", "yes", "0.10", "1"])
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)


# ═══════════════════════════════════════════════════════════════════════════
# Storm-order model (backlog.txt "HURRICANE MARKETS" -- storm-order model,
# 2026-08-07): KXFIRSTHURRICANE. See tests/test_hurricane_climatology.py for
# the underlying first_hurricane_position/first_hurricane_position_outcomes
# math.
# ═══════════════════════════════════════════════════════════════════════════


class TestIsStormOrderTicker:
    def test_matches_the_real_series(self):
        import weather_markets as wm

        assert wm.is_storm_order_ticker("KXFIRSTHURRICANE-26DEC01ATL-WIL") is True

    @pytest.mark.parametrize(
        "ticker",
        [
            "KXFIRSTHURRICANE",  # bare series alone, no event suffix, still exact match
            "KXHURCTOT-26DEC01-T9",  # a hurricane-count series
            "KXHURCAT-26FAUSTO-T5",  # per-storm category -- still unsupported
            "KXNEXTHURDATE-26DEC01-26SEP15",  # sibling time-to-next-event series
            "KXHIGHNY-26JUL20-T70",  # unrelated market entirely
        ],
    )
    def test_membership_is_series_exact(self, ticker):
        import weather_markets as wm

        expected = ticker == "KXFIRSTHURRICANE"
        assert wm.is_storm_order_ticker(ticker) is expected

    def test_still_caught_by_blanket_is_hurricane_ticker(self):
        """Confirms the blanket guard's bypass extension in analyze_trade()
        is actually necessary, not dead code."""
        import weather_markets as wm

        assert wm.is_hurricane_ticker("KXFIRSTHURRICANE-26DEC01ATL-WIL") is True


class TestParseStormOrderCondition:
    def _market(self, **overrides):
        base = {
            "ticker": "KXFIRSTHURRICANE-26DEC01ATL-ART",
            "close_time": "2026-12-01T15:00:00Z",
            "custom_strike": {"storm": "Arthur"},
        }
        base.update(overrides)
        return base

    def test_parses_correctly(self):
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(self._market())
        assert cond == {
            "type": "storm_order",
            "basin": "ATL",
            "storm_name": "Arthur",
            "position": 1,
            "season_year": 2026,
        }

    def test_position_matches_the_last_name_in_the_list(self):
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(
            self._market(
                ticker="KXFIRSTHURRICANE-26DEC01ATL-WIL",
                custom_strike={"storm": "Wilfred"},
            )
        )
        assert cond["position"] == 21

    def test_missing_custom_strike_fails_closed(self, caplog):
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(self._market(custom_strike=None))
        assert cond is None
        assert "missing/unparseable custom_strike.storm" in caplog.text

    def test_empty_storm_name_fails_closed(self):
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(
            self._market(custom_strike={"storm": ""})
        )
        assert cond is None

    def test_unknown_storm_name_fails_closed(self, caplog):
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(
            self._market(custom_strike={"storm": "NotARealName"})
        )
        assert cond is None
        assert "not found in" in caplog.text

    def test_unknown_season_year_fails_closed(self, caplog):
        """A season_year not yet in _ATLANTIC_STORM_NAMES_BY_SEASON must
        never silently guess a position from an unrelated year's list."""
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(
            self._market(
                ticker="KXFIRSTHURRICANE-99DEC01ATL-ART",
                close_time="2099-12-01T15:00:00Z",
            )
        )
        assert cond is None
        assert "no known Atlantic name list" in caplog.text

    def test_season_year_mismatch_with_close_time_fails_closed(self, caplog):
        """Same cross-check discipline _parse_hurricane_count_condition
        established: a ticker-derived season_year that doesn't match
        close_time's real year by more than 1 is untrustworthy."""
        import weather_markets as wm

        cond = wm._parse_storm_order_condition(
            self._market(close_time="2030-12-01T15:00:00Z")
        )
        assert cond is None
        assert "doesn't match close_time year" in caplog.text

    def test_non_storm_order_ticker_returns_none_silently(self, caplog):
        import weather_markets as wm

        cond = wm._parse_storm_order_condition({"ticker": "KXHIGHNY-26JUL20-T70"})
        assert cond is None
        assert caplog.text == ""

    def test_dispatches_via_parse_market_condition(self):
        """End-to-end through the real dispatcher, confirms the branch is
        actually wired in."""
        import weather_markets as wm

        cond = wm._parse_market_condition(self._market())
        assert cond is not None
        assert cond["type"] == "storm_order"

    def test_degraded_market_fails_closed_at_dispatcher_not_fallthrough(self):
        """Same KXHURCAT-bug-class concern the sibling branches' own tests
        document: a storm-order-series ticker with an unparseable
        custom_strike must return None from _parse_market_condition itself,
        never fall through to the generic threshold parser below."""
        import weather_markets as wm

        degraded = self._market(custom_strike=None)
        cond = wm._parse_market_condition(degraded)
        assert cond is None


class TestStormOrderGatesActive:
    """Mirrors TestHurricaneNextEventGatesActive's exact test shape -- own
    env var, own counter, kept fully separate from both sibling models'
    gates."""

    def test_false_when_env_var_unset(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.delenv("STORM_ORDER_TRADING_ENABLED", raising=False)
        monkeypatch.setattr(
            "tracker.count_settled_storm_order_predictions", lambda: 999
        )
        assert wm._storm_order_gates_active() is False

    def test_false_when_env_var_set_but_below_sample_floor(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("STORM_ORDER_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_storm_order_predictions", lambda: 19)
        assert wm._storm_order_gates_active() is False

    def test_true_when_env_var_set_and_sample_floor_met(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("STORM_ORDER_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_storm_order_predictions", lambda: 20)
        assert wm._storm_order_gates_active() is True

    def test_never_raises_on_count_failure(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setenv("STORM_ORDER_TRADING_ENABLED", "1")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("tracker.count_settled_storm_order_predictions", _boom)
        assert wm._storm_order_gates_active() is False

    def test_independent_of_sibling_hurricane_gates(self, monkeypatch):
        """This gate must not share state with either sibling model's --
        flipping the count or next-event model's gate/env var must not
        activate this one, and vice versa."""
        import weather_markets as wm

        monkeypatch.setenv("HURRICANE_TRADING_ENABLED", "1")
        monkeypatch.setattr("tracker.count_settled_hurricane_predictions", lambda: 999)
        monkeypatch.setenv("HURRICANE_NEXT_EVENT_TRADING_ENABLED", "1")
        monkeypatch.setattr(
            "tracker.count_settled_hurricane_next_event_predictions", lambda: 999
        )
        monkeypatch.delenv("STORM_ORDER_TRADING_ENABLED", raising=False)
        assert wm._hurricane_count_gates_active() is True
        assert wm._hurricane_next_event_gates_active() is True
        assert wm._storm_order_gates_active() is False


# ── _analyze_storm_order_trade (full dispatch, mocked climatology) ─────────


class TestAnalyzeStormOrderTrade:
    def _enriched(self, **overrides):
        base = {
            "ticker": "KXFIRSTHURRICANE-26DEC01ATL-ART",
            "close_time": "2026-12-01T15:00:00Z",
            "yes_bid_dollars": 0.10,
            "yes_ask_dollars": 0.15,
        }
        base.update(overrides)
        return base

    def _condition(self, **overrides):
        base = {
            "type": "storm_order",
            "basin": "ATL",
            "storm_name": "Arthur",
            "position": 1,
            "season_year": 2026,
        }
        base.update(overrides)
        return base

    def test_returns_none_when_hurdat2_unavailable(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms", lambda basin: None
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 116
        )
        assert result is None

    def test_returns_none_when_storms_list_is_empty(self, monkeypatch):
        import weather_markets as wm

        monkeypatch.setattr("hurricane_climatology.load_basin_storms", lambda basin: [])
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 116
        )
        assert result is None

    def test_unknown_cache_state_uses_unconditional_mode_not_assumed_zero(
        self, monkeypatch
    ):
        """A missing/stale storms-named-to-date cache (None, genuinely
        UNKNOWN) must run the unconditional distribution, not silently
        assume 0 names used so far -- unlike next_event, this market family
        stays open for the whole season even after an individual name's own
        storm has already come and gone, so silently under-counting M would
        keep assigning real probability mass to already-ruled-out
        positions, not just produce a less-sharp signal."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: None
        )

        captured = {}

        def _fake_outcomes(storms, target_position, storms_named_so_far, **kw):
            captured["storms_named_so_far"] = storms_named_so_far
            return [True] * 30

        monkeypatch.setattr(hc, "first_hurricane_position_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 116
        )
        assert captured["storms_named_so_far"] == 0  # the unconditional identity
        assert result["method"] == "storm_order_climatology"
        assert result["storms_named_so_far"] == 0

    def test_known_zero_uses_unconditional_mode(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 0
        )

        captured = {}

        def _fake_outcomes(storms, target_position, storms_named_so_far, **kw):
            captured["storms_named_so_far"] = storms_named_so_far
            return [True] * 30

        monkeypatch.setattr(hc, "first_hurricane_position_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 116
        )
        assert captured["storms_named_so_far"] == 0
        assert result["method"] == "storm_order_climatology"

    def test_known_nonzero_uses_conditional_mode(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 3
        )

        captured = {}

        def _fake_outcomes(storms, target_position, storms_named_so_far, **kw):
            captured["storms_named_so_far"] = storms_named_so_far
            return [True] * 9 + [False] * 6  # 15 outcomes (meets the floor), 60% True

        monkeypatch.setattr(hc, "first_hurricane_position_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=5),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert captured["storms_named_so_far"] == 3
        assert result["forecast_prob"] == 0.6
        assert result["method"] == "storm_order_climatology_tilted"
        assert result["storms_named_so_far"] == 3
        assert result["n_members"] == 15

    def test_position_already_eliminated_short_circuits_to_near_certain_no(
        self, monkeypatch
    ):
        """Opus-review-caught (2026-08-07, HIGH), 2nd round: when position
        <= storms_named_so_far, this name's own KXHURRICANENAMES market has
        ALREADY settled "no" (see refresh_hurricane_count_to_date's own
        docstring: settlement requires NHC to have fully stopped reporting
        on that storm) -- the market is CONCLUSIVELY resolved, mirroring
        _analyze_hurricane_next_event_trade's own occurred_this_season=True
        short-circuit. Must skip the bootstrap entirely (not run it and
        then discard the result via the sample-floor fallback, which --
        measured against real Atlantic data -- fires for essentially every
        M>=2 and would otherwise silently reset an eliminated position back
        to its full unconditional probability)."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 5
        )

        def _boom(*a, **k):
            raise AssertionError(
                "bootstrap must not run for an already-eliminated position"
            )

        monkeypatch.setattr(hc, "first_hurricane_position_outcomes", _boom)
        from datetime import UTC
        from datetime import datetime as _dt

        # position=3 <= storms_named_so_far=5 -- this name's slot has
        # already come and gone without becoming a hurricane.
        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=3),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert result is not None
        assert result["forecast_prob"] == 0.01
        assert result["ci_low"] == result["ci_high"] == 0.01
        assert result["method"] == "storm_order_confirmed_not_first"
        assert result["n_members"] == 0
        assert result["storms_named_so_far_raw"] == 5

    def test_position_equal_to_storms_named_so_far_is_also_eliminated(
        self, monkeypatch
    ):
        """Boundary check: position == storms_named_so_far (not just <)
        must also short-circuit -- that name's own market has settled too."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 3
        )
        monkeypatch.setattr(
            hc,
            "first_hurricane_position_outcomes",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("must not run for position == M")
            ),
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=3),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert result["method"] == "storm_order_confirmed_not_first"

    def test_position_still_live_does_not_short_circuit(self, monkeypatch):
        """The converse boundary: position > storms_named_so_far must reach
        the normal bootstrap path, not the short-circuit."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 3
        )
        monkeypatch.setattr(
            hc, "first_hurricane_position_outcomes", lambda *a, **k: [True] * 20
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=4),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert result["method"] != "storm_order_confirmed_not_first"

    def test_unknown_storms_named_never_short_circuits(self, monkeypatch):
        """A missing/stale storms-named-to-date cache (None) must never
        trigger the short-circuit, even for position=1 -- "unknown" is not
        "eliminated"."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(
            hc, "first_hurricane_position_outcomes", lambda *a, **k: [True] * 20
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=1),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert result["method"] != "storm_order_confirmed_not_first"
        assert result["storms_named_so_far_raw"] is None

    def test_conditional_mode_falls_back_to_unconditional_below_sample_floor(
        self, monkeypatch
    ):
        """Same opus-review-caught pattern next_event's own test documents:
        a known, non-zero storms_named_so_far alone is not sufficient to
        trust conditional mode -- if the eligible set actually returned is
        too small (<15, matching bootstrap_ci_next_event's own floor), the
        analyzer must fall back to the unconditional baseline."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 3
        )

        calls = []

        def _fake_outcomes(storms, target_position, storms_named_so_far, **kw):
            calls.append(storms_named_so_far)
            if storms_named_so_far != 0:
                return [True, True, False]  # only 3 eligible years -- below floor
            return [True] * 30

        monkeypatch.setattr(hc, "first_hurricane_position_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        # position=5 (> storms_named_so_far=3) so the new "definitively
        # eliminated" short-circuit (opus-review-caught, 2026-08-07, HIGH,
        # 2nd round) does NOT intercept this case -- this test is
        # specifically about a still-LIVE position's sample-floor fallback.
        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=5),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert calls == [3, 0]  # conditional attempt, then unconditional fallback
        assert result["n_members"] == 30
        assert result["method"] == "storm_order_climatology"  # not "_tilted"
        assert result["storms_named_so_far"] == 0

    def test_conditional_mode_kept_when_sample_floor_met(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: 3
        )

        calls = []

        def _fake_outcomes(storms, target_position, storms_named_so_far, **kw):
            calls.append(storms_named_so_far)
            return [True] * 12 + [False] * 3  # exactly 15 -- meets the floor

        monkeypatch.setattr(hc, "first_hurricane_position_outcomes", _fake_outcomes)
        from datetime import UTC
        from datetime import datetime as _dt

        # position=5 (> storms_named_so_far=3), same short-circuit-avoidance
        # reasoning as the test above.
        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(position=5),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert calls == [3]  # no fallback call
        assert result["n_members"] == 15
        assert result["method"] == "storm_order_climatology_tilted"

    def test_recommended_side_follows_edge_direction(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(
            hc, "first_hurricane_position_outcomes", lambda *a, **k: [True] * 20
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 116
        )
        assert result["forecast_prob"] == 0.99
        assert result["recommended_side"] == "yes"  # cheap market, high prob

    def test_exposure_cap_key_matches_sibling_models(self, monkeypatch):
        """Deliberately the SAME "HUR_<basin>" key as both sibling hurricane
        models, not a separate one -- correlated Atlantic storm activity
        must cap together across all 3 hurricane sub-models."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(
            hc, "first_hurricane_position_outcomes", lambda *a, **k: [True] * 20
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(), self._condition(), _dt(2026, 12, 1, tzinfo=UTC), 116
        )
        assert result["city"] == "HUR_ATL"

    def test_unanimous_outcomes_produce_a_real_nonzero_kelly(self, monkeypatch):
        """Same clamp-verification-at-the-analyzer-level next_event's own
        test documents: a unanimous [True]*N outcome set must not collapse
        ci_adjusted_kelly to exactly 0.0."""
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(
            hc, "first_hurricane_position_outcomes", lambda *a, **k: [True] * 30
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(yes_bid_dollars=0.30, yes_ask_dollars=0.35),
            self._condition(),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert result["ci_low"] == result["ci_high"] == 0.99
        assert result["ci_adjusted_kelly"] > 0.0

    def test_condition_fields_passed_through_to_diagnostics(self, monkeypatch):
        import hurricane_climatology as hc
        import weather_markets as wm

        monkeypatch.setattr(
            "hurricane_climatology.load_basin_storms",
            lambda basin: [{"year": 2020, "basin": "AL"}],
        )
        monkeypatch.setattr(
            wm, "_get_cached_storms_named_to_date", lambda basin, year: None
        )
        monkeypatch.setattr(
            hc, "first_hurricane_position_outcomes", lambda *a, **k: [False] * 20
        )
        from datetime import UTC
        from datetime import datetime as _dt

        result = wm._analyze_storm_order_trade(
            self._enriched(),
            self._condition(storm_name="Josephine", position=10),
            _dt(2026, 12, 1, tzinfo=UTC),
            116,
        )
        assert result["storm_name"] == "Josephine"
        assert result["position"] == 10
        assert result["basin"] == "ATL"


class TestStormOrderConditionConfidence:
    def test_has_its_own_entry_not_the_max_default(self):
        """Same opus-review-caught concern the sibling next_event entry's
        own test documents: this key must not be missing from
        _CONDITION_CONFIDENCE, which would silently give the least-
        validated model in the codebase the MAXIMUM confidence multiplier."""
        import weather_markets as wm

        assert "storm_order" in wm._CONDITION_CONFIDENCE
        assert (
            wm._CONDITION_CONFIDENCE["storm_order"]
            < wm._CONDITION_CONFIDENCE["hurricane_count"]
        )


# ── check_position_limits() / cmd_order() guard conditional (mirrors
#    TestCheckPositionLimitsHurricaneNextEventConditional/
#    TestCmdOrderHurricaneNextEventGuard exactly) ────────────────────────────


class TestCheckPositionLimitsStormOrderConditional:
    def test_still_blocks_when_gate_inactive(self, monkeypatch):
        import paper

        monkeypatch.delenv("STORM_ORDER_TRADING_ENABLED", raising=False)
        result = paper.check_position_limits(
            "KXFIRSTHURRICANE-26DEC01ATL-ART", qty=1, price=0.10
        )
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()

    def test_does_not_block_when_gate_active(self, monkeypatch, tmp_path):
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
                        "weather_markets._storm_order_gates_active",
                        lambda: True,
                    )
                    result = paper.check_position_limits(
                        "KXFIRSTHURRICANE-26DEC01ATL-ART", qty=1, price=0.10
                    )
        assert result["ok"] is True

    def test_other_hurricane_shapes_still_unconditionally_blocked(self, monkeypatch):
        import paper

        monkeypatch.setattr("weather_markets._storm_order_gates_active", lambda: True)
        result = paper.check_position_limits("KXHURCAT-26FAUSTO-T5", qty=1, price=0.10)
        assert result["ok"] is False
        assert "hurricane" in result["reason"].lower()

    def test_sibling_gate_state_does_not_affect_this_one(self, monkeypatch):
        """None of the 3 hurricane sub-models' gates must cross-activate
        each other."""
        import paper

        monkeypatch.setattr(
            "weather_markets._hurricane_count_gates_active", lambda: True
        )
        monkeypatch.setattr(
            "weather_markets._hurricane_next_event_gates_active", lambda: True
        )
        monkeypatch.setattr("weather_markets._storm_order_gates_active", lambda: False)
        result = paper.check_position_limits(
            "KXFIRSTHURRICANE-26DEC01ATL-ART", qty=1, price=0.10
        )
        assert result["ok"] is False


class TestCmdOrderStormOrderGuard:
    def test_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("STORM_ORDER_TRADING_ENABLED", raising=False)
        main.cmd_order(
            None, "buy", ["KXFIRSTHURRICANE-26DEC01ATL-ART", "yes", "1", "0.10"]
        )
        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "storm-order" in out.lower()
        assert "STORM_ORDER_TRADING_ENABLED" in out

    def test_does_not_refuse_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._storm_order_gates_active", lambda: True)
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_order(
                None, "buy", ["KXFIRSTHURRICANE-26DEC01ATL-ART", "yes", "1", "0.10"]
            )
        except Exception:
            pass  # downstream failure (no live market) is expected/irrelevant here
        assert not any(
            "hurricane storm-order markets are shadow-only" in p for p in printed
        )

    def test_other_hurricane_shapes_still_unconditionally_refused(
        self, monkeypatch, capsys
    ):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._storm_order_gates_active", lambda: True)
        main.cmd_order(None, "buy", ["KXHURCAT-26FAUSTO-T5", "yes", "1", "0.10"])
        out = capsys.readouterr().out
        assert "hurricane markets are not supported yet" in out


class TestQuickPaperBuyAndCmdPaperStormOrderGuards:
    """Mirrors TestQuickPaperBuyAndCmdPaperHurricaneNextEventGuards exactly."""

    def test_quick_paper_buy_refuses_when_gate_inactive(self, monkeypatch, capsys):
        from unittest.mock import MagicMock

        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("STORM_ORDER_TRADING_ENABLED", raising=False)
        mock_client = MagicMock()
        _inputs = iter(["KXFIRSTHURRICANE-26DEC01ATL-ART"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        main._quick_paper_buy(mock_client)

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "storm-order" in out.lower()
        assert "STORM_ORDER_TRADING_ENABLED" in out
        mock_client.get_market.assert_not_called()

    def test_quick_paper_buy_does_not_refuse_when_gate_active(self, monkeypatch):
        from unittest.mock import MagicMock

        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._storm_order_gates_active", lambda: True)
        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("no real market in test")
        _inputs = iter(["KXFIRSTHURRICANE-26DEC01ATL-ART", "q"])
        monkeypatch.setattr("builtins.input", lambda *_a: next(_inputs))

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main._quick_paper_buy(mock_client)
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)

    def test_cmd_paper_refuses_when_gate_inactive(self, monkeypatch, capsys):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.delenv("STORM_ORDER_TRADING_ENABLED", raising=False)

        main.cmd_paper(["buy", "KXFIRSTHURRICANE-26DEC01ATL-ART", "yes", "0.10", "1"])

        out = capsys.readouterr().out
        assert "refusing to place this order" in out
        assert "storm-order" in out.lower()
        assert "STORM_ORDER_TRADING_ENABLED" in out

    def test_cmd_paper_does_not_refuse_when_gate_active(self, monkeypatch):
        import main

        monkeypatch.setattr("main.is_trading_paused", lambda: False)
        monkeypatch.setattr("main._storm_order_gates_active", lambda: True)

        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(str(a)))
        try:
            main.cmd_paper(
                ["buy", "KXFIRSTHURRICANE-26DEC01ATL-ART", "yes", "0.10", "1"]
            )
        except Exception:
            pass
        assert not any("shadow-only" in p for p in printed)
