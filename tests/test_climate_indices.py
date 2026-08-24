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
    """Which cities have a table entry (key membership) -- the exact fact
    the completeness manifest reports on. NOT the same as "has a real,
    non-default coefficient" -- as of 2026-07-25 most covered cities are
    numerically identical to an uncovered one in most/all seasons (see
    TestRegressionFittedGapCities / TestRegressionFittedOriginalTen below
    for which specific cells are actually fitted vs. default)."""

    # Original 10 (moved to module level + hardcoded 2026-07-19, re-derived
    # via real regression 2026-07-25) + the 10 filled 2026-07-25 via real
    # AO/NAO/ENSO regression against each city's 30yr temp record
    # (backlog.txt "PER-CITY KNOWLEDGE SCATTERED" follow-up).
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
        "Austin",
        "Washington",
        "Philadelphia",
        "OklahomaCity",
        "SanFrancisco",
        "Minneapolis",
        "Houston",
        "SanAntonio",
        "LasVegas",
        "NewOrleans",
    }

    def test_ao_sens_covers_exactly_twenty_cities(self):
        assert set(ci.AO_SENS.keys()) == self._COVERED_CITIES

    def test_nao_sens_covers_exactly_twenty_cities(self):
        assert set(ci.NAO_SENS.keys()) == self._COVERED_CITIES

    def test_enso_sens_covers_exactly_twenty_cities(self):
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
        # Miami winter (re-derived 2026-07-25): AO/NAO/ENSO all default for
        # this season (Miami's only real fitted cells are AO/NAO-spring) ->
        # 0.5 + 0.4 + 0.4 = 1.3
        assert self._adjustment("Miami", month=1) == pytest.approx(1.3)

    def test_covered_city_spring(self):
        # Miami spring (re-derived 2026-07-25): ao=0.6 (fitted) + nao=0.6
        # (fitted) + enso=0.4 (default, ENSO has no spring bucket, collapses
        # to "other" which is also default for Miami) -> 1.6
        assert self._adjustment("Miami", month=4) == pytest.approx(1.6)

    def test_covered_city_spring_isolates_ao_and_nao_separately(self):
        """Miami spring is the only city/season with TWO fitted cells
        (AO=0.6, NAO=0.6) -- the combined test above can't tell them apart
        from a transposed value or an AO<->NAO swap since both happen to be
        equal. Isolate each coefficient with single-index inputs."""
        # ao-only: 1.0 * 0.6 (fitted AO-spring) + 0 + 0 = 0.6
        assert self._adjustment(
            "Miami", month=4, ao=1.0, nao=0.0, enso=0.0
        ) == pytest.approx(0.6)
        # nao-only: 0 + 1.0 * 0.6 (fitted NAO-spring) + 0 = 0.6
        assert self._adjustment(
            "Miami", month=4, ao=0.0, nao=1.0, enso=0.0
        ) == pytest.approx(0.6)

    def test_covered_city_other_season(self):
        # Miami July ("other"): all default (fitted cells are winter/spring
        # only) -> 0.5 + 0.4 + 0.4 = 1.3
        assert self._adjustment("Miami", month=7) == pytest.approx(1.3)

    def test_uncovered_city_uses_flat_default_regardless_of_season(self):
        """A city with no entry in any of the 3 tables (all 20 real traded
        cities are covered as of 2026-07-25 -- use a synthetic name so this
        keeps testing the fallback mechanism itself, not a real city's
        temporary gap) must fall through to DEFAULT_AO_SENS/
        DEFAULT_NAO_SENS/DEFAULT_ENSO_SENS (0.5+0.4+0.4 = 1.3) the SAME way
        in every season, unlike a covered city."""
        winter = self._adjustment("Nonexistent", month=1)
        spring = self._adjustment("Nonexistent", month=4)
        other = self._adjustment("Nonexistent", month=7)
        assert winter == pytest.approx(1.3)
        assert spring == pytest.approx(1.3)
        assert other == pytest.approx(1.3)

    def test_zero_indices_give_zero_adjustment(self):
        assert self._adjustment("NYC", month=1, ao=0.0, nao=0.0, enso=0.0) == 0.0

    def test_total_adjustment_capped_at_positive_six(self):
        # Large enough positive indices must clamp to +6.0 regardless of
        # per-city sensitivity magnitude, not overshoot.
        result = self._adjustment("Denver", month=1, ao=10.0, nao=10.0, enso=10.0)
        assert result == pytest.approx(6.0)

    def test_total_adjustment_capped_at_negative_six(self):
        result = self._adjustment("Denver", month=1, ao=-10.0, nao=-10.0, enso=-10.0)
        assert result == pytest.approx(-6.0)

    def test_mutation_flipping_a_sensitivity_value_changes_the_result(self):
        """Direct proof the module-level tables are actually what
        temperature_adjustment() reads (not stale/disconnected data) --
        mutating AO_SENS live and confirming the computed value shifts.
        Uses Miami-spring (a real fitted, non-default cell) rather than a
        now-fully-default city -- with a default-only city, `before` would
        be identical whether or not the city was in AO_SENS at all, which
        wouldn't actually prove the table is being read."""
        before = self._adjustment("Miami", month=4, ao=1.0, nao=0.0, enso=0.0)
        with patch.dict(
            ci.AO_SENS, {"Miami": {"winter": 0.5, "spring": 99.0, "other": 0.5}}
        ):
            after = self._adjustment("Miami", month=4, ao=1.0, nao=0.0, enso=0.0)
        assert before == pytest.approx(0.6)  # Miami AO-spring's real fitted value
        assert after == pytest.approx(6.0)  # 99.0 * 1.0 clamped to +6.0
        assert before != after


