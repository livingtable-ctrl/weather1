---
type: community
cohesion: 0.19
members: 13
---

# Community 286

**Cohesion:** 0.19 - loosely connected
**Members:** 13 nodes

## Members
- [[14 - get_edge_decay_curve() must segment by condition_type when provided.]] - rationale - tests/test_tracker.py
- [[dot-_log_with_days_out()]] - code - tests/test_tracker.py
- [[dot-setUp()_21]] - code - tests/test_tracker.py
- [[dot-tearDown()_21]] - code - tests/test_tracker.py
- [[dot-test_grpb_edge_decay_condition_type_filters()]] - code - tests/test_tracker.py
- [[dot-test_grpb_edge_decay_no_filter_returns_all()]] - code - tests/test_tracker.py
- [[dot-test_grpb_edge_decay_returns_list()]] - code - tests/test_tracker.py
- [[dot-test_grpb_edge_decay_unknown_condition_type_returns_empty()]] - code - tests/test_tracker.py
- [[Filtering by a condition_type with no data returns empty list.]] - rationale - tests/test_tracker.py
- [[Filtering by above should exclude precip_any rows.]] - rationale - tests/test_tracker.py
- [[No filter should return rows from all condition types.]] - rationale - tests/test_tracker.py
- [[Return value is always a list (never None).]] - rationale - tests/test_tracker.py
- [[TestEdgeDecayCurveConditionTypeGrpB]] - code - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_286
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestEdgeDecayCurveConditionTypeGrpB]] - degree 9, connects to 1 community