---
type: community
cohesion: 0.25
members: 8
---

# Community 429

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-setup_method()_29]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_21]] - code - tests/test_live_execution.py
- [[dot-test_fill_captures_latency_and_mid_price()]] - code - tests/test_live_execution.py
- [[dot-test_log_order_result_coalesce_never_nulls_out_prior_fill_data()]] - code - tests/test_live_execution.py
- [[dot-test_non_fill_status_leaves_instrumentation_null()]] - code - tests/test_live_execution.py
- [[A later log_order_result() call on an already-instrumented row (e.g. from an…]] - rationale - tests/test_live_execution.py
- [[TestFillInstrumentation]] - code - tests/test_live_execution.py
- [[_poll_pending_orders must capture filled_atmarket_mid_at_fill the moment a…]] - rationale - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_429
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 111]]

## Top bridge nodes
- [[TestFillInstrumentation]] - degree 9, connects to 2 communities