---
type: community
cohesion: 0.13
members: 26
---

# Community 103

**Cohesion:** 0.13 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-setup_method()_1]] - code - tests/test_calibration.py
- [[dot-setup_method()_2]] - code - tests/test_calibration.py
- [[dot-teardown_method()_1]] - code - tests/test_calibration.py
- [[dot-teardown_method()_2]] - code - tests/test_calibration.py
- [[dot-test_load_city_missing_file_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_city_valid_json_returns_dict()]] - code - tests/test_calibration.py
- [[dot-test_load_condition_corrupt_json_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_condition_missing_file_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_condition_valid_json_returns_dict()]] - code - tests/test_calibration.py
- [[dot-test_load_seasonal_corrupt_json_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_seasonal_missing_file_returns_empty()]] - code - tests/test_calibration.py
- [[dot-test_load_seasonal_valid_json_returns_dict()]] - code - tests/test_calibration.py
- [[Load per-city weights from JSON. Returns {} if file missing.]] - rationale - calibration.py
- [[Load per-condition-type weights from JSON. Returns {} if file missing.]] - rationale - calibration.py
- [[Load seasonal weights from JSON. Returns {} if file missing.]] - rationale - calibration.py
- [[Path_16]] - code
- [[TestCalibrateCityWeights]] - code - tests/test_calibration.py
- [[TestLoadWeights]] - code - tests/test_calibration.py
- [[Tests for calibration.py — seasonal and per-city blend weight calibration.]] - rationale - tests/test_calibration.py
- [[load_city_weights()]] - code - calibration.py
- [[load_condition_weights()]] - code - calibration.py
- [[load_seasonal_weights and load_city_weights must handle missingvalidcorrupt…]] - rationale - tests/test_calibration.py
- [[load_seasonal_weights()]] - code - calibration.py
- [[run_backtest result includes brier_by_condition dict.]] - rationale - tests/test_calibration.py
- [[test_calibration.py]] - code - tests/test_calibration.py
- [[test_run_backtest_reports_per_condition_type()]] - code - tests/test_calibration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_103
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 118]]
- 9 edges to [[_COMMUNITY_Community 69]]
- 4 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 3 edges to [[_COMMUNITY_Community 119]]
- 2 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 2 edges to [[_COMMUNITY_Community 109]]
- 1 edge to [[_COMMUNITY_Community 72]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]

## Top bridge nodes
- [[test_calibration.py]] - degree 23, connects to 9 communities
- [[load_condition_weights()]] - degree 9, connects to 3 communities
- [[load_seasonal_weights()]] - degree 9, connects to 3 communities
- [[load_city_weights()]] - degree 8, connects to 3 communities
- [[Path_16]] - degree 12, connects to 1 community