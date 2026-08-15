---
type: community
cohesion: 0.31
members: 9
---

# Community 411

**Cohesion:** 0.31 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-_add_typed()]] - code - tests/test_tracker.py
- [[dot-test_bias_no_condition_type_includes_all()]] - code - tests/test_tracker.py
- [[dot-test_grpb_bias_condition_type_filters_rows()]] - code - tests/test_tracker.py
- [[dot-test_grpb_bias_unknown_condition_type_returns_zero()]] - code - tests/test_tracker.py
- [[Filtering by HIGH vs PRECIP gives different bias values.]] - rationale - tests/test_tracker.py
- [[Filtering by a condition_type with no matching rows returns 0.0.]] - rationale - tests/test_tracker.py
- [[TestGetBiasConditionType]] - code - tests/test_tracker.py
- [[Tests for get_bias() stratified by condition_type (10).]] - rationale - tests/test_tracker.py
- [[Without condition_type filter, bias uses all rows.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_411
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 313]]
- 1 edge to [[_COMMUNITY_Community 135]]

## Top bridge nodes
- [[TestGetBiasConditionType]] - degree 7, connects to 2 communities
- [[dot-_add_typed()]] - degree 5, connects to 1 community