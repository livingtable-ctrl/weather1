---
type: community
cohesion: 0.31
members: 9
---

# Community 406

**Cohesion:** 0.31 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-_make_condition_db()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_accepts_cutoff_date_kwarg()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_cutoff_date_with_min_samples()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_no_market_date_rows_handled_gracefully()]] - code - tests/test_phase3_batch_c.py
- [[dot-test_weights_sum_to_one()_4]] - code - tests/test_phase3_batch_c.py
- [[P3-16 calibrate_condition_weights accepts cutoff_date; no look-ahead bias.]] - rationale - tests/test_phase3_batch_c.py
- [[Path_28]] - code
- [[Rows with NULL market_date fall back to empty-string cutoff comparison.]] - rationale - tests/test_phase3_batch_c.py
- [[TestTemporalIsolationCondition]] - code - tests/test_phase3_batch_c.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_406
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 118]]
- 4 edges to [[_COMMUNITY_Community 72]]

## Top bridge nodes
- [[dot-test_no_market_date_rows_handled_gracefully()]] - degree 4, connects to 2 communities
- [[TestTemporalIsolationCondition]] - degree 7, connects to 1 community
- [[dot-_make_condition_db()]] - degree 6, connects to 1 community
- [[dot-test_accepts_cutoff_date_kwarg()]] - degree 3, connects to 1 community
- [[dot-test_cutoff_date_with_min_samples()]] - degree 3, connects to 1 community