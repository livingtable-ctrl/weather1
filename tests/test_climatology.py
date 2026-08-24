"""Tests for climatology.py's climate-derived sigma (restored 2026-07-12 --
silently lost in the 24559a7 mystery-revert, see backlog.txt).
"""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import patch

import pytest

import climatology


def _synthetic_climate_data(n_years=30, high_base=70.0, high_spread=1.0, low_base=50.0):
    """Build a fake fetch_historical() response: one high/low reading per
    (year, month) pair for `n_years` years, so every month clears the >=30-
    point gate. high_spread controls the stdev of the "highs" series.
    """
    dates, highs, lows = [], [], []
    for year in range(2000, 2000 + n_years):
        for month in range(1, 13):
            dates.append(f"{year}-{month:02d}-15")
            # Alternate +/- spread so stdev is well-defined and nonzero.
            offset = high_spread if year % 2 == 0 else -high_spread
            highs.append(high_base + offset)
            lows.append(low_base)
    return {"dates": dates, "highs": highs, "lows": lows}


class _FakeResponse:
    """Minimal requests.Response stand-in for mocking climatology._session.get."""

    def __init__(self, daily: dict):
        self._daily = daily

    def raise_for_status(self):
        pass

    def json(self):
        return {"daily": self._daily}


def _fake_daily(n_days=3):
    return {
        "time": [f"2024-01-{d:02d}" for d in range(1, n_days + 1)],
        "temperature_2m_max": [70.0 + d for d in range(n_days)],
        "temperature_2m_min": [50.0 + d for d in range(n_days)],
    }


