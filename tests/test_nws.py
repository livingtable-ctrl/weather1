"""Tests for nws.py's nws_prob() days_out/sigma ladder."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import normal_cdf


class TestNwsProbDaysOutTimezone:
    def test_days_out_uses_city_local_today_not_utc(self):
        """nws_prob's days_out (and thus sigma) must be computed against
        the city's own local today, not UTC's -- target_date is city-local
        (from analyze_trade's parse_city_date()), so a UTC-based days_out
        silently disagrees during the ~4-8h evening window each day where
        UTC's date has already rolled over but the city's hasn't
        (backlog.txt "ANALYZE_TRADE'S past_date GATE...").

        Fixed instant 2026-08-10 00:30 UTC -> NYC local today is 2026-08-09.
        target_date=2026-08-12 is 3 days out from NYC's local today (sigma
        3.0), but only 2 days out from UTC's already-rolled-over
        2026-08-10 (sigma 2.0) -- a materially different probability for
        an "above" condition a few degrees over the forecast high, so this
        discriminates the two implementations directly rather than relying
        on a saturated (near 0/1) probability that would mask the sigma
        difference."""
        import nws

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return frozen_instant.replace(tzinfo=None)
                return frozen_instant.astimezone(tz)

        target_date = date(2026, 8, 12)
        forecast = {target_date.isoformat(): {"high": 75.0, "low": 55.0}}
        condition = {"type": "above", "threshold": 78.0, "var": "max"}
        coords = (40.7, -74.0, "America/New_York")

        with (
            patch.object(nws, "datetime", _Frozen),
            patch.object(nws, "get_nws_daily_forecast", return_value=forecast),
        ):
            result = nws.nws_prob("NYC", coords, target_date, condition)

        expected = 1.0 - normal_cdf(78.0, 75.0, 3.0)  # correct: days_out=3, sigma=3.0
        wrong = 1.0 - normal_cdf(78.0, 75.0, 2.0)  # buggy: UTC days_out=2, sigma=2.0
        assert result == pytest.approx(expected, abs=1e-9)
        assert abs(result - wrong) > 0.01, (
            "test setup bug: sigma=2.0 vs sigma=3.0 must produce a "
            "materially different probability for this to discriminate "
            "the two implementations"
        )


class TestNwsDailyForecastValidation:
    """AUD-0060: get_nws_daily_forecast's validate_nws_response() call had
    its bool return discarded, and the comment immediately above it
    ("validate BEFORE recording success so a malformed-but-HTTP-200
    response doesn't credit the circuit breaker") documented an intent that
    wasn't actually wired in -- record_success() ran unconditionally right
    after regardless of the validation result."""

    def _reset_caches(self):
        import nws

        nws._forecast_cache.clear()
        nws._gridpoint_cache.clear()

    def test_malformed_response_records_failure_not_success(self, monkeypatch):
        import nws

        self._reset_caches()
        nws._nws_cb.record_success()
        nws._nws_cb._last_failure_at = (
            None  # avoid burst-window absorption from a prior test
        )
        _before = nws._nws_cb.failure_count

        monkeypatch.setattr(nws, "_get_gridpoint", lambda lat, lon: ("OKX", 33, 35))
        # Missing "properties" entirely -- fails validate_nws_response's
        # required-field check (its own type is dict, required).
        monkeypatch.setattr(
            nws, "_get", lambda url, params=None: {"not_properties": {}}
        )

        result = nws.get_nws_daily_forecast("NYC", (40.7, -74.0, "America/New_York"))

        assert result == {}
        assert nws._nws_cb.failure_count > _before, (
            "positive control: a malformed response must be recorded as a "
            "real circuit-breaker failure, not silently absorbed as success"
        )

    def test_well_formed_response_still_credits_success_and_parses_periods(
        self, monkeypatch
    ):
        """Positive control for the test above: a genuinely valid response
        must NOT be treated as a failure -- proves the new gate only
        rejects malformed data, not every response."""
        import nws

        self._reset_caches()
        nws._nws_cb.record_success()

        monkeypatch.setattr(nws, "_get_gridpoint", lambda lat, lon: ("OKX", 33, 35))
        monkeypatch.setattr(
            nws,
            "_get",
            lambda url, params=None: {
                "properties": {
                    "periods": [
                        {
                            "startTime": "2026-08-10T06:00:00-04:00",
                            "isDaytime": True,
                            "temperature": 82,
                            "temperatureUnit": "F",
                        }
                    ]
                }
            },
        )

        result = nws.get_nws_daily_forecast("NYC", (40.7, -74.0, "America/New_York"))

        assert result == {"2026-08-10": {"high": 82.0, "low": None}}
        assert nws._nws_cb.failure_count == 0

    def test_empty_periods_records_failure_and_does_not_cache(self, monkeypatch):
        """M-18a: `{"properties": {}}` used to pass validate_nws_response()
        (only "properties" is a dict was checked), credit record_success(),
        and cache {} for the full 3600s TTL -- a city silently loses its NWS
        forecast for an hour with the breaker showing healthy. An absent OR
        empty `periods` list must now be treated as a real fetch failure:
        record_failure(), and -- the positive control below proves this
        half specifically -- no 3600s cache write of the empty result."""
        import nws

        self._reset_caches()
        nws._nws_cb.record_success()
        nws._nws_cb._last_failure_at = None
        _before = nws._nws_cb.failure_count

        monkeypatch.setattr(nws, "_get_gridpoint", lambda lat, lon: ("OKX", 33, 35))
        _call_count = {"n": 0}

        def _fake_get(url, params=None):
            _call_count["n"] += 1
            return {"properties": {}}

        monkeypatch.setattr(nws, "_get", _fake_get)

        result = nws.get_nws_daily_forecast("NYC", (40.7, -74.0, "America/New_York"))
        assert result == {}
        assert nws._nws_cb.failure_count > _before, (
            "an empty periods list must record a real circuit-breaker failure"
        )

        # Positive control: the cache must NOT have been written -- a second
        # call must re-invoke _get, not silently serve the cached {} for the
        # rest of the 3600s TTL.
        result2 = nws.get_nws_daily_forecast("NYC", (40.7, -74.0, "America/New_York"))
        assert result2 == {}
        assert _call_count["n"] == 2, (
            "an empty/malformed response must not be cached -- the second "
            "call should re-fetch, not hit a poisoned {} cache entry"
        )

    def test_periods_present_but_all_unparseable_records_failure(self, monkeypatch):
        """M-18a's second half: a response can pass the new periods-
        non-empty check yet still yield an empty `result` dict if every
        period fails its own per-period parse/unit gate (e.g. every period
        has a non-'F' temperatureUnit). That must ALSO be treated as a real
        failure -- not just the periods-missing/empty case above."""
        import nws

        self._reset_caches()
        nws._nws_cb.record_success()
        nws._nws_cb._last_failure_at = None
        _before = nws._nws_cb.failure_count

        monkeypatch.setattr(nws, "_get_gridpoint", lambda lat, lon: ("OKX", 33, 35))
        monkeypatch.setattr(
            nws,
            "_get",
            lambda url, params=None: {
                "properties": {
                    "periods": [
                        {
                            "startTime": "2026-08-10T06:00:00-04:00",
                            "isDaytime": True,
                            "temperature": 28,
                            "temperatureUnit": "C",  # every real caller uses F
                        }
                    ]
                }
            },
        )

        result = nws.get_nws_daily_forecast("NYC", (40.7, -74.0, "America/New_York"))

        assert result == {}
        assert nws._nws_cb.failure_count > _before


class TestValidateNwsResponsePeriods:
    """M-18a: schema_validator.validate_nws_response() unit tests, direct
    (not routed through get_nws_daily_forecast) -- get_nws_daily_forecast
    has its own independent empty-result guard after the parse loop (see
    TestNwsDailyForecastValidation.test_empty_periods_records_failure_and_
    does_not_cache above), which would mask a regression in
    validate_nws_response() alone for the "periods present but empty" case
    specifically, since a return of {} from an empty periods list gets
    caught by that second guard either way. These tests isolate
    validate_nws_response()'s own contribution."""

    def test_missing_periods_key_is_invalid(self):
        from schema_validator import validate_nws_response

        assert validate_nws_response({"properties": {}}) is False

    def test_empty_periods_list_is_invalid(self):
        from schema_validator import validate_nws_response

        assert validate_nws_response({"properties": {"periods": []}}) is False

    def test_non_list_periods_is_invalid(self):
        from schema_validator import validate_nws_response

        assert validate_nws_response({"properties": {"periods": "oops"}}) is False

    def test_non_empty_periods_is_valid_control(self):
        """Positive control: a real, non-empty periods list must still validate."""
        from schema_validator import validate_nws_response

        assert (
            validate_nws_response({"properties": {"periods": [{"temperature": 70}]}})
            is True
        )


class TestGetObsPoolSaturation:
    """L-1(nws): _get_obs abandons the submitted future on a wall-clock
    timeout -- ThreadPoolExecutor has no cancellation for already-started
    work, so an abandoned task keeps occupying a worker until it finishes on
    its own. Sustained hangs can permanently consume all _OBS_POOL_WORKERS
    workers; every new submission after that queues and times out too, but
    that looks identical to a normal single-request timeout in the logs
    without a distinct signal. These tests exercise the in-flight counter
    directly (deterministic) rather than real concurrent hangs (racy/slow)."""

    def setup_method(self):
        import nws

        nws._obs_inflight = 0

    def test_not_saturated_does_not_log(self, caplog):
        import logging

        import nws

        with patch.object(nws, "_get", return_value={"ok": True}):
            with caplog.at_level(logging.WARNING):
                result = nws._get_obs("http://example.test/obs")

        assert result == {"ok": True}
        assert not any("pool saturated" in r.message for r in caplog.records)

    def test_saturated_logs_distinct_warning(self, caplog):
        """Simulates _OBS_POOL_WORKERS already-in-flight tasks (e.g. from
        prior abandoned timeouts) -- the next submission must detect and log
        saturation. Mutation-tested: removing the `_inflight_now >
        _OBS_POOL_WORKERS` check (never logging) makes this fail."""
        import logging

        import nws

        nws._obs_inflight = nws._OBS_POOL_WORKERS
        with patch.object(nws, "_get", return_value={"ok": True}):
            with caplog.at_level(logging.WARNING):
                nws._get_obs("http://example.test/obs")

        assert any("pool saturated" in r.message for r in caplog.records), (
            "a submission arriving when already at/above worker capacity "
            "must log a distinct saturation warning"
        )

    def test_inflight_counter_decrements_after_completion(self):
        """The counter must return to its pre-call baseline once the
        underlying task actually finishes (via add_done_callback), not stay
        incremented forever -- otherwise every real call would eventually
        look permanently saturated even with a healthy pool."""
        import time

        import nws

        with patch.object(nws, "_get", return_value={"ok": True}):
            nws._get_obs("http://example.test/obs")

        for _ in range(50):
            if nws._obs_inflight == 0:
                break
            time.sleep(0.01)
        assert nws._obs_inflight == 0
