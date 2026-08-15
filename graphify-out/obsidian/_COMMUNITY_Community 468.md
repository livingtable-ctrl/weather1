---
type: community
cohesion: 0.29
members: 7
---

# Community 468

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-setup_method()_32]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_24]] - code - tests/test_live_execution.py
- [[dot-test_amended_row_excluded_new_row_counted_once()]] - code - tests/test_live_execution.py
- [[dot-test_mutation_amended_included_would_double_count()]] - code - tests/test_live_execution.py
- [[AMEND ORDER (V2) get_today_live_spend() must exclude 'amended' rows the same…]] - rationale - tests/test_live_execution.py
- [[Direct proof the exclusion is load-bearing temporarily querying with 'amended'…]] - rationale - tests/test_live_execution.py
- [[TestGetTodayLiveSpendExcludesAmended]] - code - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_468
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 111]]

## Top bridge nodes
- [[TestGetTodayLiveSpendExcludesAmended]] - degree 8, connects to 2 communities