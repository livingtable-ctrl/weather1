"""Tests for climatology.py's climate-derived sigma (restored 2026-07-12 --
silently lost in the 24559a7 mystery-revert, see backlog.txt).
"""

from __future__ import annotations

import json
from unittest.mock import patch

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
    def setup_method(self, method):
        climatology._sigma_mem_cache = {}

    def teardown_method(self, method):
        climatology._sigma_mem_cache = {}

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
        import time

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
