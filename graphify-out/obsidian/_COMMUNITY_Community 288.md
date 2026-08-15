---
type: community
cohesion: 0.18
members: 13
---

# Community 288

**Cohesion:** 0.18 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-_analysis()]] - code - tests/test_tracker.py
- [[dot-_analysis()_1]] - code - tests/test_tracker.py
- [[dot-setUp()_16]] - code - tests/test_tracker.py
- [[dot-tearDown()_16]] - code - tests/test_tracker.py
- [[dot-test_column_exists_after_init()_1]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_multiday_excludes_sameday_rows()]] - code - tests/test_tracker.py
- [[dot-test_log_prediction_stores_var()]] - code - tests/test_tracker.py
- [[dot-test_no_var_in_condition_stores_null()]] - code - tests/test_tracker.py
- [[dot-test_upsert_on_same_day_rescan_updates_var()]] - code - tests/test_tracker.py
- [[A daily HIGHLOW market's condition dict may not carry a var key (var lives on…]] - rationale - tests/test_tracker.py
- [[A same-day re-analysis (UPSERT conflict on ticker+predicted_date) must…]] - rationale - tests/test_tracker.py
- [[Schema v53 must add predictions.var, purely additive (backlog.txt HOURLY-…]] - rationale - tests/test_tracker.py
- [[TestPredictionsVarColumn]] - code - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_288
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 128]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Tracker Settlement Sigma & Disputed Rows]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]

## Top bridge nodes
- [[dot-_analysis()_1]] - degree 6, connects to 2 communities
- [[dot-test_count_settled_signal_rows_multiday_excludes_sameday_rows()]] - degree 3, connects to 2 communities
- [[TestPredictionsVarColumn]] - degree 9, connects to 1 community