---
type: community
cohesion: 0.13
members: 26
---

# Community 109

**Cohesion:** 0.13 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-setup_method()]] - code - tests/test_calibration.py
- [[dot-teardown_method()]] - code - tests/test_calibration.py
- [[dot-test_errors_when_weights_dont_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_load_city_missing_file_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_city_valid_json_returns_dict()]] - code - tests/test_calibration.py
- [[dot-test_load_condition_corrupt_json_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_condition_missing_file_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_condition_valid_json_returns_dict()]] - code - tests/test_calibration.py
- [[dot-test_load_seasonal_corrupt_json_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_seasonal_missing_file_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_seasonal_valid_json_returns_dict()]] - code - tests/test_calibration.py
- [[dot-test_no_warnings_with_complete_files()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_warns_when_season_missing()]] - code - tests/test_phase2_batch_c.py
- [[Load per-city weights from JSON. Returns {} if file missing.]] - rationale - calibration.py
- [[Load per-condition-type weights from JSON. Returns {} if file missing.]] - rationale - calibration.py
- [[Load seasonal weights from JSON. Returns {} if file missing.]] - rationale - calibration.py
- [[P2-7 Warn on missing or malformed weight file entries at startup.]] - rationale - calibration.py
- [[P2-7 validate_weight_files warns on missingmalformed entries.]] - rationale - tests/test_phase2_batch_c.py
- [[Path_3]] - code
- [[TestLoadWeights]] - code - tests/test_calibration.py
- [[TestValidateWeightFiles]] - code - tests/test_phase2_batch_c.py
- [[load_city_weights()]] - code - calibration.py
- [[load_condition_weights()]] - code - calibration.py
- [[load_seasonal_weights and load_city_weights must handle missingvalidcorrupt…]] - rationale - tests/test_calibration.py
- [[load_seasonal_weights()]] - code - calibration.py
- [[validate_weight_files()]] - code - calibration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_109
SORT file.name ASC
```

## Connections to other communities
- 10 edges to [[_COMMUNITY_Community 4]]
- 4 edges to [[_COMMUNITY_Community 400]]
- 4 edges to [[_COMMUNITY_Community 58]]
- 3 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[validate_weight_files()]] - degree 12, connects to 3 communities
- [[load_condition_weights()]] - degree 9, connects to 3 communities
- [[load_seasonal_weights()]] - degree 9, connects to 3 communities
- [[load_city_weights()]] - degree 8, connects to 3 communities
- [[TestValidateWeightFiles]] - degree 6, connects to 2 communities