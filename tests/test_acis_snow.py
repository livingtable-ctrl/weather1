"""Tests for acis_snow.py's batch-36 fixes -- a clone of acis_precip.py with
elem="snow" instead of "pcpn". No prior dedicated test file existed for this
module (coverage previously came only indirectly via test_snow_markets.py/
test_weather_markets.py); these tests cover specifically the two fixes this
batch made here: L-1's mem-cache pinning of the stale fallback, and L-1's
unit-guard fail-open->closed for the seasonal snow fetch. Mirrors
test_acis_precip.py's own patterns for the identical bugs in the cloned code.
"""

from __future__ import annotations

import os
import time as _time
from unittest.mock import MagicMock, patch

import pytest

import acis_snow


@pytest.fixture(autouse=True)
def _clear_seasonal_cache():
    acis_snow._seasonal_cache.clear()
    yield
    acis_snow._seasonal_cache.clear()


class TestStaleFallbackDoesNotPinMemCacheForProcessLifetime:
    """L-1: identical fix to acis_precip._load_stale_cache_or_none -- see
    that module's own test class docstring for the full rationale.
    _MEM_CACHE is a plain dict with no TTL; caching a stale-fallback result
    would pin it for the rest of the process's lifetime instead of letting
    the next call retry once ACIS recovers."""

    def test_stale_fallback_does_not_populate_mem_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(acis_snow, "DATA_DIR", tmp_path)
        monkeypatch.setattr(acis_snow, "_MEM_CACHE", {})
        sid = "TESTSTALEPIN"
        cache_path = tmp_path / f"acis_snow_{sid}.json"
        cache_path.write_text('{"2020": {"101": 1.5}}')
        old_time = _time.time() - acis_snow.CACHE_MAX_AGE - 1
        os.utime(cache_path, (old_time, old_time))

        with patch.object(
            acis_snow._session, "post", side_effect=Exception("simulated ACIS outage")
        ):
            result = acis_snow.fetch_historical_daily_snow(sid, years=5, force=True)

        assert result == {2020: {101: 1.5}}
        assert sid not in acis_snow._MEM_CACHE, (
            "the stale-fallback result must NOT be written into _MEM_CACHE "
            "-- doing so would pin it for the rest of the process's "
            "lifetime instead of letting the next call retry once ACIS "
            "recovers"
        )

    def test_recovery_after_stale_fallback_retries_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(acis_snow, "DATA_DIR", tmp_path)
        monkeypatch.setattr(acis_snow, "_MEM_CACHE", {})
        sid = "TESTRECOVER"
        cache_path = tmp_path / f"acis_snow_{sid}.json"
        cache_path.write_text('{"2020": {"101": 1.5}}')
        old_time = _time.time() - acis_snow.CACHE_MAX_AGE - 1
        os.utime(cache_path, (old_time, old_time))

        with patch.object(
            acis_snow._session, "post", side_effect=Exception("simulated ACIS outage")
        ):
            first = acis_snow.fetch_historical_daily_snow(sid, years=5, force=True)
        assert first == {2020: {101: 1.5}}

        fresh_resp = MagicMock()
        fresh_resp.json.return_value = {"data": [["2026-01-01", "3.0"]]}
        fresh_resp.raise_for_status.return_value = None
        with patch.object(
            acis_snow._session, "post", return_value=fresh_resp
        ) as mock_post:
            second = acis_snow.fetch_historical_daily_snow(sid, years=5, force=False)

        assert mock_post.call_count == 1, (
            "the second call (force=False, a real caller's shape) must "
            "actually re-attempt the network fetch, not short-circuit on a "
            "permanently-pinned _MEM_CACHE entry"
        )
        assert second == {2026: {101: 3.0}}


class TestFetchSeasonalSnowMeanCmUnitGuard:
    """L-1: fetch_seasonal_snow_mean_cm's unit guard failed OPEN when
    monthly_units was absent entirely (`is not None and !=` treats a
    missing key the same as a confirmed-correct "cm") -- exactly the
    10x-mis-tilt scenario the guard exists to prevent. Now fails CLOSED:
    missing OR wrong unit is refused."""

    def test_missing_monthly_units_is_refused(self, caplog):
        import logging

        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "monthly": {"time": ["2026-07-31"], "snowfall_mean": [5.0]},
        }
        fake_resp.raise_for_status.return_value = None
        with patch.object(acis_snow._session, "get", return_value=fake_resp):
            with caplog.at_level(logging.WARNING):
                val = acis_snow.fetch_seasonal_snow_mean_cm(
                    39.7, -104.9, "America/Denver", 2026, 7
                )
        assert val is None
        assert any("refusing to use this value" in r.message for r in caplog.records)

    def test_wrong_monthly_units_is_refused(self):
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "monthly_units": {"time": "iso8601", "snowfall_mean": "mm"},
            "monthly": {"time": ["2026-07-31"], "snowfall_mean": [5.0]},
        }
        fake_resp.raise_for_status.return_value = None
        with patch.object(acis_snow._session, "get", return_value=fake_resp):
            val = acis_snow.fetch_seasonal_snow_mean_cm(
                39.7, -104.9, "America/Denver", 2026, 7
            )
        assert val is None

    def test_correct_cm_unit_returns_value_control(self):
        """Positive control: an explicit, correct 'cm' unit must not be refused."""
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "monthly_units": {"time": "iso8601", "snowfall_mean": "cm"},
            "monthly": {"time": ["2026-07-31"], "snowfall_mean": [5.0]},
        }
        fake_resp.raise_for_status.return_value = None
        with patch.object(acis_snow._session, "get", return_value=fake_resp):
            val = acis_snow.fetch_seasonal_snow_mean_cm(
                39.7, -104.9, "America/Denver", 2026, 7
            )
        assert val == 5.0
