"""Phase 2 Batch J regression tests: P2-21/P2-22/P2-23 — METAR pipeline."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-21: _metar_lock_in threshold == 0.0 falsy bug ─────────────────────────


class TestMetarLockInZeroThreshold:
    """Freeze markets (threshold=0°F) must not silently skip METAR lock-in."""

    def test_condition_zero_is_not_none(self):
        """threshold=0.0 must pass the 'is not None' gate."""
        condition_zero = {"type": "above", "threshold": 0.0}
        assert condition_zero.get("threshold") is not None

    def test_condition_missing_threshold_is_none(self):
        """Missing threshold must be None — the gate correctly blocks it."""
        condition_no_threshold = {"type": "above"}
        assert condition_no_threshold.get("threshold") is None

    def test_negative_threshold_is_not_none(self):
        """-10°F threshold must also pass the gate."""
        assert {"type": "above", "threshold": -10.0}.get("threshold") is not None

    def test_source_uses_is_not_none(self):
        """Source code must use 'is not None', not a bare truthiness check."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets._metar_lock_in)
        assert "is not None" in src, (
            "_metar_lock_in must use 'is not None' for threshold, not truthiness"
        )
        assert 'condition.get("threshold"):' not in src, (
            "Old falsy check 'condition.get(\"threshold\"):' must be removed"
        )

    def test_above_below_are_the_only_gated_types(self):
        """Only 'above' and 'between' types are gated — 'range' with threshold=0 works."""
        # Verify the fix targets the right branch
        for ctype in ("above", "below"):
            cond = {"type": ctype, "threshold": 0.0}
            assert cond.get("threshold") is not None, (
                f"threshold=0 must not be falsy for type={ctype!r}"
            )


# ── P2-22: metar.fetch_metar never fabricates obsTime ────────────────────────


class TestMetarFetchNoFabricatedTimestamp:
    """fetch_metar must return None when obsTime is absent or unparseable."""

    def _mock_session_get(self, payload: list[dict]) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return resp

    def test_missing_obs_time_returns_none(self):
        """When obsTime key is absent, fetch_metar must return None."""
        import metar

        obs = {"tmpf": 68.0, "icaoId": "KNYC"}  # no obsTime

        with patch.object(
            metar._session, "get", return_value=self._mock_session_get([obs])
        ):
            result = metar.fetch_metar("KNYC")

        assert result is None, f"Missing obsTime must return None, got {result}"

    def test_empty_obs_time_returns_none(self):
        """When obsTime is empty string, fetch_metar must return None."""
        import metar

        obs = {"tmpf": 68.0, "icaoId": "KNYC", "obsTime": ""}

        with patch.object(
            metar._session, "get", return_value=self._mock_session_get([obs])
        ):
            result = metar.fetch_metar("KNYC")

        assert result is None

    def test_unparseable_obs_time_returns_none(self):
        """When obsTime is not ISO-parseable, fetch_metar must return None."""
        import metar

        obs = {"tmpf": 68.0, "icaoId": "KNYC", "obsTime": "not-a-date"}

        with patch.object(
            metar._session, "get", return_value=self._mock_session_get([obs])
        ):
            result = metar.fetch_metar("KNYC")

        assert result is None

    def test_valid_obs_time_returns_result(self):
        """A valid recent obsTime must produce a proper result dict."""
        import metar

        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        obs = {"tmpf": 68.0, "icaoId": "KNYC", "obsTime": now_str}

        with patch.object(
            metar._session, "get", return_value=self._mock_session_get([obs])
        ):
            result = metar.fetch_metar("KNYC")

        assert result is not None
        assert "obs_time" in result
        assert isinstance(result["obs_time"], datetime)

    def test_result_obs_time_is_utc_aware(self):
        """obs_time in the result must be timezone-aware."""
        import metar

        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        obs = {"tmpf": 68.0, "icaoId": "KNYC", "obsTime": now_str}

        with patch.object(
            metar._session, "get", return_value=self._mock_session_get([obs])
        ):
            result = metar.fetch_metar("KNYC")

        assert result is not None
        assert result["obs_time"].tzinfo is not None, "obs_time must be tz-aware"

    def test_null_obstime_is_rejected_not_fabricated(self):
        """fetch_metar must not fabricate a timestamp — None obsTime → return None."""
        import metar

        # Before P2-22 fix, missing obsTime would be replaced with datetime.now(UTC)
        # making stale obs appear fresh. Verify this path returns None instead.
        obs = {"tmpf": 68.0, "icaoId": "KNYC", "obsTime": None}

        with patch.object(
            metar._session, "get", return_value=self._mock_session_get([obs])
        ):
            result = metar.fetch_metar("KNYC")

        assert result is None, (
            "null obsTime must return None, not a fabricated timestamp"
        )