class TestFetchHistoricalCaching:
    """fetch_historical()'s _MEM_CACHE memoization -- previously zero direct
    coverage (every other test in this file mocks fetch_historical away via
    patch.object rather than exercising its real body). Written as part of
    the ForecastCache(ttl_secs=inf) migration (backlog.txt "ForecastCache
    EXISTS, BUT 2 HAND-ROLLED CACHES...") so the migration has real
    regression coverage, not just a behavior-preservation claim.

    climatology.DATA_DIR is redirected to tmp_path so these never touch the
    real data/climate_*.json archives -- isolate_climatology_mem_cache
    (conftest.py) resets _MEM_CACHE itself between tests automatically.

    Uses patch.object(climatology._session, "get", ...) as a context manager
    (matching test_acis_precip.py's/test_metar.py's established convention
    for mocking a shared module-level requests.Session, opus-review-caught
    2026-08-07) rather than monkeypatch.setattr -- the latter's teardown
    re-sets the instance attribute to the captured original rather than
    delattr-ing it, permanently leaving an instance-level override in
    _session.__dict__ instead of restoring clean class-level method lookup.
    unittest.mock's own call_count also replaces the hand-rolled `calls`
    dict counter this class used before.
    """

    def _mock_network(self, n_days=3):
        def fake_get(url, params=None, timeout=None):
            return _FakeResponse(_fake_daily(n_days))

        return patch.object(climatology._session, "get", side_effect=fake_get)

    def _mock_network_failure(self):
        def failing_get(*a, **kw):
            raise climatology.requests.ConnectionError("simulated network failure")

        return patch.object(climatology._session, "get", side_effect=failing_get)

    def test_network_fetch_populates_mem_cache_and_writes_disk(
        self, tmp_path, monkeypatch
    ):
        with self._mock_network() as mock_get:
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert mock_get.call_count == 1
        assert result["highs"] == [70.0, 71.0, 72.0]
        assert climatology._MEM_CACHE.get("NYC") == result, (
            "a successful network fetch must populate _MEM_CACHE"
        )
        disk_path = tmp_path / "climate_NYC.json"
        assert disk_path.exists()
        assert json.loads(disk_path.read_text())["highs"] == [70.0, 71.0, 72.0]

    def test_second_call_same_city_serves_from_mem_cache_not_network(
        self, tmp_path, monkeypatch
    ):
        """Deletes the disk cache file between calls so the second call can
        ONLY succeed via _MEM_CACHE -- without this, a mutation that breaks
        memoization but leaves the disk-cache fallback intact would still
        avoid a second network call (the first call's own write already
        populated a fresh disk file) and this test would pass for the wrong
        reason. Confirmed live: an earlier version of this test without the
        delete step survived exactly that mutation."""
        coords = (40.7, -74.0, "America/New_York")

        with self._mock_network() as mock_get:
            first = climatology.fetch_historical("NYC", coords)
            (tmp_path / "climate_NYC.json").unlink()
            second = climatology.fetch_historical("NYC", coords)

        assert mock_get.call_count == 1, (
            "second call for the same city must be served from _MEM_CACHE, "
            "not trigger a second network fetch"
        )
        assert second == first

    def test_force_true_bypasses_mem_cache(self, tmp_path, monkeypatch):
        coords = (40.7, -74.0, "America/New_York")

        with self._mock_network() as mock_get:
            climatology.fetch_historical("NYC", coords)
            climatology.fetch_historical("NYC", coords, force=True)

        assert mock_get.call_count == 2, (
            "force=True must bypass both mem and disk cache"
        )

    def test_fresh_disk_cache_serves_without_network_call(self, tmp_path, monkeypatch):
        disk_path = tmp_path / "climate_NYC.json"
        disk_data = {"dates": ["2020-01-01"], "highs": [99.0], "lows": [1.0]}
        disk_path.write_text(json.dumps(disk_data))

        with self._mock_network() as mock_get:
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert mock_get.call_count == 0, (
            "a fresh disk cache must not trigger a network call"
        )
        assert result["highs"] == [99.0]

    def test_fresh_disk_cache_read_also_populates_mem_cache(
        self, tmp_path, monkeypatch
    ):
        """Targets _MEM_CACHE.set() on the fresh-disk-read branch specifically
        (climatology.py's first .set() call inside fetch_historical) --
        deletes the disk file after the first call so a second call can only
        succeed via the in-memory cache that read populated, proving that
        branch caches its result and not just the network-fetch branch
        (opus-review-caught 2026-08-07: this exact site was uncovered and a
        mutation deleting its .set() call survived the rest of this suite)."""
        disk_path = tmp_path / "climate_NYC.json"
        disk_data = {"dates": ["2020-01-01"], "highs": [99.0], "lows": [1.0]}
        disk_path.write_text(json.dumps(disk_data))
        coords = (40.7, -74.0, "America/New_York")

        first = climatology.fetch_historical("NYC", coords)
        disk_path.unlink()
        with self._mock_network() as mock_get:
            second = climatology.fetch_historical("NYC", coords)

        assert mock_get.call_count == 0, (
            "reading a fresh disk cache must populate _MEM_CACHE too, so a "
            "later call (even after the disk file is gone) is served from "
            "memory rather than falling through to the network"
        )
        assert second == first == disk_data

    def test_stale_disk_cache_triggers_network_refetch(self, tmp_path, monkeypatch):
        import os

        disk_path = tmp_path / "climate_NYC.json"
        disk_path.write_text(
            json.dumps({"dates": ["2020-01-01"], "highs": [99.0], "lows": [1.0]})
        )
        stale_time = time.time() - climatology.CACHE_MAX_AGE - 3600
        os.utime(disk_path, (stale_time, stale_time))

        with self._mock_network() as mock_get:
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert mock_get.call_count == 1, (
            "a stale disk cache must trigger a real refetch"
        )
        assert result["highs"] == [70.0, 71.0, 72.0], (
            "must return the fresh network data, not the stale disk content"
        )

    def test_network_failure_falls_back_to_existing_disk_cache(
        self, tmp_path, monkeypatch
    ):
        import os

        disk_path = tmp_path / "climate_NYC.json"
        disk_data = {"dates": ["2020-01-01"], "highs": [55.0], "lows": [1.0]}
        disk_path.write_text(json.dumps(disk_data))
        stale_time = time.time() - climatology.CACHE_MAX_AGE - 3600
        os.utime(disk_path, (stale_time, stale_time))  # force the network attempt

        with self._mock_network_failure() as mock_get:
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert mock_get.call_count == 1, (
            "must actually attempt (and fail) a network call, not silently "
            "serve the disk content as if it were fresh -- opus-review-caught "
            "2026-08-07: without this assertion the fresh-disk-cache path and "
            "the network-failure-fallback path are indistinguishable, since "
            "both return the same underlying disk content"
        )
        assert result["highs"] == [55.0], (
            "a network failure must fall back to the existing (even if stale) "
            "disk cache rather than returning None"
        )

    def test_network_failure_fallback_also_populates_mem_cache(
        self, tmp_path, monkeypatch
    ):
        """Targets _MEM_CACHE.set() on the network-failure-fallback branch
        specifically (opus-review-caught 2026-08-07: uncovered, a mutation
        deleting that .set() call survived the rest of this suite)."""
        import os

        disk_path = tmp_path / "climate_NYC.json"
        disk_data = {"dates": ["2020-01-01"], "highs": [55.0], "lows": [1.0]}
        disk_path.write_text(json.dumps(disk_data))
        stale_time = time.time() - climatology.CACHE_MAX_AGE - 3600
        os.utime(disk_path, (stale_time, stale_time))
        coords = (40.7, -74.0, "America/New_York")

        with self._mock_network_failure() as mock_get:
            first = climatology.fetch_historical("NYC", coords)
        assert mock_get.call_count == 1
        assert first["highs"] == [55.0]

        disk_path.unlink()  # remove the disk fallback entirely
        with self._mock_network_failure() as mock_get2:
            second = climatology.fetch_historical("NYC", coords)

        assert mock_get2.call_count == 0, (
            "the network-failure disk-fallback branch must also populate "
            "_MEM_CACHE, so a later call is served from memory without "
            "attempting the network again or needing the (now-deleted) disk file"
        )
        assert second == first

    def test_network_failure_with_no_disk_cache_returns_none(
        self, tmp_path, monkeypatch
    ):
        with self._mock_network_failure():
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert result is None

    # ── M-18e: unguarded json.load on the per-city climate cache ────────────

    def test_corrupt_fresh_disk_cache_falls_through_to_network_refetch(
        self, tmp_path, monkeypatch
    ):
        """M-18e: a corrupt/truncated climate_{city}.json used to raise
        straight out of fetch_historical() -- and since load_all_sigmas()
        calls fetch_historical() (via compute_sigma_from_climate()) while
        holding its own _sigma_lock, that raise would propagate out of
        load_all_sigmas() entirely, dropping the lock mid-loop and aborting
        every OTHER city's sigma compute in the same call, not just this
        one. Must degrade to a real refetch instead, mirroring
        _load_sigma_cache_file's own corrupt-file guarding."""
        disk_path = tmp_path / "climate_NYC.json"
        disk_path.write_text("{not valid json")  # fresh mtime, corrupt content

        with self._mock_network() as mock_get:
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert result is not None
        assert result["highs"] == [70.0, 71.0, 72.0], (
            "a corrupt fresh disk cache must not raise -- it must fall "
            "through to a real network refetch"
        )
        assert mock_get.call_count == 1

    def test_corrupt_stale_fallback_cache_returns_none_not_raise(
        self, tmp_path, monkeypatch
    ):
        """M-18e's second gap: the except-handler's stale-cache-read copy
        (reached when the network call itself fails) has the identical
        unguarded json.load -- and sits inside an `except Exception as exc`
        block, so an unguarded raise there would mask the original network
        error behind an unrelated JSONDecodeError while still propagating
        out of load_all_sigmas(). Must return None gracefully instead."""
        import os

        disk_path = tmp_path / "climate_NYC.json"
        disk_path.write_text("{not valid json")
        stale_time = time.time() - climatology.CACHE_MAX_AGE - 3600
        os.utime(disk_path, (stale_time, stale_time))  # force the network attempt

        with self._mock_network_failure():
            result = climatology.fetch_historical(
                "NYC", (40.7, -74.0, "America/New_York")
            )

        assert result is None, (
            "a network failure falling back to a corrupt stale disk cache "
            "must return None (not raise, and not mask the original "
            "network error with a JSONDecodeError)"
        )

    def test_load_all_sigmas_survives_corrupt_climate_cache_for_other_cities(
        self, tmp_path, monkeypatch
    ):
        """Integration-level proof: a corrupt climate_{city}.json for ONE
        city must not abort load_all_sigmas()'s loop for every OTHER city
        -- the exact failure mode M-18e's docstring describes (an unguarded
        raise inside the _sigma_lock-held loop). Exercises the REAL
        fetch_historical() end to end (not a mock standing in for it) --
        an earlier version of this test replaced fetch_historical entirely,
        which meant it could not actually detect a regression in the
        json.load guard it claims to prove; this version writes a genuinely
        corrupt file to disk and lets compute_sigma_from_climate() ->
        fetch_historical() read it for real. Network is mocked to also fail
        for BAD (compute_sigma_from_climate() doesn't thread load_all_
        sigmas()'s own `force` through to fetch_historical() at all -- so a
        FRESH-mtime corrupt file always exercises the first guarded
        json.load branch, and a failed network attempt then exercises the
        second guarded (stale-cache-fallback) branch reading the same
        corrupt file again) -- proving BOTH of climatology.py's M-18e fixes
        survive in the same call, not just the first one."""
        import os

        import climatology as clim

        monkeypatch.setattr(clim, "DATA_DIR", tmp_path)
        monkeypatch.setattr(clim, "_SIGMA_CACHE_PATH", tmp_path / "forecast_sigma.json")
        clim._sigma_mem_cache.clear()
        clim._MEM_CACHE.clear()

        bad_path = tmp_path / "climate_BAD.json"
        bad_path.write_text("{not valid json")
        now = time.time()
        os.utime(bad_path, (now, now))  # fresh mtime -- not stale

        good_path = tmp_path / "climate_GOOD.json"
        good_data = _synthetic_climate_data()
        good_path.write_text(json.dumps(good_data))
        os.utime(good_path, (now, now))

        with patch.object(
            clim._session, "get", side_effect=clim.requests.ConnectionError("down")
        ) as mock_get:
            result = clim.load_all_sigmas(
                {"BAD": (0.0, 0.0, "UTC"), "GOOD": (0.0, 0.0, "UTC")}, force=True
            )

        assert mock_get.call_count == 2, (
            "expected exactly 2 network attempts (BAD's corrupt-fresh-cache "
            "falls through to a real refetch attempt, once per var -- "
            "compute_sigma_from_climate() calls fetch_historical() once for "
            "max and once for min, and neither corrupt-file failure path "
            "populates _MEM_CACHE, so each var independently repeats the "
            "same guarded-read + network-attempt sequence); GOOD's own "
            "fresh, valid on-disk cache must be served without ever "
            "touching the network at all"
        )
        assert "GOOD" in result and result["GOOD"]["max"], (
            "GOOD city's sigma must still be computed even though BAD's "
            "climate cache was corrupt/unfetchable"
        )
        assert result["BAD"] == {"max": {}, "min": {}}, (
            "BAD's corrupt cache (both guarded read attempts exhausted, "
            "network also down) must degrade to an empty entry, not raise"
        )


