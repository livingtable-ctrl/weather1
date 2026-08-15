---
type: community
cohesion: 0.13
members: 15
---

# Community 239

**Cohesion:** 0.13 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-setUp()_10]] - code - tests/test_tracker.py
- [[dot-tearDown()_10]] - code - tests/test_tracker.py
- [[dot-test_city_breakdown()]] - code - tests/test_tracker.py
- [[dot-test_days_back_filters_old_rows()]] - code - tests/test_tracker.py
- [[dot-test_max_and_min_never_pooled()]] - code - tests/test_tracker.py
- [[dot-test_null_var_rows_excluded()]] - code - tests/test_tracker.py
- [[dot-test_returns_empty_when_no_data()]] - code - tests/test_tracker.py
- [[dot-test_signed_bias_not_absolute_error()]] - code - tests/test_tracker.py
- [[dot-test_under_prediction_gives_negative_bias()]] - code - tests/test_tracker.py
- [[A model that consistently over-predicts must show a POSITIVE bias (not the MAE,…]] - rationale - tests/test_tracker.py
- [[A row logged without var= (legacy, pre-backfill) must not be attributed to…]] - rationale - tests/test_tracker.py
- [[A row older than days_back must be excluded, same convention as…]] - rationale - tests/test_tracker.py
- [[Same model, opposite-signed error on each var -- each bucket must keep its own…]] - rationale - tests/test_tracker.py
- [[TestGetMemberBias]] - code - tests/test_tracker.py
- [[get_member_bias() -- signed per-model bias split by var, feeding…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_239
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestGetMemberBias]] - degree 11, connects to 1 community