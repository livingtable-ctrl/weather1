---
type: community
cohesion: 0.18
members: 11
---

# Community 346

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-setup_method()_23]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_15]] - code - tests/test_live_execution.py
- [[dot-test_canceled_order_resolves_to_canceled()]] - code - tests/test_live_execution.py
- [[dot-test_executed_order_resolves_to_internal_filled_status()]] - code - tests/test_live_execution.py
- [[dot-test_partial_fill_then_cancel_resolves_to_filled()]] - code - tests/test_live_execution.py
- [[dot-test_resting_order_resolves_to_pending()]] - code - tests/test_live_execution.py
- [[2026-07-09 Kalshi's real order-status enum is restingcanceledexecuted --…]] - rationale - tests/test_live_execution.py
- [[A pending row whose order actually executed must resolve to this bot's internal…]] - rationale - tests/test_live_execution.py
- [[A resting order must land on status='pending' — the only status every…]] - rationale - tests/test_live_execution.py
- [[F9 Kalshi has no distinct 'partially filled' status -- an order that fills…]] - rationale - tests/test_live_execution.py
- [[TestRecoverPendingOrders]] - code - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_346
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 3]]
- 3 edges to [[_COMMUNITY_Community 12]]

## Top bridge nodes
- [[TestRecoverPendingOrders]] - degree 11, connects to 2 communities
- [[dot-test_executed_order_resolves_to_internal_filled_status()]] - degree 3, connects to 1 community
- [[dot-test_partial_fill_then_cancel_resolves_to_filled()]] - degree 3, connects to 1 community
- [[dot-test_resting_order_resolves_to_pending()]] - degree 3, connects to 1 community
- [[dot-test_canceled_order_resolves_to_canceled()]] - degree 2, connects to 1 community