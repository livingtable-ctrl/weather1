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
