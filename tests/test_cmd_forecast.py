"""Tests for main.cmd_forecast's date computation (AUD-0045, 2026-08-18
max-depth forensic audit).

cmd_forecast(city) used to anchor its 7-day display window on
utils.utc_today() with no per-city ZoneInfo adjustment, despite city being a
known parameter -- during the evening window where UTC's calendar date has
rolled over but the city's has not, the row labeled "today" actually showed
tomorrow's local forecast, and the city's real local today was omitted from
the window entirely. Fixed to compute today via
ZoneInfo(_CITY_TZ.get(city, ...)), mirroring _feature_importance_days_out's
established local-today pattern, with a UTC fallback on ZoneInfo failure.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import main


class TestCmdForecastLocalToday:
    def test_unknown_city_prints_error_and_never_calls_get_weather_forecast(self):
        with patch.object(main, "get_weather_forecast") as mock_gwf:
            main.cmd_forecast("NotACity")
        mock_gwf.assert_not_called()

    def test_utc_rollover_window_uses_city_local_today(self):
        """At 2026-07-10 02:00 UTC, UTC has already rolled to 2026-07-10, but
        LA (UTC-7, PDT) is still 2026-07-09. The first (i=0, "today") date
        requested from get_weather_forecast must be LA's actual local today
        (07-09), not UTC's already-rolled-over 07-10 -- proves a real
        per-city ZoneInfo lookup, not merely "some non-UTC zone" or a lookup
        that silently resolves to the function's own America/New_York
        fallback default (LA's zone genuinely differs from both)."""
        fixed_instant = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        requested_dates = []

        def _fake_gwf(city, d):
            requested_dates.append(d)
            return None  # no forecast data needed -- only checking the date arg

        with (
            patch.object(main, "datetime", _FixedDatetime),
            patch.object(main, "get_weather_forecast", side_effect=_fake_gwf),
        ):
            main.cmd_forecast("LA")

        assert requested_dates[0].isoformat() == "2026-07-09"
        assert len(requested_dates) == 7
        assert requested_dates[-1].isoformat() == "2026-07-15"

    def test_zoneinfo_failure_falls_back_to_utc(self):
        """If ZoneInfo construction raises for any reason, cmd_forecast must
        fall back to UTC's today rather than propagate the exception.

        Opus-review-caught: the original instant (2026-07-10 12:00 UTC) gave
        Phoenix (UTC-7, no DST) the same calendar date as UTC itself (both
        07-10), so the assertion held whether or not the ZoneInfo-failure
        except branch actually ran -- it couldn't tell "used the UTC
        fallback" apart from "somehow still resolved Phoenix's real local
        date". Using 02:00 UTC instead, where Phoenix's real local date
        (07-09) genuinely differs from UTC's (07-10), makes the assertion
        prove the fallback path specifically."""
        fixed_instant = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        requested_dates = []

        def _fake_gwf(city, d):
            requested_dates.append(d)
            return None

        with (
            patch.object(main, "datetime", _FixedDatetime),
            patch("zoneinfo.ZoneInfo", side_effect=RuntimeError("boom")),
            patch.object(main, "get_weather_forecast", side_effect=_fake_gwf),
        ):
            main.cmd_forecast("Phoenix")

        assert requested_dates[0].isoformat() == "2026-07-10"
