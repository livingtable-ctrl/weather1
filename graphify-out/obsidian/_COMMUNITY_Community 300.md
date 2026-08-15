---
type: community
cohesion: 0.30
members: 12
---

# Community 300

**Cohesion:** 0.30 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-_seed_row()]] - code - tests/test_live_execution.py
- [[dot-setup_method()_19]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_12]] - code - tests/test_live_execution.py
- [[dot-test_false_when_cancel_call_itself_raises()]] - code - tests/test_live_execution.py
- [[dot-test_false_when_order_still_resting_despite_zero_fill_count()]] - code - tests/test_live_execution.py
- [[dot-test_false_when_partial_fill_detected()]] - code - tests/test_live_execution.py
- [[dot-test_false_when_post_cancel_verification_query_fails()]] - code - tests/test_live_execution.py
- [[dot-test_true_when_confirmed_unfilled()]] - code - tests/test_live_execution.py
- [[A cancel that hasn't propagated yet (Kalshi still reports resting, zero fills…]] - rationale - tests/test_live_execution.py
- [[Cancel a resting order and return True only if verified both genuinely unfilled…]] - rationale - order_executor.py
- [[TestCancelAndVerifySafeToReplace]] - code - tests/test_live_execution.py
- [[_cancel_and_verify_safe_to_replace()]] - code - order_executor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_300
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 111]]
- 2 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 157]]
- 1 edge to [[_COMMUNITY_Community 67]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]

## Top bridge nodes
- [[_cancel_and_verify_safe_to_replace()]] - degree 10, connects to 4 communities
- [[TestCancelAndVerifySafeToReplace]] - degree 11, connects to 2 communities