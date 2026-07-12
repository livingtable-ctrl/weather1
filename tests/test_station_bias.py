"""Tests for the per-city static station-bias tables.

Rewritten 2026-07-12: previously exercised apply_station_bias(), a thin
wrapper (`forecast_temp - table.get(city, 0.0)`) that turned out to have
zero production callers -- the real, wired-in bias correction is
_get_combined_station_bias() (blends this same static table with a dynamic
METAR-derived correction as settled-observation samples accumulate), so
apply_station_bias() was deleted as superseded rather than wired up. These
tests are rewritten to check the underlying _STATION_BIAS_HIGH/_LOW tables
directly -- the city-equality assertions here are real data-consistency
checks worth keeping regardless of which function reads the tables.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStationBiasTables:
    def test_nyc_bias_negative(self):
        """NYC has a -1°F bias correction (subtract from model)."""
        from weather_markets import _STATION_BIAS_HIGH

        assert _STATION_BIAS_HIGH["NYC"] == 1.0

    def test_miami_bias_negative(self):
        """Miami has a -3°F bias correction."""
        from weather_markets import _STATION_BIAS_HIGH

        assert _STATION_BIAS_HIGH["Miami"] == 3.0

    def test_denver_bias_negative(self):
        """Denver has a -2°F bias correction."""
        from weather_markets import _STATION_BIAS_HIGH

        assert _STATION_BIAS_HIGH["Denver"] == 2.0

    def test_unknown_city_no_change(self):
        """Unknown cities have no bias table entry -- callers fall back to 0.0."""
        from weather_markets import _STATION_BIAS_HIGH

        assert "XYZ" not in _STATION_BIAS_HIGH

    def test_los_angeles_no_bias(self):
        """LA has no known systematic bias."""
        from weather_markets import _STATION_BIAS_HIGH

        assert _STATION_BIAS_HIGH.get("LA", 0.0) == 0.0

    def test_bias_table_exists(self):
        """_STATION_BIAS (legacy alias for _STATION_BIAS_HIGH) is importable."""
        from weather_markets import _STATION_BIAS

        assert isinstance(_STATION_BIAS, dict)
        assert "NYC" in _STATION_BIAS

    def test_las_vegas_bias_matches_phoenix(self):
        """Las Vegas has no settled-observation history yet — uses Phoenix's
        desert-climate bias as an interim value (same GFS/ICON warm-bias artifact)."""
        from weather_markets import _STATION_BIAS_HIGH, _STATION_BIAS_LOW

        assert _STATION_BIAS_HIGH["LasVegas"] == _STATION_BIAS_HIGH["Phoenix"]
        assert _STATION_BIAS_LOW["LasVegas"] == _STATION_BIAS_LOW["Phoenix"]

    def test_new_orleans_bias_matches_houston(self):
        """New Orleans has no settled-observation history yet — uses Houston's
        Gulf humid-subtropical bias as an interim value."""
        from weather_markets import _STATION_BIAS_HIGH, _STATION_BIAS_LOW

        assert _STATION_BIAS_HIGH["NewOrleans"] == _STATION_BIAS_HIGH["Houston"]
        assert _STATION_BIAS_LOW["NewOrleans"] == _STATION_BIAS_LOW["Houston"]
