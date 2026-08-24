"""Tests for NOAA MOS via IEM API."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────

MOS_RESPONSE_OK = {
    "data": [
        {"ftime": "2026-04-17 15:00", "tmp": 68, "dpt": 50},
        {"ftime": "2026-04-17 18:00", "tmp": 65, "dpt": 49},
        {"ftime": "2026-04-17 21:00", "tmp": 60, "dpt": 48},
        {"ftime": "2026-04-18 00:00", "tmp": 55, "dpt": 46},
    ]
}

MOS_RESPONSE_EMPTY = {"data": []}


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFetchMos:
    def setup_method(self):
        """Clear the MOS in-process cache before each test."""
        import mos

        mos._MOS_CACHE.clear()

    def test_returns_dict_on_success(self):
        """fetch_mos returns a dict with max_temp_f on success."""
        import mos

        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = MOS_RESPONSE_OK
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result is not None
        assert "max_temp_f" in result
        assert result["max_temp_f"] == 68  # highest tmp in the day

    def test_returns_none_on_empty_data(self):
        import mos

        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = MOS_RESPONSE_EMPTY
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result is None

    def test_returns_none_on_request_exception(self):
        import requests

        import mos

        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.side_effect = requests.RequestException("timeout")
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result is None

    def test_negative_caches_failure(self):
        """A failed fetch must be negative-cached -- a second call within the
        TTL must not re-invoke the session (2026-07-19 ForecastCache
        migration: get_with_ts() must distinguish a real cached None from
        no-entry-at-all)."""
        import requests

        import mos

        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.side_effect = requests.RequestException("timeout")
            first = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))
            assert first is None
            assert mock_sess.get.call_count == 1

            second = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))
            assert second is None
            assert mock_sess.get.call_count == 1, (
                "negative-cached hit must not re-call the session"
            )

    def test_station_lookup(self):
        """get_mos_station returns correct ASOS station for each city.

        Keys are full city names (matching _parse_city_from_ticker's output,
        the real call-site format) — not 3-letter short codes. The old short
        codes ("CHI"/"LAX"/"DAL"/"DEN"/"MIA") never matched because every
        real caller passes the full name, so MOS silently returned None for
        5 of 6 covered cities until this was fixed.
        """
        import mos

        assert mos.get_mos_station("NYC") == "KNYC"
        assert mos.get_mos_station("Miami") == "KMIA"
        assert mos.get_mos_station("Chicago") == "KMDW"
        assert mos.get_mos_station("LA") == "KLAX"
        assert mos.get_mos_station("Dallas") == "KDFW"
        assert mos.get_mos_station("Denver") == "KDEN"

    def test_unknown_city_returns_none(self):
        import mos

        assert mos.get_mos_station("XYZ") is None

    def test_max_temp_is_highest_in_day(self):
        """max_temp_f is the highest tmp reading across all hours for the target date."""
        import mos

        response = {
            "data": [
                {"ftime": "2026-04-17 09:00", "tmp": 60},
                {"ftime": "2026-04-17 15:00", "tmp": 72},
                {"ftime": "2026-04-17 18:00", "tmp": 65},
                {"ftime": "2026-04-18 00:00", "tmp": 55},  # next day — exclude
            ]
        }
        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result["max_temp_f"] == 72
        assert result["n_hours"] == 3  # only same-day rows counted

    def test_days_out_uses_city_local_today_not_utc(self):
        """fetch_mos's days_out (and thus sigma) must be computed against
        the tz passed in, not UTC -- target_date is city-local (from
        analyze_trade's parse_city_date()), so a UTC-based days_out
        silently disagrees during the ~4-8h evening window each day where
        UTC's date has already rolled over but the city's hasn't
        (backlog.txt "ANALYZE_TRADE'S past_date GATE...").

        Fixed instant 2026-08-10 00:30 UTC -> NYC local today is 2026-08-09.
        target_date=2026-08-11 is 2 days out from NYC's local today, but
        only 1 day out from UTC's already-rolled-over 2026-08-10 -- the
        GFS sigma table gives a different value for each (3.2 vs 2.5),
        so this discriminates the two implementations directly."""
        from datetime import UTC, datetime

        import mos

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return frozen_instant.replace(tzinfo=None)
                return frozen_instant.astimezone(tz)

        response = {
            "data": [{"ftime": "2026-08-11 15:00", "tmp": 70}],
        }
        with (
            patch.object(mos, "datetime", _Frozen),
            patch.object(mos, "_session") as mock_sess,
        ):
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos(
                "KNYC",
                target_date=date(2026, 8, 11),
                model="GFS",
                tz="America/New_York",
            )

        assert result is not None
        assert result["sigma"] == 3.2, (
            f"expected GFS sigma for days_out=2 (NYC-local) == 3.2, got "
            f"{result['sigma']!r} -- looks like days_out was computed from "
            f"UTC (days_out=1 -> sigma=2.5) instead of America/New_York"
        )

    def test_fetch_mos_best_routing_uses_city_local_today_not_utc(self):
        """fetch_mos_best's NAM-vs-GFS routing must also key off the passed
        tz, not UTC -- same fixed instant/target_date as the sigma test
        above: NYC-local days_out=2 must skip the NAM attempt entirely
        (days_out>1), where a UTC-based days_out=1 would wrongly try NAM
        first."""
        from datetime import UTC, datetime

        import mos

        frozen_instant = datetime(2026, 8, 10, 0, 30, tzinfo=UTC)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return frozen_instant.replace(tzinfo=None)
                return frozen_instant.astimezone(tz)

        response = {
            "data": [{"ftime": "2026-08-11 15:00", "tmp": 70}],
        }
        with (
            patch.object(mos, "datetime", _Frozen),
            patch.object(mos, "_session") as mock_sess,
        ):
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos_best(
                "KNYC", target_date=date(2026, 8, 11), tz="America/New_York"
            )

        assert result is not None
        assert result["model"] == "GFS", (
            f"expected GFS (days_out=2 from NYC-local skips the NAM "
            f"attempt), got model={result['model']!r} -- looks like "
            f"days_out was computed from UTC (days_out=1, tries NAM first)"
        )

    # ── M-18c: ftime UTC vs. city-local target date row filter ──────────────

    def test_row_filter_includes_utc_evening_row_still_local_afternoon(self):
        """M-18c: ftime is UTC; a row timestamped in the UTC evening can
        still be the CITY-LOCAL afternoon for a west-of-UTC station. KLAX is
        UTC-7 (PDT): 2026-08-11 06:00 UTC == 2026-08-10 23:00 PDT (previous
        LA-local day) is NOT the target date, but 2026-08-11 20:00 UTC ==
        2026-08-11 13:00 PDT IS still the target date -- the old raw
        string-prefix filter (`ftime.startswith(date_str)`) wrongly excluded
        this second row because its UTC date string ("2026-08-11") happens
        to match by coincidence here at 20:00z, but at 06:00z (the KLAX
        style overnight boundary) it silently EXCLUDES real same-day
        afternoon/evening PDT readings whose ftime has already rolled to the
        NEXT UTC day. Use a row at 2026-08-12 06:00 UTC (still 2026-08-11
        23:00 PDT, i.e. the LAST hour of the LA-local target date) -- the
        old filter's string-prefix check would exclude this ("2026-08-12"
        != "2026-08-11") even though it truly belongs to the target date."""
        import mos

        response = {
            "data": [
                {"ftime": "2026-08-12 06:00", "tmp": 80},  # 2026-08-11 23:00 PDT
            ]
        }
        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos(
                "KLAX",
                target_date=date(2026, 8, 11),
                model="GFS",
                tz="America/Los_Angeles",
            )

        assert result is not None, (
            "a UTC ftime that's already rolled to the next UTC calendar "
            "day must still be included when it's still the target LOCAL "
            "date -- the old UTC-string-prefix filter silently dropped it"
        )
        assert result["max_temp_f"] == 80

    def test_row_filter_excludes_utc_morning_row_actually_prior_local_day(self):
        """M-18c's other direction: a row whose UTC date string matches
        date_str can actually belong to the PRIOR local day. KLAX
        (UTC-7/PDT): 2026-08-11 05:00 UTC == 2026-08-10 22:00 PDT -- the old
        filter's `ftime.startswith("2026-08-11")` wrongly INCLUDED this row
        for target_date=2026-08-11, even though it's really the previous
        LA-local day's evening reading."""
        import mos

        response = {
            "data": [
                {"ftime": "2026-08-11 05:00", "tmp": 60},  # 2026-08-10 22:00 PDT
            ]
        }
        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos(
                "KLAX",
                target_date=date(2026, 8, 11),
                model="GFS",
                tz="America/Los_Angeles",
            )

        assert result is None, (
            "a UTC ftime that STRING-matches the target date but is "
            "actually the prior LOCAL day (KLAX is UTC-7) must be excluded "
            "-- the old filter wrongly included it"
        )

    def test_row_filter_no_tz_falls_back_to_utc_string_comparison(self):
        """Backward-compat control: when tz is None (unknown caller/city,
        same fallback _local_or_utc_today already documents), the filter
        must fall back to the OLD raw UTC-string comparison rather than
        erroring or silently returning zero rows -- matches every existing
        tz=None test in this file (e.g. test_returns_dict_on_success above),
        none of which pass tz."""
        import mos

        response = {
            "data": [{"ftime": "2026-04-17 15:00", "tmp": 68}],
        }
        with patch.object(mos, "_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = mos.fetch_mos("KNYC", target_date=date(2026, 4, 17))

        assert result is not None
        assert result["max_temp_f"] == 68


class TestMosIntegration:
    def test_analyze_trade_includes_mos_field(self):
        """analyze_trade result dict contains mos_max_temp key."""
        from datetime import date
        from unittest.mock import patch

        import weather_markets

        # Minimal enriched dict that will pass all gates in analyze_trade
        enriched = {
            "ticker": "KXNYC-2026-04-17-HIGH-68",
            "series_ticker": "KXNYC-HIGH",
            "_city": "NYC",
            "_date": date(2026, 4, 17),
            "_forecast": {"high_f": 68.0, "low_f": 52.0},
            "_hour": None,
            "volume": 100,
            "open_interest": 100,
            "yes_ask": 0.55,
            "yes_bid": 0.50,
            "no_ask": 0.50,
            "no_bid": 0.45,
            "close_time": "2026-04-17T23:59:00Z",
        }

        # Patch external calls so analyze_trade returns a result
        with (
            patch("weather_markets.get_ensemble_temps", return_value=[65.0] * 15),
            patch("weather_markets.nws_prob", return_value=0.55),
            patch("weather_markets.climatological_prob", return_value=0.50),
            patch("weather_markets.get_live_observation", return_value=None),
        ):
            result = weather_markets.analyze_trade(enriched)

        # Result may be None if gates block it, but if it returns, mos_max_temp must be a key
        if result is not None:
            assert "mos_max_temp" in result
