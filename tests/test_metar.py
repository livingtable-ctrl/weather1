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
