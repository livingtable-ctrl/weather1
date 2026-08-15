---
type: community
cohesion: 0.31
members: 9
---

# Community 389

**Cohesion:** 0.31 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-setup_method()_17]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_16]] - code - tests/test_live_execution.py
- [[dot-test_gate_blocked_returns_false_and_places_nothing()]] - code - tests/test_live_execution.py
- [[dot-test_place_order_failure_logs_failed_status()]] - code - tests/test_live_execution.py
- [[dot-test_success_logs_replaces_order_id()]] - code - tests/test_live_execution.py
- [[dot-test_taker_cross_logged_as_market_order_type()]] - code - tests/test_live_execution.py
- [[Place a replacement order for a just-canceled resting order (reprice or taker-…]] - rationale - order_executor.py
- [[TestReplaceLiveOrder]] - code - tests/test_live_execution.py
- [[_replace_live_order()]] - code - order_executor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_389
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 111]]
- 2 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 67]]

## Top bridge nodes
- [[_replace_live_order()]] - degree 11, connects to 4 communities
- [[TestReplaceLiveOrder]] - degree 9, connects to 2 communities