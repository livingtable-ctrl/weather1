---
type: community
cohesion: 0.25
members: 8
---

# Community 438

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_empty_condition_type_filter()]] - code - tests/test_tracker.py
- [[dot-test_no_filter_returns_all()]] - code - tests/test_tracker.py
- [[dot-test_nyc_high_vs_precip_different_bias()]] - code - tests/test_tracker.py
- [[Filtering by non-existent condition_type returns empty dict.]] - rationale - tests/test_tracker.py
- [[NYC HIGH vs NYC PRECIP should have different bias.]] - rationale - tests/test_tracker.py
- [[TestCalibrationByCityConditionType]] - code - tests/test_tracker.py
- [[Tests for get_calibration_by_city() with condition_type (54, 56).]] - rationale - tests/test_tracker.py
- [[Without condition_type, all predictions are included.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_438
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 135]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 313]]

## Top bridge nodes
- [[TestCalibrationByCityConditionType]] - degree 6, connects to 2 communities
- [[dot-test_empty_condition_type_filter()]] - degree 3, connects to 1 community
- [[dot-test_no_filter_returns_all()]] - degree 3, connects to 1 community
- [[dot-test_nyc_high_vs_precip_different_bias()]] - degree 3, connects to 1 community