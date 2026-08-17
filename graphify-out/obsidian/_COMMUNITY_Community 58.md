---
type: community
cohesion: 0.08
members: 36
---

# Community 58

**Cohesion:** 0.08 - loosely connected
**Members:** 36 nodes

## Members
- [[dot-setup_method()_32]] - code - tests/test_calibration.py
- [[dot-setup_method()_33]] - code - tests/test_calibration.py
- [[dot-setup_method()_34]] - code - tests/test_calibration.py
- [[dot-teardown_method()_24]] - code - tests/test_calibration.py
- [[dot-teardown_method()_25]] - code - tests/test_calibration.py
- [[dot-teardown_method()_26]] - code - tests/test_calibration.py
- [[dot-test_below_threshold_omits_city()]] - code - tests/test_calibration.py
- [[dot-test_below_threshold_omits_season()]] - code - tests/test_calibration.py
- [[dot-test_calibrate_calls_update_learned_weights()]] - code - tests/test_calibration.py
- [[dot-test_calibrate_platt_excludes_rain_only_city()]] - code - tests/test_calibration.py
- [[dot-test_calibrate_platt_excludes_snow_only_city()]] - code - tests/test_calibration.py
- [[dot-test_calibrate_writes_seasonal_json()]] - code - tests/test_calibration.py
- [[dot-test_monthly_rain_rows_not_counted()]] - code - tests/test_calibration.py
- [[dot-test_monthly_snow_rows_not_counted()]] - code - tests/test_calibration.py
- [[dot-test_returns_weights_for_qualifying_city()]] - code - tests/test_calibration.py
- [[dot-test_returns_weights_summing_to_one()]] - code - tests/test_calibration.py
- [[dot-test_rows_without_source_probs_not_counted()]] - code - tests/test_calibration.py
- [[10 predictions ( 20) → season returned with neutral uncalibrated defaults.]] - rationale - tests/test_calibration.py
- [[10 predictions ( 50) → city absent.]] - rationale - tests/test_calibration.py
- [[55 NYC predictions (= 50) → NYC weights present and valid.]] - rationale - tests/test_calibration.py
- [[60 winter predictions → winter weights present and sum to 1.0.]] - rationale - tests/test_calibration.py
- [[Generate n rows with a winter market_date (January).]] - rationale - tests/test_calibration.py
- [[P1-9 cmd_calibrate() must call update_learned_weights_from_tracker().]] - rationale - tests/test_calibration.py
- [[Rows missing ensemble_probnws_probclim_prob must not count toward threshold.]] - rationale - tests/test_calibration.py
- [[Seed a minimal predictions + outcomes DB for calibration tests.]] - rationale - tests/test_calibration.py
- [[TestCalibrateCLI]] - code - tests/test_calibration.py
- [[TestCalibrateCityWeights]] - code - tests/test_calibration.py
- [[TestCalibrateSeasonalWeights]] - code - tests/test_calibration.py
- [[_make_winter_rows()]] - code - tests/test_calibration.py
- [[_seed_db()]] - code - tests/test_calibration.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Snow Step 2 the identical…]] - rationale - tests/test_calibration.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 (review- caught, MEDIUM…]] - rationale - tests/test_calibration.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 (review- caught, defense-…]] - rationale - tests/test_calibration.py
- [[backlog.txt Snow Step 2 the identical defense-in-depth check, mirrored for…]] - rationale - tests/test_calibration.py
- [[cmd_calibrate writes JSON files to data when enough data exists.]] - rationale - tests/test_calibration.py
- [[cmd_calibrate() writes dataseasonal_weights.json with calibrated weights.]] - rationale - tests/test_calibration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_58
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 4]]
- 5 edges to [[_COMMUNITY_Community 400]]
- 4 edges to [[_COMMUNITY_Community 109]]
- 2 edges to [[_COMMUNITY_Community 125]]

## Top bridge nodes
- [[_seed_db()]] - degree 14, connects to 2 communities
- [[_make_winter_rows()]] - degree 13, connects to 1 community
- [[TestCalibrateCLI]] - degree 8, connects to 1 community
- [[TestCalibrateSeasonalWeights]] - degree 8, connects to 1 community
- [[TestCalibrateCityWeights]] - degree 5, connects to 1 community