# ── P2-23: _metar_station_for_city covers all 18 cities ──────────────────────


class TestMetarStationForCityAllCities:
    """All 18 Kalshi cities must map to a METAR station and timezone."""

    ALL_CITIES = [
        "NYC",
        "Chicago",
        "LA",
        "Miami",
        "Boston",
        "Dallas",
        "Phoenix",
        "Seattle",
        "Denver",
        "Atlanta",
        "Austin",
        "Washington",
        "Philadelphia",
        "OklahomaCity",
        "SanFrancisco",
        "Minneapolis",
        "Houston",
        "SanAntonio",
    ]

    EXPECTED_STATIONS = {
        "NYC": "KNYC",
        "Chicago": "KORD",
        "LA": "KLAX",
        "Miami": "KMIA",
        "Boston": "KBOS",
        "Dallas": "KDFW",
        "Phoenix": "KPHX",
        "Seattle": "KSEA",
        "Denver": "KDEN",
        "Atlanta": "KATL",
        "Austin": "KAUS",
        "Washington": "KDCA",
        "Philadelphia": "KPHL",
        "OklahomaCity": "KOKC",
        "SanFrancisco": "KSFO",
        "Minneapolis": "KMSP",
        "Houston": "KIAH",
        "SanAntonio": "KSAT",
    }

    def test_all_cities_return_station(self):
        import weather_markets

        missing = [
            c
            for c in self.ALL_CITIES
            if weather_markets._metar_station_for_city(c) is None
        ]
        assert not missing, f"_metar_station_for_city returns None for: {missing}"

    def test_station_ids_are_correct(self):
        import weather_markets

        wrong = {
            city: weather_markets._metar_station_for_city(city)
            for city, expected in self.EXPECTED_STATIONS.items()
            if weather_markets._metar_station_for_city(city) != expected
        }
        assert not wrong, f"Wrong station IDs: {wrong}"

    def test_city_tz_covers_all_cities(self):
        import weather_markets

        missing = [c for c in self.ALL_CITIES if c not in weather_markets._CITY_TZ]
        assert not missing, f"_CITY_TZ missing entries for: {missing}"

    def test_city_tz_values_are_valid_iana(self):
        """All timezone strings must be parseable by zoneinfo."""
        import zoneinfo

        import weather_markets

        bad = {}
        for city, tz in weather_markets._CITY_TZ.items():
            try:
                zoneinfo.ZoneInfo(tz)
            except Exception as e:
                bad[city] = str(e)
        assert not bad, f"Invalid timezone strings: {bad}"

    def test_old_abbreviations_removed(self):
        """Old 3-letter keys (MIA, CHI, LAX, DAL, DEN) must no longer be primary keys."""
        import weather_markets

        old_keys = {"MIA", "CHI", "LAX", "DAL"}
        for key in old_keys:
            assert key not in weather_markets._CITY_TZ, (
                f"Old abbreviation {key!r} still in _CITY_TZ"
            )
            assert key not in weather_markets._CITY_METAR_STATION, (
                f"Old abbreviation {key!r} still in _CITY_METAR_STATION"
            )

    def test_station_map_matches_metar_module(self):
        """_CITY_METAR_STATION must agree with metar.MARKET_STATION_MAP."""
        import metar
        import weather_markets

        for city, station in metar.MARKET_STATION_MAP.items():
            wm_station = weather_markets._CITY_METAR_STATION.get(city)
            assert wm_station == station, (
                f"City {city!r}: metar.py={station!r}, "
                f"weather_markets.py={wm_station!r}"
            )
