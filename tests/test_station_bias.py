"""Tests for per-city static bias correction."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestApplyStationBias:
    def test_nyc_bias_negative(self):
        """NYC has a -1°F bias correction (subtract from model)."""
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("NYC", 72.0)
        assert corrected == pytest.approx(71.0, abs=0.01)

    def test_miami_bias_negative(self):
        """Miami has a -3°F bias correction."""
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("Miami", 90.0)
        assert corrected == pytest.approx(87.0, abs=0.01)

    def test_denver_bias_negative(self):
        """Denver has a -2°F bias correction."""
        from weather_markets import apply_station_bias

        corrected = apply_station_bias("Denver", 65.0)
        assert corrected == pytest.approx(63.0, abs=0.01)

    def test_unknown_city_no_change(self):
        """Unknown cities return the temperature unchanged."""
        from weather_markets import apply_station_bias

        assert apply_station_bias("XYZ", 70.0) == pytest.approx(70.0)

    def test_los_angeles_no_bias(self):
        """LA has no known systematic bias."""
        from weather_markets import apply_station_bias

        assert apply_station_bias("LA", 75.0) == pytest.approx(75.0)

    def test_bias_table_exists(self):
        """_STATION_BIAS dict is importable."""
        from weather_markets import _STATION_BIAS

        assert isinstance(_STATION_BIAS, dict)
        assert "NYC" in _STATION_BIAS

    def test_las_vegas_bias_matches_phoenix(self):
        """Las Vegas has no settled-observation history yet — uses Phoenix's
        desert-climate bias as an interim value (same GFS/ICON warm-bias artifact)."""
        from weather_markets import apply_station_bias

        assert apply_station_bias("LasVegas", 100.0) == pytest.approx(
            apply_station_bias("Phoenix", 100.0)
        )
        assert apply_station_bias("LasVegas", 100.0, var="min") == pytest.approx(
            apply_station_bias("Phoenix", 100.0, var="min")
        )

    def test_new_orleans_bias_matches_houston(self):
        """New Orleans has no settled-observation history yet — uses Houston's
        Gulf humid-subtropical bias as an interim value."""
        from weather_markets import apply_station_bias

        assert apply_station_bias("NewOrleans", 90.0) == pytest.approx(
            apply_station_bias("Houston", 90.0)
        )
        assert apply_station_bias("NewOrleans", 90.0, var="min") == pytest.approx(
            apply_station_bias("Houston", 90.0, var="min")
        )
