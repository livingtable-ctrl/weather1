"""Tests for METAR same-day lock-in strategy."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Sample METAR API response
METAR_RESPONSE = [
    {
        "icaoId": "KNYC",
        "obsTime": "2026-04-17T17:00:00Z",
        "temp": 22.2,  # °C (72°F)
        "dewp": 10.0,
        "tmpf": 72.0,  # °F if provided, else computed
    }
]

METAR_RESPONSE_COLD = [
    {
        "icaoId": "KNYC",
        "obsTime": "2026-04-17T17:00:00Z",
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

        response = [{"icaoId": "KNYC", "obsTime": "2026-04-17T17:00:00Z", "temp": 20.0}]
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

    def test_returns_none_on_empty_response(self):
        import metar

        with patch.object(metar, "_session") as mock:
            mock.get.return_value.json.return_value = []
            mock.get.return_value.raise_for_status.return_value = None
            result = metar.fetch_metar("KNYC")

        assert result is None


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
