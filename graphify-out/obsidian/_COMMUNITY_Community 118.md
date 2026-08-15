---
type: community
cohesion: 0.13
members: 24
---

# Community 118

**Cohesion:** 0.13 - loosely connected
**Members:** 24 nodes

## Members
- [[dot-test_equal_weights_returned_when_gate_fails()]] - code - tests/test_phase3_batch_c.py
- [[Exponential decay weight so recent settled trades count more in calibration.]] - rationale - calibration.py
- [[Grid-search optimal blend weights per condition type (abovebelowbetween).…]] - rationale - calibration.py
- [[Grid-search optimal blend weights per season. Returns {season {ensemble,…]] - rationale - calibration.py
- [[Offline blend-weight calibration for seasonal and per-city model optimization.…]] - rationale - calibration.py
- [[Path_2]] - code
- [[Random-search 200 simplex samples on train_rows; gate on val Brier improvement…]] - rationale - calibration.py
- [[Row]] - code
- [[Run all three blend-weight calibrations and write results atomically to disk.…]] - rationale - calibration.py
- [[Split (date_str, e, c, n, s, weight) rows into (train, val) tuples (date…]] - rationale - calibration.py
- [[When val Brier improvement = 0.001, equal weights are returned.]] - rationale - tests/test_phase3_batch_c.py
- [[_CONDITION_WEIGHTS cache]] - code - weather_markets.py
- [[_best_weights()]] - code - calibration.py
- [[_compute_recency_weight()]] - code - calibration.py
- [[_load_rows()]] - code - calibration.py
- [[_split_rows()]] - code - calibration.py
- [[calibrate_and_save()]] - code - calibration.py
- [[calibrate_condition_weights returns dict keyed by condition type.]] - rationale - tests/test_calibration.py
- [[calibrate_condition_weights()]] - code - calibration.py
- [[calibrate_seasonal_weights()]] - code - calibration.py
- [[calibration.py]] - code - calibration.py
- [[check_edge.py script]] - code - check_edge.py
- [[test_calibrate_condition_weights_returns_per_type_dict()]] - code - tests/test_calibration.py
- [[tracker.DB_PATH  predictions DB]] - code - tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_118
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_Community 72]]
- 9 edges to [[_COMMUNITY_Community 103]]
- 5 edges to [[_COMMUNITY_Community 69]]
- 4 edges to [[_COMMUNITY_Community 406]]
- 3 edges to [[_COMMUNITY_Community 119]]
- 3 edges to [[_COMMUNITY_Community 59]]
- 2 edges to [[_COMMUNITY_Community 387]]
- 2 edges to [[_COMMUNITY_Community 47]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 37]]
- 1 edge to [[_COMMUNITY_Community 151]]
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[calibration.py]] - degree 20, connects to 8 communities
- [[calibrate_and_save()]] - degree 13, connects to 5 communities
- [[calibrate_seasonal_weights()]] - degree 18, connects to 4 communities
- [[calibrate_condition_weights()]] - degree 14, connects to 3 communities
- [[_best_weights()]] - degree 9, connects to 3 communities