class TestClimatologicalNormal:
    """M-31: climatological_normal() is a new function -- regime.py's
    heat_dome/cold_snap climatology-anomaly confirmation reads it. Mirrors
    climatological_prob's own circuit-breaker/window/floor conventions
    (shared via the new _window_temps helper both now call)."""

    def test_mean_and_stdev_match_hand_computed_values(self):
        import statistics

        data = _synthetic_climate_data(n_years=30, high_base=85.0, high_spread=5.0)
        with patch.object(climatology, "fetch_historical", return_value=data):
            from datetime import date as _date

            result = climatology.climatological_normal(
                "Phoenix",
                (33.45, -112.07, "America/Phoenix"),
                _date(2020, 7, 15),
                "max",
            )
        assert result is not None
        mean, std = result
        # July 15 across 30 years, alternating +5/-5 by year parity (15 of
        # each) -- window (WINDOW_DAYS=21, July isn't a shoulder month)
        # only admits the 15th-of-July points themselves (June/Aug 15 are
        # 31 days away), so this is exactly the alternating +-5 series.
        expected_values = [
            85.0 + (5.0 if year % 2 == 0 else -5.0) for year in range(2000, 2030)
        ]
        assert mean == pytest.approx(statistics.mean(expected_values))
        assert std == pytest.approx(statistics.stdev(expected_values))
        assert mean == pytest.approx(85.0)

    def test_insufficient_data_returns_none(self):
        """Fewer than 30 points in the window (climatological_prob's own
        floor) must return None, not a normal computed from a thin sample."""
        data = _synthetic_climate_data(n_years=10)
        with patch.object(climatology, "fetch_historical", return_value=data):
            from datetime import date as _date

            result = climatology.climatological_normal(
                "Phoenix",
                (33.45, -112.07, "America/Phoenix"),
                _date(2020, 7, 15),
                "max",
            )
        assert result is None

    def test_fetch_failure_returns_none(self):
        with patch.object(climatology, "fetch_historical", return_value=None):
            from datetime import date as _date

            result = climatology.climatological_normal(
                "Phoenix",
                (33.45, -112.07, "America/Phoenix"),
                _date(2020, 7, 15),
                "max",
            )
        assert result is None

    def test_circuit_open_returns_none_without_fetching(self):
        from datetime import date as _date

        with patch.object(climatology._clim_cb, "is_open", return_value=True):
            with patch.object(climatology, "fetch_historical") as mock_fetch:
                result = climatology.climatological_normal(
                    "Phoenix",
                    (33.45, -112.07, "America/Phoenix"),
                    _date(2020, 7, 15),
                    "max",
                )
        assert result is None
        mock_fetch.assert_not_called()

    def test_min_var_uses_lows_not_highs(self):
        data = _synthetic_climate_data(
            n_years=30, high_base=85.0, high_spread=0.0, low_base=50.0
        )
        with patch.object(climatology, "fetch_historical", return_value=data):
            from datetime import date as _date

            result = climatology.climatological_normal(
                "Phoenix",
                (33.45, -112.07, "America/Phoenix"),
                _date(2020, 7, 15),
                "min",
            )
        assert result is not None
        mean, _std = result
        assert mean == pytest.approx(50.0), "var='min' must read the lows series"


