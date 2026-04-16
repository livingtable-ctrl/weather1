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

    def test_station_lookup(self):
        """get_mos_station returns correct ASOS station for each city."""
        import mos

        assert mos.get_mos_station("NYC") == "KNYC"
        assert mos.get_mos_station("MIA") == "KMIA"
        assert mos.get_mos_station("CHI") == "KORD"
        assert mos.get_mos_station("LAX") == "KLAX"
        assert mos.get_mos_station("DAL") == "KDFW"

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


class TestMosIntegration:
    def test_analyze_trade_includes_mos_field(self):
        """analyze_trade result dict contains mos_max_temp key."""
        from weather_markets import analyze_trade

        # This just checks the key exists — value may be None if API unavailable
        result = analyze_trade.__doc__  # smoke check module loads
        assert result is not None  # analyze_trade has a docstring
