---
type: community
cohesion: 0.33
members: 6
---

# Community 522

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-setUp()_39]] - code - tests/test_tracker.py
- [[dot-tearDown()_38]] - code - tests/test_tracker.py
- [[dot-test_missing_source_probs_stored_as_null()]] - code - tests/test_tracker.py
- [[Calling log_prediction without source probs stores NULL (old callers safe).]] - rationale - tests/test_tracker.py
- [[TestSourceProbsPassthrough]] - code - tests/test_tracker.py
- [[log_prediction called without source probs must store NULLs (backward compat).]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_522
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestSourceProbsPassthrough]] - degree 5, connects to 1 community