---
type: community
cohesion: 0.10
members: 24
---

# Community 119

**Cohesion:** 0.10 - loosely connected
**Members:** 24 nodes

## Members
- [[dot-test_city_weights_file_exists()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_city_weights_values_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_condition_weights_file_exists()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_condition_weights_has_all_types()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_condition_weights_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_errors_when_weights_dont_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_minneapolis_not_97pct_climatology()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_minneapolis_weights_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_no_warnings_with_complete_files()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_seasonal_weights_file_exists()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_seasonal_weights_has_all_seasons()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_seasonal_weights_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_warns_when_season_missing()]] - code - tests/test_phase2_batch_c.py
- [[P2-10 Minneapolis city weights must not have 0.97 climatology.]] - rationale - tests/test_phase2_batch_c.py
- [[P2-7 Warn on missing or malformed weight file entries at startup.]] - rationale - calibration.py
- [[P2-7 seasonal, condition, and city weight files must be present.]] - rationale - tests/test_phase2_batch_c.py
- [[P2-7 validate_weight_files warns on missingmalformed entries.]] - rationale - tests/test_phase2_batch_c.py
- [[Phase 2 Batch C Regression Tests]] - code - tests/test_phase2_batch_c.py
- [[Phase 2 Batch C regression tests P2-7, P2-10, P2-12, P2-13.]] - rationale - tests/test_phase2_batch_c.py
- [[TestMinneapolisWeights]] - code - tests/test_phase2_batch_c.py
- [[TestValidateWeightFiles]] - code - tests/test_phase2_batch_c.py
- [[TestWeightFilesExist]] - code - tests/test_phase2_batch_c.py
- [[dataseasonal_condition_city_weights.json]] - document - data/city_weights.json
- [[validate_weight_files()]] - code - calibration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_119
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 51]]
- 3 edges to [[_COMMUNITY_Community 103]]
- 3 edges to [[_COMMUNITY_Community 118]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 344]]
- 1 edge to [[_COMMUNITY_Community 432]]
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]

## Top bridge nodes
- [[Phase 2 Batch C Regression Tests]] - degree 13, connects to 6 communities
- [[validate_weight_files()]] - degree 13, connects to 3 communities
- [[dataseasonal_condition_city_weights.json]] - degree 4, connects to 2 communities
- [[TestWeightFilesExist]] - degree 11, connects to 1 community
- [[TestValidateWeightFiles]] - degree 6, connects to 1 community