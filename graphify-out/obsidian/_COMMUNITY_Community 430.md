---
type: community
cohesion: 0.25
members: 8
---

# Community 430

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_get_brier_by_version_empty()]] - code - tests/test_p9_p10.py
- [[dot-test_get_brier_by_version_groups_correctly()]] - code - tests/test_p9_p10.py
- [[dot-test_log_prediction_stores_edge_calc_version()]] - code - tests/test_p9_p10.py
- [[dot-test_log_prediction_version_defaults_to_none()]] - code - tests/test_p9_p10.py
- [[Callers that don't pass edge_calc_version store NULL (backward compat).]] - rationale - tests/test_p9_p10.py
- [[Predictions stamped with different versions produce separate Brier entries.]] - rationale - tests/test_p9_p10.py
- [[TestStrategyVersioning]] - code - tests/test_p9_p10.py
- [[edge_calc_version kwarg is stored and retrievable.]] - rationale - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_430
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 101]]
- 1 edge to [[_COMMUNITY_Community 50]]

## Top bridge nodes
- [[TestStrategyVersioning]] - degree 5, connects to 1 community
- [[dot-test_get_brier_by_version_groups_correctly()]] - degree 3, connects to 1 community
- [[dot-test_log_prediction_stores_edge_calc_version()]] - degree 3, connects to 1 community