class TestComputeSigmaFromClimate:
    def test_returns_per_month_dict(self):
        data = _synthetic_climate_data()
        with patch.object(climatology, "fetch_historical", return_value=data):
            result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="max"
            )
        assert set(result.keys()) == set(range(1, 13))
        for sigma in result.values():
            assert sigma >= climatology._SIGMA_FLOOR

    def test_empty_when_fetch_historical_returns_none(self):
        with patch.object(climatology, "fetch_historical", return_value=None):
            result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="max"
            )
        assert result == {}

    def test_skips_months_with_fewer_than_30_points(self):
        # Only 5 years of data — well under the 30-point gate per month.
        data = _synthetic_climate_data(n_years=5)
        with patch.object(climatology, "fetch_historical", return_value=data):
            result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="max"
            )
        assert result == {}

    def test_respects_sigma_floor(self):
        # Zero-variance data: stdev=0, so sigma would compute to 0 without the floor.
        data = {
            "dates": [f"2000-01-{d:02d}" for d in range(1, 32)] * 2,
            "highs": [70.0] * 62,
            "lows": [50.0] * 62,
        }
        # Pad to >=30 points for January specifically.
        with patch.object(climatology, "fetch_historical", return_value=data):
            result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="max"
            )
        assert result.get(1) == climatology._SIGMA_FLOOR

    def test_min_var_uses_lows_not_highs(self):
        # spread=5.0 -> stdev~5.0 -> *0.6=3.0, comfortably above the 1.5 floor
        data = _synthetic_climate_data(high_base=70.0, high_spread=5.0, low_base=50.0)
        with patch.object(climatology, "fetch_historical", return_value=data):
            max_result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="max"
            )
            min_result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="min"
            )
        # lows are constant (stdev=0) -> floored; highs alternate +/-1.0 -> not floored
        assert min_result[1] == climatology._SIGMA_FLOOR
        assert max_result[1] > climatology._SIGMA_FLOOR

    def test_ignores_null_values(self):
        # 31 years so removing one January point still leaves exactly 30 —
        # the >=30 gate boundary.
        data = _synthetic_climate_data(n_years=31)
        data["highs"][0] = None  # first entry: year 2000, January
        with patch.object(climatology, "fetch_historical", return_value=data):
            result = climatology.compute_sigma_from_climate(
                "NYC", (40.7, -74.0, "America/New_York"), var="max"
            )
        assert 1 in result  # still enough remaining points


