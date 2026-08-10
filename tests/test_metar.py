"""Tests for METAR same-day lock-in strategy."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from forecast_cache import ForecastCache

sys.path.insert(0, str(Path(__file__).parent.parent))


def _fresh_obs_time() -> str:
    """Return an obsTime string 15 minutes in the past (always within the 90-min staleness gate)."""
    return (datetime.now(UTC) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")


# Sample METAR API response — uses a fresh obsTime so P1-2 staleness gate accepts it
METAR_RESPONSE = [
    {
        "icaoId": "KNYC",
        "obsTime": _fresh_obs_time(),
        "temp": 22.2,  # °C (72°F)
        "dewp": 10.0,
        "tmpf": 72.0,  # °F if provided, else computed
    }
]

METAR_RESPONSE_COLD = [
    {
        "icaoId": "KNYC",
        "obsTime": _fresh_obs_time(),
        "temp": 10.0,  # 50°F — clearly below a 65°F threshold
        "dewp": 5.0,
    }
]


class TestFetchMetar:
    def test_returns_current_temp_f(self):
        """fetch_metar returns current_temp_f in Fahrenheit."""
        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = METAR_RESPONSE
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is not None
        assert "current_temp_f" in result
        assert result["current_temp_f"] == pytest.approx(72.0, abs=0.5)

    def test_celsius_converted_to_fahrenheit(self):
        """If only Celsius provided, convert to Fahrenheit."""
        import metar

        response = [{"icaoId": "KNYC", "obsTime": _fresh_obs_time(), "temp": 20.0}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result["current_temp_f"] == pytest.approx(68.0, abs=0.2)

    def test_returns_none_on_failure(self):
        import requests

        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.side_effect = requests.RequestException("timeout")
            result = metar.fetch_metar("KNYC")

        assert result is None

    def test_negative_caches_failure(self):
        """A failed fetch must be negative-cached -- a second call within the
        TTL must not re-invoke the session (2026-07-19 ForecastCache
        migration: get_with_ts() must distinguish a real cached None from
        no-entry-at-all)."""
        import requests

        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.side_effect = requests.RequestException("timeout")
            first = metar.fetch_metar("KNYC")
            assert first is None
            assert mock.get.call_count == 1

            second = metar.fetch_metar("KNYC")
            assert second is None
            assert mock.get.call_count == 1, (
                "negative-cached hit must not re-call the session"
            )

    def test_returns_none_on_empty_response(self):
        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = []
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None

    # ── P1-2: staleness gate ──────────────────────────────────────────────────

    def test_returns_none_when_obstime_missing(self):
        """P1-2: response with no obsTime key → None (no fabricated timestamp)."""
        import metar

        response = [{"icaoId": "KNYC", "tmpf": 72.0}]  # no obsTime
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None, (
            "fetch_metar must return None when obsTime is absent — "
            "fabricating a timestamp would make a stale observation appear current"
        )

    def test_returns_none_when_obstime_unparseable(self):
        """P1-2: response with invalid obsTime string → None."""
        import metar

        response = [{"icaoId": "KNYC", "tmpf": 72.0, "obsTime": "not-a-date"}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None

    def test_returns_none_when_observation_stale(self):
        """P1-2: observation older than 90 minutes → None."""
        import metar

        stale_time = (datetime.now(UTC) - timedelta(minutes=120)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [{"icaoId": "KNYC", "tmpf": 72.0, "obsTime": stale_time}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None, (
            "fetch_metar must return None for a 120-minute-old observation"
        )

    def test_returns_result_when_observation_fresh(self):
        """P1-2: observation 30 minutes old → accepted."""
        import metar

        fresh_time = (datetime.now(UTC) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [{"icaoId": "KNYC", "tmpf": 72.0, "obsTime": fresh_time}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is not None
        assert result["current_temp_f"] == pytest.approx(72.0)

    def test_returns_none_for_implausible_high_temp(self):
        """P1-2: temperature above 140°F → None (physically impossible)."""
        import metar

        fresh_time = (datetime.now(UTC) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [{"icaoId": "KNYC", "tmpf": 999.0, "obsTime": fresh_time}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None

    def test_returns_none_for_implausible_low_temp(self):
        """P1-2: temperature below -80°F → None (physically impossible)."""
        import metar

        fresh_time = (datetime.now(UTC) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [{"icaoId": "KNYC", "tmpf": -100.0, "obsTime": fresh_time}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None

    def test_max_min_temp_f_parsed_from_real_api_field_names(self):
        """Regression for the field-name bug found by opus review of
        backlog.txt "BETWEEN-BUCKET MARKETS ... METAR LOCK-IN WAS DISABLED"
        (2026-08-09): aviationweather.gov's real /api/data/metar payload has
        no "minf"/"maxf" field at all -- only "maxT"/"minT" in CELSIUS. Code
        that read "minf"/"maxf" silently got None for every observation ever
        fetched, in production, since fetch_metar was written -- every caller
        (both above/below's own daily-extreme branch and the newly re-enabled
        between branch) always fell back to current_temp_f without ever
        knowing it. Payload below is verbatim field shape from a real
        aviationweather.gov response captured 2026-08-09 (KJFK:
        temp=32.2, maxT=32.8, minT=25.6 -- all Celsius)."""
        import metar

        fresh_time = (datetime.now(UTC) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [
            {
                "icaoId": "KJFK",
                "obsTime": fresh_time,
                "temp": 32.2,
                "dewp": 20.0,
                "maxT": 32.8,
                "minT": 25.6,
            }
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KJFK")

        assert result is not None
        assert result["max_temp_f"] == pytest.approx(91.04, abs=0.1), (
            f"max_temp_f not parsed from maxT (Celsius): got {result['max_temp_f']!r}"
        )
        assert result["min_temp_f"] == pytest.approx(78.08, abs=0.1), (
            f"min_temp_f not parsed from minT (Celsius): got {result['min_temp_f']!r}"
        )

    def test_max_min_temp_f_prefers_fahrenheit_field_if_ever_present(self):
        """Defensive: if the API ever adds a Fahrenheit extreme field, prefer
        it over converting the Celsius one (mirrors current_temp_f's own
        tmpf-then-temp preference)."""
        import metar

        fresh_time = (datetime.now(UTC) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [
            {
                "icaoId": "KJFK",
                "obsTime": fresh_time,
                "temp": 32.2,
                "maxf": 90.0,  # Fahrenheit -- should win over maxT below
                "maxT": 32.8,  # Celsius -- would be ~91.0F if converted
                "minf": 80.0,
                "minT": 25.6,
            }
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KJFK")

        assert result["max_temp_f"] == pytest.approx(90.0, abs=0.01)
        assert result["min_temp_f"] == pytest.approx(80.0, abs=0.01)

    def test_dew_point_f_parsed_from_real_dewp_celsius_field(self):
        """Regression for the same field-name bug: the real payload's dew
        point field is "dewp" (Celsius), not "dwpt" -- the code's prior
        second-choice fallback. dew_point_f was also always None in
        production before this fix (KJFK: dewp=20.0C -> 68.0F)."""
        import metar

        fresh_time = (datetime.now(UTC) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        response = [
            {"icaoId": "KJFK", "obsTime": fresh_time, "temp": 32.2, "dewp": 20.0}
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KJFK")

        assert result["dew_point_f"] == pytest.approx(68.0, abs=0.1), (
            f"dew_point_f not parsed from dewp (Celsius): got {result['dew_point_f']!r}"
        )


class TestFetchMetarDailyExtreme:
    """Tests for fetch_metar_daily_extreme / _fetch_daily_temps_f — the
    true running-daily-extreme computation added 2026-08-09 (backlog.txt
    "SETTLEMENT_MONITOR.PY'S OWN BETWEEN-BUCKET LOCK...") after live-
    verifying that fetch_metar()'s own max_temp_f/min_temp_f fields are a
    sparse 6-hour synoptic-window value, not a value that accumulates since
    local midnight.
    """

    @staticmethod
    def _epoch(dt) -> int:
        return int(dt.timestamp())

    def test_computes_max_across_multiple_readings_same_local_date(self):
        """Daily max is the max of ALL today's readings, not just the
        latest one or a synoptic-hour maxT field."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        # Readings across the local day — the highest (91.4F) is neither
        # the first nor the last in the list, and none of them carry a
        # maxT/minT field at all (mirrors the real API's sparse synoptic
        # reporting — this function must not depend on that field).
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 18, 0, tzinfo=tz)),
                "tmpf": 84.0,
            },
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 14, 0, tzinfo=tz)),
                "tmpf": 91.4,
            },
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 10, 0, tzinfo=tz)),
                "tmpf": 76.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )

        assert result == pytest.approx(91.4)

    def test_computes_min_across_multiple_readings_same_local_date(self):
        """extreme='min' returns the lowest reading, not the highest."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 18, 0, tzinfo=tz)),
                "tmpf": 84.0,
            },
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 6, 0, tzinfo=tz)),
                "tmpf": 58.5,
            },
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 10, 0, tzinfo=tz)),
                "tmpf": 76.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "min"
            )

        assert result == pytest.approx(58.5)

    def test_excludes_readings_from_a_different_local_date(self):
        """A reading from the PRIOR local calendar day (e.g. a UTC obsTime
        that converts to ~11 PM the previous evening) must not pollute
        today's extreme — the exact class of date-guard bug e395392 fixed
        for the instantaneous-reading path."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 14, 0, tzinfo=tz)),
                "tmpf": 80.0,
            },
            # Prior day, would be the max if wrongly included
            {
                "obsTime": self._epoch(datetime(2026, 8, 8, 23, 0, tzinfo=tz)),
                "tmpf": 99.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )

        assert result == pytest.approx(80.0)

    def test_returns_none_on_fetch_failure(self):
        import requests

        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.side_effect = requests.RequestException("timeout")
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", datetime(2026, 8, 9).date(), "max"
            )

        assert result is None

    def test_returns_none_when_no_readings_match_target_date(self):
        """Fetch succeeds but every reading is from a different date (e.g.
        called right after local midnight, before today's first ob) → None,
        not a crash or a stale/wrong value."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 0, 5, tzinfo=tz).date()
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 8, 23, 0, tzinfo=tz)),
                "tmpf": 80.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )

        assert result is None

    def test_ignores_sparse_synoptic_maxt_field_uses_raw_readings_instead(self):
        """Regression guard for the exact bug this function exists to fix:
        even when a reading carries a (stale, 6h-windowed) maxT field lower
        than the TRUE max among today's raw temp readings, the function
        must return the true max, not the misleading maxT value."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 19, 0, tzinfo=tz).date()
        response = [
            # Synoptic report with a maxT far below the real later peak —
            # this function must ignore maxT entirely.
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 12, 0, tzinfo=tz)),
                "tmpf": 70.0,
                "maxT": 21.1,  # ~70F — stale/irrelevant to this function
            },
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 15, 0, tzinfo=tz)),
                "tmpf": 94.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )

        assert result == pytest.approx(94.0)

    def test_second_call_within_ttl_does_not_refetch(self):
        """Cache hit: a second call for the same station+date within the
        TTL must not re-invoke the session."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 14, 0, tzinfo=tz)),
                "tmpf": 80.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            first = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )
            assert first == pytest.approx(80.0)
            assert mock.get.call_count == 1

            second = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "min"
            )
            assert second == pytest.approx(80.0)
            assert mock.get.call_count == 1, (
                "second call (even for a different extreme) must reuse the "
                "cached station+date reading list, not re-fetch"
            )

    def test_uses_celsius_temp_field_when_tmpf_absent(self):
        """The REAL aviationweather.gov payload has no tmpf field at all —
        only "temp" in Celsius (same field-name reality documented at
        TestFetchMetar.test_max_min_temp_f_parsed_from_real_api_field_names
        above). Mutation-tested 2026-08-09 (opus review): all other tests in
        this class use a "tmpf"-only fixture, so a mutant that broke the
        Celsius-conversion branch entirely passed every one of them —
        production would have silently returned None for every station."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 9, 14, 0, tzinfo=tz)),
                "temp": 32.2,  # Celsius, no tmpf key — real payload shape
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )

        assert result == pytest.approx(89.96, abs=0.1)

    def test_requests_a_wide_hours_window_not_just_the_latest_reading(self):
        """Mutation-tested 2026-08-09: without an explicit `hours` param the
        API returns only the single latest observation, degenerating this
        function into the exact single-reading bug it exists to fix. Assert
        the request actually asks for a wide window."""
        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = []
            mock.get.return_value.raise_for_status.return_value = None
            metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", datetime(2026, 8, 9).date(), "max"
            )

        _args, kwargs = mock.get.call_args
        assert "hours" in kwargs["params"], (
            "request must specify an hours window, not rely on the API's "
            "single-latest-observation default"
        )
        assert int(kwargs["params"]["hours"]) >= 24, (
            "hours window must be wide enough to cover local midnight to "
            "now for any continental-US timezone"
        )

    def test_cache_key_includes_target_date_not_just_station(self):
        """Mutation-tested 2026-08-09: a station-only cache key would leak
        one date's reading list into another date's lookup — the exact
        cross-midnight pollution class of bug the per-date key exists to
        prevent. Same station, two different target dates, must each
        trigger their own fetch."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        day1 = datetime(2026, 8, 8, 15, 0, tzinfo=tz).date()
        day2 = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        response = [
            {
                "obsTime": self._epoch(datetime(2026, 8, 8, 14, 0, tzinfo=tz)),
                "tmpf": 60.0,
            },
        ]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            metar.fetch_metar_daily_extreme("KNYC", "America/New_York", day1, "max")
            assert mock.get.call_count == 1

            metar.fetch_metar_daily_extreme("KNYC", "America/New_York", day2, "max")
            assert mock.get.call_count == 2, (
                "a different target_date for the same station must not "
                "reuse day1's cached reading list"
            )

    def test_negative_caches_fetch_failure(self):
        """A failed fetch must be negative-cached — a second call within the
        TTL must not re-invoke the session (mirrors fetch_metar()'s own
        test_negative_caches_failure)."""
        import requests

        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.side_effect = requests.RequestException("timeout")
            first = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", datetime(2026, 8, 9).date(), "max"
            )
            assert first is None
            assert mock.get.call_count == 1

            second = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", datetime(2026, 8, 9).date(), "max"
            )
            assert second is None
            assert mock.get.call_count == 1, (
                "negative-cached hit must not re-call the session"
            )

    def test_obs_time_accepts_iso_string_not_only_epoch(self):
        """_extract_obs_time must also accept an ISO-8601 string obsTime
        (test-fixture convention used throughout this file, and a defensive
        fallback matching fetch_metar()'s own permissiveness), not only the
        numeric epoch the live API currently returns."""
        from zoneinfo import ZoneInfo

        import metar

        tz = ZoneInfo("America/New_York")
        target = datetime(2026, 8, 9, 15, 0, tzinfo=tz).date()
        iso_time = datetime(2026, 8, 9, 14, 0, tzinfo=tz).astimezone(UTC).isoformat()
        response = [{"obsTime": iso_time, "tmpf": 77.0}]
        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = response
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", target, "max"
            )

        assert result == pytest.approx(77.0)

    def test_invalid_extreme_argument_raises(self):
        """extreme must be exactly 'max' or 'min' — a typo like 'MAX' must
        raise loudly, not silently fall through to 'min' semantics."""
        import metar

        with pytest.raises(ValueError):
            metar.fetch_metar_daily_extreme(
                "KNYC", "America/New_York", datetime(2026, 8, 9).date(), "MAX"
            )


class TestCheckMetarLockout:
    def test_locked_below_threshold_after_2pm(self):
        """
        At 5 PM local with temp 10°C (50°F), threshold 65°F 'above' → locked OUT
        (it can't reach 65°F by end of day, so 'above' is False → bet NO).
        """
        import metar

        obs_time = datetime(2026, 4, 17, 21, 0, tzinfo=UTC)  # 5 PM ET
        result = metar.check_metar_lockout(
            current_temp_f=50.0,
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert result["locked"] is True
        assert result["outcome"] == "no"
        assert result["confidence"] >= 0.88

    def test_locked_above_threshold_after_2pm(self):
        """
        At 5 PM local with current temp 80°F, threshold 65°F 'above' → locked IN
        (it has already exceeded 65°F, so 'above' is True → bet YES).
        """
        import metar

        obs_time = datetime(2026, 4, 17, 21, 0, tzinfo=UTC)  # 5 PM ET
        result = metar.check_metar_lockout(
            current_temp_f=80.0,
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert result["locked"] is True
        assert result["outcome"] == "yes"
        assert result["confidence"] >= 0.88

    def test_not_locked_before_2pm(self):
        """Before 2 PM local, never lock in regardless of temperature."""
        import metar

        obs_time = datetime(2026, 4, 17, 16, 0, tzinfo=UTC)  # noon ET
        result = metar.check_metar_lockout(
            current_temp_f=80.0,
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert result["locked"] is False

    def test_not_locked_within_margin(self):
        """Temperature within margin_f of threshold is too close to lock in."""
        import metar

        obs_time = datetime(2026, 4, 17, 21, 0, tzinfo=UTC)  # 5 PM ET
        result = metar.check_metar_lockout(
            current_temp_f=64.0,  # only 1°F below threshold
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,  # require 3°F clearance
        )

        assert result["locked"] is False


# ── L6-D regression: dynamic lock-in confidence ──────────────────────────────


class TestDynamicLockInConfidence:
    """Regression tests for L6-D: METAR lock-in confidence must scale with
    temperature clearance and time of day rather than using a hardcoded 0.90.

    Previously _LOCK_IN_CONFIDENCE = 0.90 was applied unconditionally, causing
    near-threshold afternoon lock-ins (e.g. 3°F at 2 PM) to be treated with
    the same confidence as clear afternoon lock-ins (e.g. 15°F at 10 PM).
    """

    def test_near_threshold_early_afternoon_confidence_below_old_hardcoded(self):
        """Regression for L6-D: 3°F clearance at 2 PM must yield confidence < 0.90.

        Before fix: hardcoded 0.90.  After fix: 0.720 — avoids over-betting
        near-threshold markets at the earliest lock-in hour.
        """
        import metar

        # 3°F above threshold (exactly at the default margin), 2 PM ET
        obs_time = datetime(2026, 4, 17, 18, 0, tzinfo=UTC)  # 2 PM ET (UTC-4 in April)
        result = metar.check_metar_lockout(
            current_temp_f=68.0,  # threshold + 3°F (just at trigger margin)
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert result["locked"] is True
        assert result["confidence"] < 0.90, (
            f"Near-threshold afternoon lock-in gave confidence={result['confidence']:.3f}; "
            f"must be < 0.90 to avoid over-betting (was hardcoded 0.90 before L6-D fix)"
        )
        # Must still be a meaningful probability (not negligible)
        assert result["confidence"] >= 0.70, (
            f"Confidence {result['confidence']:.3f} too low — lock-in should still be useful"
        )

    def test_large_clearance_late_evening_gets_high_confidence(self):
        """Regression for L6-D: 15°F clearance at 10 PM must yield confidence >= 0.90.

        Large margin + late hour → outcome is very certain; Kelly should be high.
        """
        import metar

        # 15°F above threshold, 10 PM ET
        obs_time = datetime(2026, 4, 18, 2, 0, tzinfo=UTC)  # 10 PM ET
        result = metar.check_metar_lockout(
            current_temp_f=80.0,  # threshold + 15°F
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert result["locked"] is True
        assert result["confidence"] >= 0.90, (
            f"Large-clearance late-evening lock-in gave confidence={result['confidence']:.3f}; "
            f"must be >= 0.90 for a 15°F margin at 10 PM"
        )

    def test_confidence_increases_with_clearance(self):
        """Confidence must be strictly higher for larger temperature clearance
        at the same time of day."""
        import metar

        obs_time = datetime(2026, 4, 17, 21, 0, tzinfo=UTC)  # 5 PM ET

        small = metar.check_metar_lockout(
            current_temp_f=68.0,  # 3°F above threshold
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )
        large = metar.check_metar_lockout(
            current_temp_f=78.0,  # 13°F above threshold
            threshold_f=65.0,
            direction="above",
            obs_time=obs_time,
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert small["locked"] is True
        assert large["locked"] is True
        assert large["confidence"] > small["confidence"], (
            f"Larger clearance must give higher confidence: "
            f"13°F={large['confidence']:.3f} vs 3°F={small['confidence']:.3f}"
        )

    def test_confidence_increases_with_hour(self):
        """Confidence must be strictly higher for a later observation time
        with the same temperature clearance."""
        import metar

        early = metar.check_metar_lockout(
            current_temp_f=78.0,  # 13°F above 65°F threshold
            threshold_f=65.0,
            direction="above",
            obs_time=datetime(2026, 4, 17, 18, 0, tzinfo=UTC),  # 2 PM ET
            city_tz="America/New_York",
            margin_f=3.0,
        )
        late = metar.check_metar_lockout(
            current_temp_f=78.0,  # same clearance
            threshold_f=65.0,
            direction="above",
            obs_time=datetime(2026, 4, 18, 2, 0, tzinfo=UTC),  # 10 PM ET
            city_tz="America/New_York",
            margin_f=3.0,
        )

        assert early["locked"] is True
        assert late["locked"] is True
        assert late["confidence"] > early["confidence"], (
            f"Later lock-in must have higher confidence: "
            f"10 PM={late['confidence']:.3f} vs 2 PM={early['confidence']:.3f}"
        )


class TestDewPointCorrection:
    def test_dew_point_temp_correction_miami(self):
        """Miami humid day: dew=76, forecast=90 → depression=14°F < 20°F → negative correction."""
        from weather_markets import _dew_point_temp_correction

        correction = _dew_point_temp_correction(
            "Miami", dew_point_f=76.0, forecast_temp_f=90.0
        )
        assert correction < 0.0, (
            "Humid day should produce negative temperature correction"
        )
        assert correction >= -5.0, "Correction should not exceed -5°F bound"

    def test_dew_point_temp_correction_dry_city_no_effect(self):
        """Denver (not in sensitive set) must return 0.0 regardless of dew point."""
        from weather_markets import _dew_point_temp_correction

        correction = _dew_point_temp_correction(
            "Denver", dew_point_f=40.0, forecast_temp_f=85.0
        )
        assert correction == 0.0

    def test_dew_point_temp_correction_dry_conditions_no_effect(self):
        """Even for a sensitive city, depression >= 20°F means no correction."""
        from weather_markets import _dew_point_temp_correction

        correction = _dew_point_temp_correction(
            "Houston", dew_point_f=60.0, forecast_temp_f=90.0
        )
        assert correction == 0.0, "Depression=30 → no correction"

    def test_dew_point_temp_correction_at_saturation(self):
        """At depression=0 (saturated), correction is exactly -3.0 (the formula max)."""
        from weather_markets import _dew_point_temp_correction

        correction = _dew_point_temp_correction(
            "SanFrancisco", dew_point_f=70.0, forecast_temp_f=70.0
        )
        assert correction == -3.0

    def test_fetch_metar_includes_dew_point_f(self):
        """fetch_metar result dict must include dew_point_f key."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from metar import fetch_metar

        mock_data = [
            {
                "tmpf": "72.0",
                "dwpf": "65.0",
                "obsTime": int(datetime.now(UTC).timestamp()),
                "icaoId": "KMIA",
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status.return_value = None

        with patch("metar._METAR_CACHE", ForecastCache()):
            with patch("metar._session") as mock_session:
                mock_session.get.return_value = mock_resp
                result = fetch_metar("KMIA")

        assert result is not None
        assert "dew_point_f" in result
        assert result["dew_point_f"] == pytest.approx(65.0, abs=0.1)