class TestRegressionFittedGapCities:
    """Hand-computed regression-locking tests for the 10 cities researched
    2026-07-25 (backlog.txt "PER-CITY KNOWLEDGE SCATTERED" follow-up) --
    pins the actual fitted-vs-default values so a future accidental edit to
    AO_SENS/NAO_SENS/ENSO_SENS is caught the same way
    TestTemperatureAdjustmentComputedValues pins the (re-derived, see
    TestRegressionFittedOriginalTen below) original 10.

    Revised same day after an independent review found the first pass fit
    AO/NAO/ENSO at lag 0, but get_indices() only ever returns an
    already-published (lagged) value in production -- refitting at the lag
    actually used, plus a Benjamini-Hochberg FDR correction across the 80
    cells tested, collapsed almost everything to the flat default. Only 4
    of the 10 researched cities ended up with any real (non-default) cell
    at all, all in ENSO's "other" season."""

    def _adjustment(self, city, month, ao=1.0, nao=1.0, enso=1.0):
        with patch.object(
            ci, "get_indices", return_value={"ao": ao, "nao": nao, "enso": enso}
        ):
            return ci.temperature_adjustment(city, date(2026, month, 15))

    def test_six_of_ten_researched_cities_are_entirely_default(self):
        """Washington/Philadelphia/Minneapolis/Houston/LasVegas/NewOrleans:
        nothing survived lag-1 + BH-FDR in any of the 8 cells -- confirm
        each behaves numerically identically to an uncovered city in every
        season (0.5+0.4+0.4=1.3 winter/spring, same for "other")."""
        for city in (
            "Washington",
            "Philadelphia",
            "Minneapolis",
            "Houston",
            "LasVegas",
            "NewOrleans",
        ):
            assert self._adjustment(city, month=1) == pytest.approx(1.3), city
            assert self._adjustment(city, month=4) == pytest.approx(1.3), city
            assert self._adjustment(city, month=7) == pytest.approx(1.3), city

    def test_austin_winter_is_entirely_default_despite_being_a_covered_city(self):
        """Austin has a real fitted cell (ENSO-other), but winter is 100%
        default -- a covered city is not the same guarantee as "every
        season has a real fitted signal"."""
        assert self._adjustment("Austin", month=1) == pytest.approx(1.3)

    def test_gulf_coast_negative_enso_other_reduces_total_adjustment(self):
        """The 3 cities with a fitted negative ENSO "other" coefficient --
        confirm it actually SUBTRACTS from the total rather than being
        silently clamped to the table's usual positive convention. Also
        confirms the spring bucket (which collapses to ENSO's "other" key)
        picks up the same fitted value, not the winter one."""
        # Austin other: ao=0.5 (default) + nao=0.4 (default) + enso=-0.7 (fitted, negative) = 0.2
        assert self._adjustment("Austin", month=7) == pytest.approx(0.2)
        assert self._adjustment("Austin", month=4) == pytest.approx(0.2)  # spring
        # OklahomaCity other: ao=0.5 (default) + nao=0.4 (default) + enso=-0.7 (fitted, negative) = 0.2
        assert self._adjustment("OklahomaCity", month=7) == pytest.approx(0.2)
        # SanAntonio other: ao=0.5 (default) + nao=0.4 (default) + enso=-0.6 (fitted, negative) = 0.3
        assert self._adjustment("SanAntonio", month=7) == pytest.approx(0.3)

    def test_san_francisco_ao_nao_and_enso_winter_default_but_enso_other_fitted(self):
        """West Coast city: no AO/NAO cell survives BH-FDR at any season
        (AO-other is raw-significant, p=0.021, but doesn't clear the
        multiple-comparisons bar -- same reason Seattle's hand-set AO
        doesn't hold up under this regression, both are Atlantic-sector
        patterns), and ENSO-winter didn't survive BH-FDR either -- but
        ENSO-"other" is real and POSITIVE (a real West Coast ENSO
        teleconnection, opposite sign from the Gulf Coast cities' negative
        "other" coefficient)."""
        # winter: ao=0.5 (default) + nao=0.4 (default) + enso=0.4 (default) = 1.3 -- same as uncovered
        assert self._adjustment("SanFrancisco", month=1) == pytest.approx(1.3)
        # other: ao=0.5 (default) + nao=0.4 (default) + enso=0.6 (fitted, positive) = 1.5
        assert self._adjustment("SanFrancisco", month=7) == pytest.approx(1.5)


