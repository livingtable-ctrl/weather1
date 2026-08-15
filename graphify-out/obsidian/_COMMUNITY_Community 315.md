---
type: community
cohesion: 0.23
members: 12
---

# Community 315

**Cohesion:** 0.23 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-_add_decay()]] - code - tests/test_tracker.py
- [[dot-test_condition_type_filter_returns_list()]] - code - tests/test_tracker.py
- [[dot-test_empty_when_no_matching_condition()]] - code - tests/test_tracker.py
- [[dot-test_high_vs_precip_differ()]] - code - tests/test_tracker.py
- [[dot-test_no_filter_uses_all()]] - code - tests/test_tracker.py
- [[Add n predictions with a given edge size and days_out.]] - rationale - tests/test_tracker.py
- [[HIGH and PRECIP should produce different curves.]] - rationale - tests/test_tracker.py
- [[Non-existent condition_type returns empty list.]] - rationale - tests/test_tracker.py
- [[TestEdgeDecayCurveConditionType]] - code - tests/test_tracker.py
- [[Tests for get_edge_decay_curve() stratified by condition_type (14).]] - rationale - tests/test_tracker.py
- [[Without filter, all condition types are included.]] - rationale - tests/test_tracker.py
- [[get_edge_decay_curve(condition_type='HIGH') returns a list.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_315
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 313]]
- 1 edge to [[_COMMUNITY_Community 135]]

## Top bridge nodes
- [[TestEdgeDecayCurveConditionType]] - degree 8, connects to 2 communities
- [[dot-_add_decay()]] - degree 7, connects to 1 community