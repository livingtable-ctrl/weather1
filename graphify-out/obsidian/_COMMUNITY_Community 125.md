---
type: community
cohesion: 0.16
members: 24
---

# Community 125

**Cohesion:** 0.16 - loosely connected
**Members:** 24 nodes

## Members
- [[dot-test_49_rows_city_omitted()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_50_rows_city_present()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_all_weights_in_range()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_auto_split_80_20()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_calibrate_city_weights_deterministic()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_city_accepts_cutoff_date_kwarg()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_city_min_is_50()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_cutoff_excludes_future_rows_from_training()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_seasonal_accepts_cutoff_date_kwarg()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_weights_sum_to_one()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_weights_with_explicit_cutoff_sum_to_one()]] - code - tests/test_phase3_batch_c.py
- [[Generate n rows with spread-out dates for stable 8020 splits.]] - rationale - tests/test_phase3_batch_c.py
- [[Grid-search optimal blend weights per city. Returns {city {ensemble,…]] - rationale - calibration.py
- [[P3-1 calibrate_seasonal_weights and calibrate_city_weights accept cutoff_date.]] - rationale - tests/test_phase3_batch_c.py
- [[P3-25 _CITY_MIN must be 50.]] - rationale - tests/test_phase3_batch_c.py
- [[Rows after cutoff must not affect training — weights with tight cutoff differ.]] - rationale - tests/test_phase3_batch_c.py
- [[Same data → same weights (random search uses fixed seed=42).]] - rationale - tests/test_phase3_batch_c.py
- [[Seed a predictions+outcomes DB for calibration tests.]] - rationale - tests/test_phase3_batch_c.py
- [[TestCityMinThreshold]] - code - tests/test_phase3_batch_c.py
- [[TestTemporalIsolationSeasonalCity]] - code - tests/test_phase3_batch_c.py
- [[Without cutoff_date, function runs without error on enough rows.]] - rationale - tests/test_phase3_batch_c.py
- [[_make_db()]] - code - tests/test_phase3_batch_c.py
- [[_rows()]] - code - tests/test_phase3_batch_c.py
- [[calibrate_city_weights()]] - code - calibration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_125
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 147]]
- 6 edges to [[_COMMUNITY_Community 400]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 266]]
- 2 edges to [[_COMMUNITY_Community 58]]

## Top bridge nodes
- [[calibrate_city_weights()]] - degree 20, connects to 4 communities
- [[_make_db()]] - degree 15, connects to 2 communities
- [[_rows()]] - degree 12, connects to 1 community
- [[TestTemporalIsolationSeasonalCity]] - degree 7, connects to 1 community
- [[TestCityMinThreshold]] - degree 5, connects to 1 community