class TestRegressionFittedOriginalTen:
    """Hand-computed regression-locking tests for the ORIGINAL 10 cities,
    re-derived 2026-07-25 (backlog.txt "EXISTING 10 climate_indices CITIES'
    HAND-SET AO/NAO/ENSO VALUES DISAGREE WITH THE REAL 31-YEAR REGRESSION")
    using the identical lag-1 + BH-FDR methodology as
    TestRegressionFittedGapCities above, applied at the user's explicit
    confirmation to replace the previous hand-set values entirely.

    Only 4 of 80 cells survive: Miami AO-spring, Miami NAO-spring, Seattle
    ENSO-other, Denver ENSO-other (Miami's cells are pinned in
    TestTemperatureAdjustmentComputedValues above, reused rather than
    duplicated here). Every other cell across these 10 cities reverts to
    the flat default."""

    def _adjustment(self, city, month, ao=1.0, nao=1.0, enso=1.0):
        with patch.object(
            ci, "get_indices", return_value={"ao": ao, "nao": nao, "enso": enso}
        ):
            return ci.temperature_adjustment(city, date(2026, month, 15))

    def test_seven_of_ten_original_cities_are_entirely_default(self):
        """NYC/Boston/Chicago/LA/Dallas/Phoenix/Atlanta: nothing survived
        lag-1 + BH-FDR in any of their 8 cells -- each now behaves
        numerically identically to an uncovered city in every season."""
        for city in (
            "NYC",
            "Boston",
            "Chicago",
            "LA",
            "Dallas",
            "Phoenix",
            "Atlanta",
        ):
            assert self._adjustment(city, month=1) == pytest.approx(1.3), city
            assert self._adjustment(city, month=4) == pytest.approx(1.3), city
            assert self._adjustment(city, month=7) == pytest.approx(1.3), city

    def test_seattle_positive_enso_other_fitted_spring_and_other_share_it(self):
        """Seattle's only real cell (ENSO-other, fitted positive) -- winter
        stays default, and the spring bucket (which collapses to ENSO's
        "other" key) picks up the same fitted value as summer/fall."""
        # winter: ao=0.5 (default) + nao=0.4 (default) + enso=0.4 (default) = 1.3
        assert self._adjustment("Seattle", month=1) == pytest.approx(1.3)
        # spring/other: ao=0.5 (default) + nao=0.4 (default) + enso=0.7 (fitted) = 1.6
        assert self._adjustment("Seattle", month=4) == pytest.approx(1.6)
        assert self._adjustment("Seattle", month=7) == pytest.approx(1.6)

    def test_denver_negative_enso_other_reverses_the_hand_set_sign(self):
        """Denver's fitted ENSO-other (-1.0) is the OPPOSITE sign from its
        removed hand-set value (+0.3) -- confirm it actually subtracts,
        turning an otherwise-positive total negative, not just shrinking
        it. Winter stays default (positive) since only "other" is fitted."""
        # winter: ao=0.5 (default) + nao=0.4 (default) + enso=0.4 (default) = 1.3
        assert self._adjustment("Denver", month=1) == pytest.approx(1.3)
        # spring/other: ao=0.5 (default) + nao=0.4 (default) + enso=-1.0 (fitted, negative) = -0.1
        assert self._adjustment("Denver", month=4) == pytest.approx(-0.1)
        assert self._adjustment("Denver", month=7) == pytest.approx(-0.1)


