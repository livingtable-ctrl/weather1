---
type: community
cohesion: 0.05
members: 52
---

# Community 31

**Cohesion:** 0.05 - loosely connected
**Members:** 52 nodes

## Members
- [[dot-_adjustment()_1]] - code - tests/test_climate_indices.py
- [[dot-_adjustment()_2]] - code - tests/test_climate_indices.py
- [[dot-_adjustment()]] - code - tests/test_climate_indices.py
- [[dot-test_all_three_tables_cover_the_same_city_set()]] - code - tests/test_climate_indices.py
- [[dot-test_ao_and_nao_entries_have_all_three_seasons()]] - code - tests/test_climate_indices.py
- [[dot-test_ao_sens_covers_exactly_twenty_cities()]] - code - tests/test_climate_indices.py
- [[dot-test_austin_winter_is_entirely_default_despite_being_a_covered_city()]] - code - tests/test_climate_indices.py
- [[dot-test_covered_city_other_season()]] - code - tests/test_climate_indices.py
- [[dot-test_covered_city_spring()]] - code - tests/test_climate_indices.py
- [[dot-test_covered_city_spring_isolates_ao_and_nao_separately()]] - code - tests/test_climate_indices.py
- [[dot-test_covered_city_winter()]] - code - tests/test_climate_indices.py
- [[dot-test_december_january_february_are_winter()]] - code - tests/test_climate_indices.py
- [[dot-test_denver_negative_enso_other_reverses_the_hand_set_sign()]] - code - tests/test_climate_indices.py
- [[dot-test_enso_entries_have_only_two_seasons()]] - code - tests/test_climate_indices.py
- [[dot-test_enso_sens_covers_exactly_twenty_cities()]] - code - tests/test_climate_indices.py
- [[dot-test_gulf_coast_negative_enso_other_reduces_total_adjustment()]] - code - tests/test_climate_indices.py
- [[dot-test_june_through_november_are_other()]] - code - tests/test_climate_indices.py
- [[dot-test_march_april_may_are_spring()]] - code - tests/test_climate_indices.py
- [[dot-test_mutation_flipping_a_sensitivity_value_changes_the_result()]] - code - tests/test_climate_indices.py
- [[dot-test_nao_sens_covers_exactly_twenty_cities()]] - code - tests/test_climate_indices.py
- [[dot-test_san_francisco_ao_nao_and_enso_winter_default_but_enso_other_fitted()]] - code - tests/test_climate_indices.py
- [[dot-test_seattle_positive_enso_other_fitted_spring_and_other_share_it()]] - code - tests/test_climate_indices.py
- [[dot-test_seven_of_ten_original_cities_are_entirely_default()]] - code - tests/test_climate_indices.py
- [[dot-test_six_of_ten_researched_cities_are_entirely_default()]] - code - tests/test_climate_indices.py
- [[dot-test_total_adjustment_capped_at_negative_six()]] - code - tests/test_climate_indices.py
- [[dot-test_total_adjustment_capped_at_positive_six()]] - code - tests/test_climate_indices.py
- [[dot-test_uncovered_city_uses_flat_default_regardless_of_season()]] - code - tests/test_climate_indices.py
- [[dot-test_zero_indices_give_zero_adjustment()]] - code - tests/test_climate_indices.py
- [[A city present in one table but not another would silently mix a real…]] - rationale - tests/test_climate_indices.py
- [[A city with no entry in any of the 3 tables (all 20 real traded cities are…]] - rationale - tests/test_climate_indices.py
- [[Austin has a real fitted cell (ENSO-other), but winter is 100% default -- a…]] - rationale - tests/test_climate_indices.py
- [[Denver's fitted ENSO-other (-1.0) is the OPPOSITE sign from its removed hand-…]] - rationale - tests/test_climate_indices.py
- [[Direct proof the module-level tables are actually what temperature_adjustment()…]] - rationale - tests/test_climate_indices.py
- [[ENSO's original ternary never had a spring-specific branch -- must stay 2…]] - rationale - tests/test_climate_indices.py
- [[Hand-computed expected values from AO_SENSNAO_SENSENSO_SENS directly, with…]] - rationale - tests/test_climate_indices.py
- [[Hand-computed regression-locking tests for the 10 cities researched 2026-07-25…]] - rationale - tests/test_climate_indices.py
- [[Hand-computed regression-locking tests for the ORIGINAL 10 cities, re-derived…]] - rationale - tests/test_climate_indices.py
- [[Miami spring is the only cityseason with TWO fitted cells (AO=0.6, NAO=0.6) --…]] - rationale - tests/test_climate_indices.py
- [[NYCBostonChicagoLADallasPhoenixAtlanta nothing survived lag-1 + BH-FDR…]] - rationale - tests/test_climate_indices.py
- [[Seattle's only real cell (ENSO-other, fitted positive) -- winter stays default,…]] - rationale - tests/test_climate_indices.py
- [[TestRegressionFittedGapCities]] - code - tests/test_climate_indices.py
- [[TestRegressionFittedOriginalTen]] - code - tests/test_climate_indices.py
- [[TestSeasonBucket]] - code - tests/test_climate_indices.py
- [[TestSensitivityTablesCoverage]] - code - tests/test_climate_indices.py
- [[TestTemperatureAdjustmentComputedValues]] - code - tests/test_climate_indices.py
- [[Tests for climate_indices.py's per-city AONAOENSO sensitivity tables.…]] - rationale - tests/test_climate_indices.py
- [[The 3 cities with a fitted negative ENSO other coefficient -- confirm it…]] - rationale - tests/test_climate_indices.py
- [[WashingtonPhiladelphiaMinneapolisHoustonLasVegasNewOrleans nothing…]] - rationale - tests/test_climate_indices.py
- [[West Coast city no AONAO cell survives BH-FDR at any season (AO-other is raw-…]] - rationale - tests/test_climate_indices.py
- [[Which cities have a table entry (key membership) -- the exact fact the…]] - rationale - tests/test_climate_indices.py
- [[climate_indices.py_1]] - code - climate_indices.py
- [[test_climate_indices.py]] - code - tests/test_climate_indices.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_31
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 302]]

## Top bridge nodes
- [[test_climate_indices.py]] - degree 9, connects to 2 communities