class TestLoadAllSigmasBehavior:
    # No setup_method/teardown_method needed (opus-review-caught 2026-08-07,
    # confirmed via a direct probe -- deleting both still leaves every test in
    # this class passing): conftest.py's autouse isolate_dynamic_sigma fixture
    # already installs a fresh climatology._sigma_mem_cache before every test
    # runs (autouse fixtures apply before setup_method), and monkeypatch
    # restores the true module-level original at teardown regardless.

    def test_builds_per_city_max_and_min_structure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        fake_sigma = {1: 3.2, 2: 3.4}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value=fake_sigma
        ):
            result = climatology.load_all_sigmas(city_coords, force=True)
        assert result["NYC"]["max"] == {"1": 3.2, "2": 3.4}
        assert result["NYC"]["min"] == {"1": 3.2, "2": 3.4}

    def test_writes_cache_file(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "sigma.json"
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ):
            climatology.load_all_sigmas(city_coords, force=True)
        assert cache_path.exists()
        on_disk = json.loads(cache_path.read_text())
        assert on_disk["NYC"]["max"]["1"] == 3.0

    def test_reads_fresh_cache_without_recompute(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(json.dumps({"NYC": {"max": {"1": 9.9}, "min": {}}}))
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(climatology, "compute_sigma_from_climate") as mock_compute:
            result = climatology.load_all_sigmas(city_coords)
        mock_compute.assert_not_called()
        assert result["NYC"]["max"]["1"] == 9.9

    def test_recomputes_stale_cache(self, tmp_path, monkeypatch):
        import os

        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(json.dumps({"NYC": {"max": {"1": 9.9}, "min": {}}}))
        stale_time = time.time() - climatology._SIGMA_CACHE_AGE - 3600
        os.utime(cache_path, (stale_time, stale_time))
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 4.4}
        ) as mock_compute:
            result = climatology.load_all_sigmas(city_coords)
        mock_compute.assert_called()
        assert result["NYC"]["max"]["1"] == 4.4

    def test_memoizes_in_process(self, tmp_path, monkeypatch):
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ) as mock_compute:
            climatology.load_all_sigmas(city_coords, force=True)
            call_count_after_first = mock_compute.call_count
            climatology.load_all_sigmas(
                city_coords
            )  # force=False, should hit mem cache
        assert mock_compute.call_count == call_count_after_first

    def test_force_bypasses_memoization(self, tmp_path, monkeypatch):
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ) as mock_compute:
            climatology.load_all_sigmas(city_coords, force=True)
            first_calls = mock_compute.call_count
            climatology.load_all_sigmas(city_coords, force=True)
        assert mock_compute.call_count > first_calls

    def test_covers_lasvegas_and_neworleans(self, tmp_path, monkeypatch):
        """The actual backlog payoff: cities absent from weather_markets'
        static _HISTORICAL_SIGMA table get a real dynamic sigma here, keyed
        the same way as every other city (no special-casing needed)."""
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        city_coords = {
            "LasVegas": (36.17, -115.14, "America/Los_Angeles"),
            "NewOrleans": (29.95, -90.07, "America/Chicago"),
        }
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 2.9}
        ):
            result = climatology.load_all_sigmas(city_coords, force=True)
        assert result["LasVegas"]["max"]["1"] == 2.9
        assert result["NewOrleans"]["max"]["1"] == 2.9

    def test_concurrent_cold_cache_calls_compute_only_once(self, tmp_path, monkeypatch):
        """backlog.txt "FORECAST_SIGMA.JSON ATOMIC WRITE CONTENTION": cron.py's
        ThreadPoolExecutor scan can call load_all_sigmas() from multiple worker
        threads at once against a cold cache. Without _sigma_lock, every thread
        would see the empty mem-cache/missing file and independently recompute
        + race to atomic_write_json() the same forecast_sigma.json (observed
        live: WinError 32/5/2 on the rename step, recurring 2026-07-19/25/27/30).
        Slows compute_sigma_from_climate down to widen the race window, lines
        up N threads on a barrier so they all pass the empty-cache check at
        the same instant, and asserts only ONE thread's worth of compute calls
        happened -- proving the lock serializes them rather than letting every
        thread redundantly (and racily) recompute+write."""
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        n_threads = 8
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        calls = {"n": 0}

        def slow_compute(city, coords, var="max"):
            with call_count_lock:
                calls["n"] += 1
            time.sleep(0.05)
            return {1: 3.0}

        results = []
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(climatology.load_all_sigmas(city_coords))
            except Exception as e:  # pragma: no cover - surfaced via errors list
                errors.append(e)

        with patch.object(
            climatology, "compute_sigma_from_climate", side_effect=slow_compute
        ):
            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert not errors, f"worker thread(s) raised: {errors}"
        assert len(results) == n_threads
        # 1 city * 2 vars (max/min) = 2 calls total if the lock serialized the
        # whole race onto a single winner; without the lock this would be up
        # to n_threads*2.
        assert calls["n"] == 2, (
            f"expected exactly 2 compute_sigma_from_climate calls (one city's "
            f"max+min, computed once), got {calls['n']} -- the lock isn't "
            f"serializing concurrent cold-cache callers"
        )
        # Every thread must still get the real, fully-computed result, not a
        # partial/empty dict from a racer that returned before the winner finished.
        for r in results:
            assert r["NYC"]["max"]["1"] == 3.0
        on_disk = json.loads((tmp_path / "sigma.json").read_text())
        assert on_disk["NYC"]["max"]["1"] == 3.0


