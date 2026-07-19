"""Tests for climate_indices.py's per-city AO/NAO/ENSO sensitivity tables.

AO_SENS/NAO_SENS/ENSO_SENS were moved to module level 2026-07-19 (previously
3 dict literals rebuilt from scratch inside temperature_adjustment() on every
call) so per-city coverage is inspectable for the PER-CITY KNOWLEDGE
SCATTERED completeness manifest (backlog.txt) without needing to execute or
parse the function body. This file locks in temperature_adjustment()'s real
computed values -- no prior test in the suite did this; every other test
file that touches temperature_adjustment() mocks it out entirely.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

import climate_indices as ci


class TestSeasonBucket:
    def test_december_january_february_are_winter(self):
        assert ci._season_bucket(12) == "winter"
        assert ci._season_bucket(1) == "winter"
        assert ci._season_bucket(2) == "winter"

    def test_march_april_may_are_spring(self):
        assert ci._season_bucket(3) == "spring"
        assert ci._season_bucket(4) == "spring"
        assert ci._season_bucket(5) == "spring"

    def test_june_through_november_are_other(self):
        for month in range(6, 12):
            assert ci._season_bucket(month) == "other"


class TestSensitivityTablesCoverage:
    """Which cities have real (non-default) sensitivity entries -- the exact
    fact the completeness manifest reports on."""

    _COVERED_CITIES = {
        "NYC",
        "Boston",
        "Chicago",
        "Miami",
        "LA",
        "Dallas",
        "Phoenix",
        "Seattle",
        "Denver",
        "Atlanta",
    }

    def test_ao_sens_covers_exactly_ten_cities(self):
        assert set(ci.AO_SENS.keys()) == self._COVERED_CITIES

    def test_nao_sens_covers_exactly_ten_cities(self):
        assert set(ci.NAO_SENS.keys()) == self._COVERED_CITIES

    def test_enso_sens_covers_exactly_ten_cities(self):
        assert set(ci.ENSO_SENS.keys()) == self._COVERED_CITIES

    def test_all_three_tables_cover_the_same_city_set(self):
        """A city present in one table but not another would silently mix
        a real sensitivity with a generic default -- verify they're
        perfectly aligned, not just each individually 10-wide."""
        assert set(ci.AO_SENS) == set(ci.NAO_SENS) == set(ci.ENSO_SENS)

    def test_ao_and_nao_entries_have_all_three_seasons(self):
        for city, seasons in {**ci.AO_SENS, **ci.NAO_SENS}.items():
            assert set(seasons) == {"winter", "spring", "other"}, city

    def test_enso_entries_have_only_two_seasons(self):
        """ENSO's original ternary never had a spring-specific branch --
        must stay 2 buckets, not silently gain a 3rd via copy-paste."""
        for city, seasons in ci.ENSO_SENS.items():
            assert set(seasons) == {"winter", "other"}, city


class TestTemperatureAdjustmentComputedValues:
    """Hand-computed expected values from AO_SENS/NAO_SENS/ENSO_SENS
    directly, with indices pinned to isolate the sensitivity lookup from
    get_indices()'s own logic."""

    def _adjustment(self, city, month, ao=1.0, nao=1.0, enso=1.0):
        with patch.object(
            ci, "get_indices", return_value={"ao": ao, "nao": nao, "enso": enso}
        ):
            return ci.temperature_adjustment(city, date(2026, month, 15))

    def test_covered_city_winter(self):
        # NYC winter: ao=2.0, nao=1.2, enso=1.0 (winter bucket) -> 4.2
        assert self._adjustment("NYC", month=1) == pytest.approx(4.2)

    def test_covered_city_spring(self):
        # NYC spring: ao=1.2, nao=0.7, enso=0.3 (ENSO has no spring bucket,
        # collapses to "other") -> 2.2
        assert self._adjustment("NYC", month=4) == pytest.approx(2.2)

    def test_covered_city_other_season(self):
        # NYC July ("other"): ao=0.4, nao=0.2, enso=0.3 -> 0.9
        assert self._adjustment("NYC", month=7) == pytest.approx(0.9)

    def test_uncovered_city_uses_flat_default_regardless_of_season(self):
        """Austin has no entry in any of the 3 tables -- must fall through
        to DEFAULT_AO_SENS/DEFAULT_NAO_SENS/DEFAULT_ENSO_SENS (0.5+0.4+0.4
        = 1.3) the SAME way in every season, unlike a covered city."""
        winter = self._adjustment("Austin", month=1)
        spring = self._adjustment("Austin", month=4)
        other = self._adjustment("Austin", month=7)
        assert winter == pytest.approx(1.3)
        assert spring == pytest.approx(1.3)
        assert other == pytest.approx(1.3)

    def test_zero_indices_give_zero_adjustment(self):
        assert self._adjustment("NYC", month=1, ao=0.0, nao=0.0, enso=0.0) == 0.0

    def test_total_adjustment_capped_at_positive_six(self):
        # Denver winter has the highest AO sensitivity (1.8); large enough
        # positive indices must still clamp to +6.0, not overshoot.
        result = self._adjustment("Denver", month=1, ao=10.0, nao=10.0, enso=10.0)
        assert result == pytest.approx(6.0)

    def test_total_adjustment_capped_at_negative_six(self):
        result = self._adjustment("Denver", month=1, ao=-10.0, nao=-10.0, enso=-10.0)
        assert result == pytest.approx(-6.0)

    def test_mutation_flipping_a_sensitivity_value_changes_the_result(self):
        """Direct proof the module-level tables are actually what
        temperature_adjustment() reads (not stale/disconnected data) --
        mutating AO_SENS live and confirming the computed value shifts."""
        before = self._adjustment("NYC", month=1, ao=1.0, nao=0.0, enso=0.0)
        with patch.dict(
            ci.AO_SENS, {"NYC": {"winter": 99.0, "spring": 1.2, "other": 0.4}}
        ):
            after = self._adjustment("NYC", month=1, ao=1.0, nao=0.0, enso=0.0)
        assert before == pytest.approx(2.0)
        assert after == pytest.approx(6.0)  # 99.0 * 1.0 clamped to +6.0
        assert before != after
