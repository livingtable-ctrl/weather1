---
type: community
cohesion: 0.10
members: 25
---

# Community 111

**Cohesion:** 0.10 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-test_cycle_dedup_skips_already_ordered()]] - code - tests/test_live_execution.py
- [[dot-test_falls_back_to_rest_when_ws_cache_missing()]] - code - tests/test_live_execution.py
- [[dot-test_falls_back_to_rest_when_ws_entry_one_sided()]] - code - tests/test_live_execution.py
- [[dot-test_filled_order_updates_status()]] - code - tests/test_live_execution.py
- [[dot-test_places_order_when_not_yet_ordered()]] - code - tests/test_live_execution.py
- [[dot-test_returns_false_when_already_ordered_this_cycle()]] - code - tests/test_live_execution.py
- [[dot-test_returns_none_when_both_sources_unavailable()]] - code - tests/test_live_execution.py
- [[dot-test_returns_none_when_rest_market_has_no_quote()]] - code - tests/test_live_execution.py
- [[dot-test_uses_ws_cache_when_fresh_and_complete()]] - code - tests/test_live_execution.py
- [[dot-test_var_computation_error_skips_the_trade()]] - code - tests/test_live_execution.py
- [[A one-sided WS book (no real ask) must not be treated as usable -- falls…]] - rationale - tests/test_live_execution.py
- [[F5 a portfolio_var() exception used to be swallowed at DEBUG and the trade…]] - rationale - tests/test_live_execution.py
- [[If was_ordered_this_cycle returns True, no paper or live order is placed.]] - rationale - tests/test_live_execution.py
- [[Positive control order fires when dedup finds no prior order this cycle.]] - rationale - tests/test_live_execution.py
- [[Return a market-price-shaped dict ({yes_bid ..., yes_ask ...}) with the…]] - rationale - order_executor.py
- [[TestAutoPlaceTradesCycleCheck]] - code - tests/test_live_execution.py
- [[TestGetCurrentBook]] - code - tests/test_live_execution.py
- [[TestPlaceLiveOrderDedup]] - code - tests/test_live_execution.py
- [[TestPollPendingOrders]] - code - tests/test_live_execution.py
- [[TestVarGateFailsClosed]] - code - tests/test_live_execution.py
- [[Tests for live execution path in main.py.]] - rationale - tests/test_live_execution.py
- [[_get_current_book()]] - code - order_executor.py
- [[_place_live_order must return (False, 0.0) when the ticker was already ordered…]] - rationale - tests/test_live_execution.py
- [[_poll_pending_orders updates a pending live order to 'filled' when API returns…]] - rationale - tests/test_live_execution.py
- [[test_live_execution.py]] - code - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_111
SORT file.name ASC
```

## Connections to other communities
- 17 edges to [[_COMMUNITY_Community 45]]
- 6 edges to [[_COMMUNITY_Community 67]]
- 6 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 4 edges to [[_COMMUNITY_Community 144]]
- 4 edges to [[_COMMUNITY_Community 215]]
- 4 edges to [[_COMMUNITY_Community 110]]
- 3 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 3 edges to [[_COMMUNITY_Community 157]]
- 2 edges to [[_COMMUNITY_Community 227]]
- 2 edges to [[_COMMUNITY_Community 300]]
- 2 edges to [[_COMMUNITY_Community 389]]
- 2 edges to [[_COMMUNITY_Community 329]]
- 1 edge to [[_COMMUNITY_Community 198]]
- 1 edge to [[_COMMUNITY_Community 328]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 183]]
- 1 edge to [[_COMMUNITY_Community 429]]
- 1 edge to [[_COMMUNITY_Community 468]]
- 1 edge to [[_COMMUNITY_Community 469]]
- 1 edge to [[_COMMUNITY_Community 337]]
- 1 edge to [[_COMMUNITY_Community 171]]
- 1 edge to [[_COMMUNITY_Community 338]]

## Top bridge nodes
- [[test_live_execution.py]] - degree 54, connects to 20 communities
- [[_get_current_book()]] - degree 16, connects to 7 communities
- [[TestGetCurrentBook]] - degree 8, connects to 1 community
- [[TestPlaceLiveOrderDedup]] - degree 6, connects to 1 community
- [[TestVarGateFailsClosed]] - degree 5, connects to 1 community