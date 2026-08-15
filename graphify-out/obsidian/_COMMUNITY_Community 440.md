---
type: community
cohesion: 0.25
members: 8
---

# Community 440

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-setUp()_32]] - code - tests/test_tracker.py
- [[dot-tearDown()_31]] - code - tests/test_tracker.py
- [[dot-test_columns_exist_after_init()]] - code - tests/test_tracker.py
- [[dot-test_log_prediction_stores_source_probs()]] - code - tests/test_tracker.py
- [[After init_db(), predictions table must have ensemble_prob, nws_prob, clim_prob.]] - rationale - tests/test_tracker.py
- [[Schema v9 must add ensemble_prob, nws_prob, clim_prob to predictions.]] - rationale - tests/test_tracker.py
- [[TestPerSourceProbColumns]] - code - tests/test_tracker.py
- [[log_prediction with source probs stores them retrievable from DB.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_440
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestPerSourceProbColumns]] - degree 6, connects to 1 community