class TestLoadAllSigmasMerge:
    """backlog.txt "PRELOAD_ALL CAN PERMANENTLY TRUNCATE forecast_sigma.json
    TO ONE CITY ON A PARTIAL CALL": load_all_sigmas() used to unconditionally
    overwrite data/forecast_sigma.json with a table built from EXACTLY the
    city_coords dict it was given, dropping every other city's existing
    entry. It now merges: only the cities actually passed in this call are
    recomputed, everything else already on disk survives untouched.
    """

    def test_partial_call_preserves_other_cities_in_memory_result(
        self, tmp_path, monkeypatch
    ):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(
            json.dumps({"LasVegas": {"max": {"1": 5.5}, "min": {"1": 4.4}}})
        )
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ):
            result = climatology.load_all_sigmas(
                {"NYC": (40.7, -74.0, "America/New_York")}, force=True
            )
        assert result["LasVegas"]["max"]["1"] == 5.5
        assert result["NYC"]["max"]["1"] == 3.0

    def test_partial_call_preserves_other_cities_on_disk(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(
            json.dumps({"LasVegas": {"max": {"1": 5.5}, "min": {"1": 4.4}}})
        )
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ):
            climatology.load_all_sigmas(
                {"NYC": (40.7, -74.0, "America/New_York")}, force=True
            )
        on_disk = json.loads(cache_path.read_text())
        assert on_disk["LasVegas"]["max"]["1"] == 5.5
        assert on_disk["NYC"]["max"]["1"] == 3.0

    def test_recomputing_a_city_overwrites_only_that_citys_entry(
        self, tmp_path, monkeypatch
    ):
        """A city passed again in a later call gets its own entry refreshed
        (not stuck at a stale value), while untouched cities are unaffected."""
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(
            json.dumps(
                {
                    "NYC": {"max": {"1": 1.1}, "min": {}},
                    "LasVegas": {"max": {"1": 5.5}, "min": {}},
                }
            )
        )
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 9.9}
        ):
            result = climatology.load_all_sigmas(
                {"NYC": (40.7, -74.0, "America/New_York")}, force=True
            )
        assert result["NYC"]["max"]["1"] == 9.9
        assert result["LasVegas"]["max"]["1"] == 5.5

    def test_corrupt_existing_file_falls_back_to_fresh_table_without_crashing(
        self, tmp_path, monkeypatch
    ):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text("{not valid json")
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ):
            result = climatology.load_all_sigmas(
                {"NYC": (40.7, -74.0, "America/New_York")}, force=True
            )
        assert result["NYC"]["max"]["1"] == 3.0

    def test_sequential_partial_calls_accumulate_full_table(
        self, tmp_path, monkeypatch
    ):
        """Simulates main.py's setup wizard calling load_all_sigmas() (via
        preload_all(), see TestPreloadAllSigmaGate below for the full
        end-to-end version) once per city -- each call should add to the
        table, not reset it."""
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        cities = {
            "NYC": (40.7, -74.0, "America/New_York"),
            "LasVegas": (36.17, -115.14, "America/Los_Angeles"),
            "NewOrleans": (29.95, -90.07, "America/Chicago"),
        }
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ):
            for city, coords in cities.items():
                result = climatology.load_all_sigmas({city: coords}, force=True)
        assert set(result.keys()) == set(cities.keys())

    def test_partial_var_failure_does_not_clobber_the_other_vars_good_table(
        self, tmp_path, monkeypatch
    ):
        """L-5: the old guard (`if not (max_sigma or min_sigma) and
        _sigma_entry_has_data(...): continue`) only skipped the write when
        BOTH vars came back empty. A PARTIAL failure -- max succeeds, min
        comes back empty from a transient glitch -- made `max_sigma or
        min_sigma` truthy, so it fell through and wrote {"max": <good>,
        "min": {}}, clobbering NYC's existing GOOD min table. Must preserve
        each var independently."""
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(
            json.dumps(
                {"NYC": {"max": {"1": 1.1}, "min": {"1": 2.2}}}  # both real
            )
        )
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)

        def fake_compute(city, coords, var="max"):
            if var == "max":
                return {1: 9.9}  # fresh, successful recompute
            return {}  # min compute failed this round (transient)

        with patch.object(
            climatology, "compute_sigma_from_climate", side_effect=fake_compute
        ):
            result = climatology.load_all_sigmas(
                {"NYC": (40.7, -74.0, "America/New_York")}, force=True
            )

        assert result["NYC"]["max"]["1"] == 9.9, "max must reflect the fresh recompute"
        assert result["NYC"]["min"]["1"] == 2.2, (
            "min's existing good table must survive a partial (min-only) "
            "compute failure, not be clobbered with an empty dict"
        )

    def test_partial_var_failure_min_survives_on_disk_too(self, tmp_path, monkeypatch):
        """Positive-path control for the fix above, checked at the disk-
        write level too, not just the in-memory return value."""
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(
            json.dumps({"NYC": {"max": {"1": 1.1}, "min": {"1": 2.2}}})
        )
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)

        def fake_compute(city, coords, var="max"):
            return {1: 9.9} if var == "max" else {}

        with patch.object(
            climatology, "compute_sigma_from_climate", side_effect=fake_compute
        ):
            climatology.load_all_sigmas(
                {"NYC": (40.7, -74.0, "America/New_York")}, force=True
            )

        on_disk = json.loads(cache_path.read_text())
        assert on_disk["NYC"]["min"]["1"] == 2.2
        assert on_disk["NYC"]["max"]["1"] == 9.9