class TestGetIndicesPartialFailureCaching:
    """L-6: the H-17 zero-result cache guard only fired when ALL THREE
    fetches returned empty -- a PARTIAL outage (e.g. AO fails, NAO/ENSO
    succeed) still cached the combined result (AO's spurious 0.0 included)
    for the full 24h TTL, since not every index was 0.0. Fixed to skip the
    cache write whenever ANY raw fetch dict came back empty (the only way
    _fetch_monthly_index/_fetch_enso return {}), not just when the combined
    RESULT happens to be all-zero."""

    def _mock_fetches(self, monkeypatch, ao, nao, enso):
        # "daily_ao_index" (AO) vs "pna/norm.nao" (NAO) -- distinguish on
        # the AO-specific path segment, not a bare "ao" substring, since
        # "norm.nao..." itself contains "ao" and would otherwise collide.
        def _fake_fetch_monthly_index(url):
            return ao if "ao_index" in url else nao

        monkeypatch.setattr(ci, "_fetch_monthly_index", _fake_fetch_monthly_index)
        monkeypatch.setattr(ci, "_fetch_enso", lambda: enso)

    def test_all_three_succeed_caches(self, monkeypatch):
        self._mock_fetches(
            monkeypatch,
            ao={(2026, 1): 0.5},
            nao={(2026, 1): 0.3},
            enso={(2026, 1): -0.2},
        )
        result = ci.get_indices(target_month=1, target_year=2026)
        assert result == {"ao": 0.5, "nao": 0.3, "enso": -0.2, "year": 2026, "month": 1}
        assert ci._indices_cache.get((2026, 1)) == result

    def test_one_of_three_fails_does_not_cache(self, monkeypatch):
        """The core L-6 regression: AO's raw fetch failed ({}), NAO/ENSO
        succeeded with real non-zero values -- the OLD guard only checked
        whether the combined result was all-zero, which it isn't here (nao/
        enso are nonzero), so it cached anyway, freezing AO's failure (as a
        spurious 0.0) into the shared (year, month) slot for 24h even after
        AO recovered. Mutation-tested below by reverting to the old
        all-zero-only check."""
        self._mock_fetches(
            monkeypatch,
            ao={},  # simulates a failed AO fetch (_fetch_monthly_index's own except-clause return)
            nao={(2026, 1): 0.3},
            enso={(2026, 1): -0.2},
        )
        result = ci.get_indices(target_month=1, target_year=2026)
        assert result == {"ao": 0.0, "nao": 0.3, "enso": -0.2, "year": 2026, "month": 1}
        assert ci._indices_cache.get((2026, 1)) is None, (
            "a partial fetch failure (AO empty, NAO/ENSO real) must NOT be "
            "cached -- the next call must retry AO instead of being frozen "
            "at 0.0 for the full 24h TTL"
        )

    def test_all_three_fail_does_not_cache_control(self, monkeypatch):
        """Positive control matching the original H-17 all-zero case."""
        self._mock_fetches(monkeypatch, ao={}, nao={}, enso={})
        result = ci.get_indices(target_month=1, target_year=2026)
        assert result == {"ao": 0.0, "nao": 0.0, "enso": 0.0, "year": 2026, "month": 1}
        assert ci._indices_cache.get((2026, 1)) is None
