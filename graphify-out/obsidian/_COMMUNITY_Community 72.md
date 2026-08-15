---
type: community
cohesion: 0.12
members: 32
---

# Community 72

**Cohesion:** 0.12 - loosely connected
**Members:** 32 nodes

## Members
- [[dot-test_49_rows_city_omitted()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_50_rows_city_present()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_all_weights_in_range()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_auto_split_80_20()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_brier_gate_constant()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_calibrate_city_weights_deterministic()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_city_accepts_cutoff_date_kwarg()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_city_min_is_50()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_cutoff_excludes_future_rows_from_training()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_n_random_search_is_200()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_seasonal_accepts_cutoff_date_kwarg()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_weights_sum_to_one()_5]] - code - tests/test_phase3_batch_c.py
- [[dot-test_weights_with_explicit_cutoff_sum_to_one()]] - code - tests/test_phase3_batch_c.py
- [[Generate n rows with spread-out dates for stable 8020 splits.]] - rationale - tests/test_phase3_batch_c.py
- [[Grid-search optimal blend weights per city. Returns {city {ensemble,…]] - rationale - calibration.py
- [[P3-1 calibrate_seasonal_weights and calibrate_city_weights accept cutoff_date.]] - rationale - tests/test_phase3_batch_c.py
- [[P3-25 _CITY_MIN must be 50.]] - rationale - tests/test_phase3_batch_c.py
- [[P3-7 _best_weights uses random search; gate returns equal weights when no…]] - rationale - tests/test_phase3_batch_c.py
- [[Phase 3 Batch C Calibration Tests]] - code - tests/test_phase3_batch_c.py
- [[Phase 3 Batch C regression tests P3-1, P3-7, P3-16, P3-17, P3-25.]] - rationale - tests/test_phase3_batch_c.py
- [[Rows after cutoff must not affect training — weights with tight cutoff differ.]] - rationale - tests/test_phase3_batch_c.py
- [[Same data → same weights (random search uses fixed seed=42).]] - rationale - tests/test_phase3_batch_c.py
- [[Seed a predictions+outcomes DB for calibration tests.]] - rationale - tests/test_phase3_batch_c.py
- [[TestCityMinThreshold]] - code - tests/test_phase3_batch_c.py
- [[TestRandomSearchAndGate]] - code - tests/test_phase3_batch_c.py
- [[TestTemporalIsolationSeasonalCity]] - code - tests/test_phase3_batch_c.py
- [[Without cutoff_date, function runs without error on enough rows.]] - rationale - tests/test_phase3_batch_c.py
- [[_make_db()_1]] - code - tests/test_phase3_batch_c.py
- [[_rows()]] - code - tests/test_phase3_batch_c.py
- [[calibrate_city_weights()]] - code - calibration.py
- [[calibration cutoff_date temporal isolation (seasonalcitycondition)]] - code - calibration.py
- [[calibration._brier  _CITY_MIN  _best_weights  calibrate_city_weights]] - code - calibration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_72
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_Community 118]]
- 4 edges to [[_COMMUNITY_Community 406]]
- 2 edges to [[_COMMUNITY_Community 387]]
- 2 edges to [[_COMMUNITY_Community 69]]
- 1 edge to [[_COMMUNITY_Community 103]]
- 1 edge to [[_COMMUNITY_Community 151]]

## Top bridge nodes
- [[Phase 3 Batch C Calibration Tests]] - degree 16, connects to 4 communities
- [[calibrate_city_weights()]] - degree 20, connects to 3 communities
- [[_make_db()_1]] - degree 15, connects to 1 community
- [[TestRandomSearchAndGate]] - degree 8, connects to 1 community
- [[dot-test_auto_split_80_20()]] - degree 5, connects to 1 community