class TestPreloadAllSigmaGate:
    """backlog.txt "PRELOAD_ALL CAN PERMANENTLY TRUNCATE forecast_sigma.json
    TO ONE CITY ON A PARTIAL CALL": preload_all()'s own gate used to trigger
    a sigma refresh only when the cache file was missing or stale -- blind to
    whether the cities it was actually asked to preload were in that file at
    all. A per-city caller (main.py's setup wizard) would write city 1's
    entry, see the file as "fresh" on every later call, and never trigger a
    refresh for the remaining cities until the file went stale a month later
    -- even though the merge fix above means load_all_sigmas() *would* have
    handled it correctly if it had ever been called. The gate now also fires
    when any requested city is missing from the cached table.
    """

    def _mock_climate_history(self, tmp_path, monkeypatch):
        # preload_all()'s per-city climate-history loop is independent of the
        # sigma-cache logic under test; stub it out so it neither hits the
        # network nor requires real climate_{city}.json fixtures.
        monkeypatch.setattr(
            climatology, "_cache_path", lambda city: tmp_path / f"climate_{city}.json"
        )
        return patch.object(climatology, "fetch_historical", return_value=None)

    def test_sequential_per_city_preload_all_calls_build_full_table(
        self, tmp_path, monkeypatch
    ):
        """The exact backlog scenario: main.py's wizard calls
        preload_all({city: CITY_COORDS[city]}) once per city in a loop. All
        cities must end up in forecast_sigma.json, not just the first one."""
        sigma_path = tmp_path / "sigma.json"
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", sigma_path)
        cities = {
            "NYC": (40.7, -74.0, "America/New_York"),
            "LasVegas": (36.17, -115.14, "America/Los_Angeles"),
            "NewOrleans": (29.95, -90.07, "America/Chicago"),
        }
        with (
            self._mock_climate_history(tmp_path, monkeypatch),
            patch.object(
                climatology, "compute_sigma_from_climate", return_value={1: 3.0}
            ),
        ):
            for city, coords in cities.items():
                climatology.preload_all({city: coords})
        on_disk = json.loads(sigma_path.read_text())
        assert set(on_disk.keys()) == set(cities.keys())

    def test_second_call_for_same_cities_does_not_recompute(
        self, tmp_path, monkeypatch
    ):
        """Once a city is already in the fresh cache, a later preload_all()
        call for that same city should NOT trigger another recompute."""
        sigma_path = tmp_path / "sigma.json"
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", sigma_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with (
            self._mock_climate_history(tmp_path, monkeypatch),
            patch.object(
                climatology, "compute_sigma_from_climate", return_value={1: 3.0}
            ) as mock_compute,
        ):
            climatology.preload_all(city_coords)
            calls_after_first = mock_compute.call_count
            climatology.preload_all(city_coords)
        assert mock_compute.call_count == calls_after_first

    def test_missing_cities_helper_treats_absent_file_as_all_missing(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", tmp_path / "sigma.json")
        missing = climatology._sigma_cache_missing_cities({"NYC": (0, 0, "UTC")})
        assert missing == {"NYC"}

    def test_missing_cities_helper_treats_corrupt_file_as_all_missing(
        self, tmp_path, monkeypatch
    ):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text("{not valid json")
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        missing = climatology._sigma_cache_missing_cities({"NYC": (0, 0, "UTC")})
        assert missing == {"NYC"}

    def test_missing_cities_helper_returns_empty_when_all_present(
        self, tmp_path, monkeypatch
    ):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(json.dumps({"NYC": {"max": {"1": 3.0}, "min": {}}}))
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        missing = climatology._sigma_cache_missing_cities({"NYC": (0, 0, "UTC")})
        assert missing == set()

    def test_missing_cities_helper_treats_empty_entry_as_missing(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught 2026-08-07: a city KEY present in the file with
        no real computed data (both max and min empty -- e.g. a prior compute
        failed because the climate archive wasn't downloaded yet) must still
        count as missing, or it gets stuck that way for _SIGMA_CACHE_AGE."""
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(json.dumps({"NYC": {"max": {}, "min": {}}}))
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        missing = climatology._sigma_cache_missing_cities({"NYC": (0, 0, "UTC")})
        assert missing == {"NYC"}

    def test_missing_cities_helper_treats_non_dict_json_as_all_missing(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught 2026-08-07: valid JSON that isn't an object
        (null, a list, ...) must degrade gracefully, not raise out of the
        helper -- `set(existing)` on a non-dict either raises or silently
        does the wrong thing (e.g. iterating list elements as city names)."""
        cache_path = tmp_path / "sigma.json"
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        for bad_content in ("null", "[]", '"a string"', "42"):
            cache_path.write_text(bad_content)
            missing = climatology._sigma_cache_missing_cities({"NYC": (0, 0, "UTC")})
            assert missing == {"NYC"}, f"failed for content={bad_content!r}"


class TestSigmaCacheRobustness:
    """opus-review-caught 2026-08-07 (post-merge-fix review): the merge fix's
    own machinery had three further gaps -- load_all_sigmas()'s force=False
    fast path didn't check for missing/empty cities at all (so the ACTUAL
    live cron path, which calls load_all_sigmas() directly via
    weather_markets._load_dynamic_sigma() and never goes through
    preload_all()'s gate, was still exposed to the original bug); non-dict
    JSON content crashed instead of degrading; and a transient compute
    failure could silently overwrite a city's previously-good entry with an
    empty one.
    """

    def test_fresh_path_still_recomputes_a_missing_city(self, tmp_path, monkeypatch):
        """The actual live-path regression: weather_markets._load_dynamic_sigma
        calls load_all_sigmas(CITY_COORDS, force=False) directly -- never
        through preload_all(). A fresh (recently-written) file missing a
        newly-added city must NOT be silently accepted as-is -- the call must
        fall through to a real recompute rather than returning the file as-is
        with LasVegas absent."""
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(json.dumps({"NYC": {"max": {"1": 1.1}, "min": {}}}))
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {
            "NYC": (40.7, -74.0, "America/New_York"),
            "LasVegas": (36.17, -115.14, "America/Los_Angeles"),
        }
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 2.9}
        ) as mock_compute:
            result = climatology.load_all_sigmas(city_coords, force=False)
        mock_compute.assert_called()
        assert result["LasVegas"]["max"]["1"] == 2.9  # newly computed
        assert "LasVegas" in result and "NYC" in result

    def test_fresh_path_recomputes_a_present_but_empty_city(
        self, tmp_path, monkeypatch
    ):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(json.dumps({"NYC": {"max": {}, "min": {}}}))
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ) as mock_compute:
            result = climatology.load_all_sigmas(city_coords, force=False)
        mock_compute.assert_called()
        assert result["NYC"]["max"]["1"] == 3.0

    def test_non_dict_json_does_not_crash_load_all_sigmas(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text("null")
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(
            climatology, "compute_sigma_from_climate", return_value={1: 3.0}
        ):
            result = climatology.load_all_sigmas(city_coords, force=True)
        assert result["NYC"]["max"]["1"] == 3.0

    def test_transient_empty_compute_does_not_clobber_existing_good_entry(
        self, tmp_path, monkeypatch
    ):
        """A city that already has real data must survive a later call where
        compute_sigma_from_climate() comes back empty for that city (e.g. a
        network blip) -- the empty result must not overwrite the good one."""
        cache_path = tmp_path / "sigma.json"
        cache_path.write_text(
            json.dumps({"NYC": {"max": {"1": 3.3}, "min": {"1": 2.2}}})
        )
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", cache_path)
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with patch.object(climatology, "compute_sigma_from_climate", return_value={}):
            result = climatology.load_all_sigmas(city_coords, force=True)
        assert result["NYC"]["max"]["1"] == 3.3
        assert result["NYC"]["min"]["1"] == 2.2

    def test_second_preload_all_call_retries_after_a_failed_compute(
        self, tmp_path, monkeypatch
    ):
        """opus-review-caught: a city that failed to compute (empty result,
        e.g. fetch_historical() had no data on a fresh install) must not get
        stuck -- the next preload_all() call for that city should retry, not
        treat the empty entry as already-satisfied."""
        sigma_path = tmp_path / "sigma.json"
        monkeypatch.setattr(climatology, "_SIGMA_CACHE_PATH", sigma_path)
        monkeypatch.setattr(
            climatology, "_cache_path", lambda city: tmp_path / f"climate_{city}.json"
        )
        city_coords = {"NYC": (40.7, -74.0, "America/New_York")}
        with (
            patch.object(climatology, "fetch_historical", return_value=None),
            patch.object(
                climatology, "compute_sigma_from_climate", return_value={}
            ) as mock_compute,
        ):
            climatology.preload_all(city_coords)
            calls_after_first = mock_compute.call_count
            assert calls_after_first > 0
            climatology.preload_all(city_coords)
        assert mock_compute.call_count > calls_after_first
