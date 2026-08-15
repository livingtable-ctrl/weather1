---
type: community
cohesion: 0.10
members: 34
---

# Community 67

**Cohesion:** 0.10 - loosely connected
**Members:** 34 nodes

## Members
- [[dot-_seed_pending()]] - code - tests/test_live_execution.py
- [[dot-setup_method()_37]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_29]] - code - tests/test_live_execution.py
- [[dot-test_amend_exchange_success_survives_bookkeeping_failure()]] - code - tests/test_live_execution.py
- [[dot-test_amend_failure_leaves_old_row_pending_not_amended()]] - code - tests/test_live_execution.py
- [[dot-test_amend_success_logs_new_row_and_marks_old_row_amended()]] - code - tests/test_live_execution.py
- [[dot-test_amend_that_crosses_the_book_is_logged_as_filled()]] - code - tests/test_live_execution.py
- [[dot-test_empty_liquid_opps_is_a_noop()]] - code - tests/test_live_execution.py
- [[dot-test_midpoint_no_side()]] - code - tests/test_live_execution.py
- [[dot-test_midpoint_yes_side()]] - code - tests/test_live_execution.py
- [[dot-test_order_younger_than_blanket_gate_is_untouched()]] - code - tests/test_live_execution.py
- [[dot-test_price_moved_reprices_as_new_maker_order()]] - code - tests/test_live_execution.py
- [[dot-test_price_unchanged_leaves_order_resting()]] - code - tests/test_live_execution.py
- [[dot-test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses()]] - code - tests/test_live_execution.py
- [[dot-test_strong_edge_and_rested_crosses_as_taker()]] - code - tests/test_live_execution.py
- [[dot-test_ticker_not_in_scan_leaves_order_untouched()]] - code - tests/test_live_execution.py
- [[dot-test_validation_failure_cancels_without_replacing()]] - code - tests/test_live_execution.py
- [[AMEND ORDER (V2) superseded the old cancel+verify-then-replace fill-race…]] - rationale - tests/test_live_execution.py
- [[AMEND ORDER (V2) reprice-improve amends in place -- see…]] - rationale - tests/test_live_execution.py
- [[If amend_order() raises, the old row must NOT be marked 'amended' -- the…]] - rationale - tests/test_live_execution.py
- [[If the exchange call succeeds but a SUBSEQUENT execution_log write raises (e.g.…]] - rationale - tests/test_live_execution.py
- [[Reprice a resting live order in place via Kalshi's atomic amend endpoint,…]] - rationale - order_executor.py
- [[Reprice-or-cancel resting live orders based on this cycle's fresh market…]] - rationale - order_executor.py
- [[Return midpoint of current bidask for the given side, rounded to 2dp. Handles…]] - rationale - order_executor.py
- [[TestMidpointPrice]] - code - tests/test_live_execution.py
- [[TestRepriceOrCancelPendingOrders]] - code - tests/test_live_execution.py
- [[The _MIN_REST_MINUTES_BEFORE_REPRICE, _MIN_REST_MINUTES_BEFORE_TAKER_CROSS)…]] - rationale - tests/test_live_execution.py
- [[The core reprice-or-cancel policy cancel on edge decay, cancel+ replace as…]] - rationale - tests/test_live_execution.py
- [[Younger than _MIN_REST_MINUTES_BEFORE_REPRICE (2 min) - left resting…]] - rationale - tests/test_live_execution.py
- [[_amend_live_order()]] - code - order_executor.py
- [[_midpoint_price is still used for live order placementrepricing…]] - rationale - tests/test_live_execution.py
- [[_midpoint_price()]] - code - order_executor.py
- [[_reprice_or_cancel_pending_orders()]] - code - order_executor.py
- [[execution_log bookkeeping for a successful amend a NEW row is logged (chained…]] - rationale - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_67
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 111]]
- 4 edges to [[_COMMUNITY_Community 45]]
- 4 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 3 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 2 edges to [[_COMMUNITY_Community 164]]
- 1 edge to [[_COMMUNITY_Community 157]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 215]]
- 1 edge to [[_COMMUNITY_Community 300]]
- 1 edge to [[_COMMUNITY_Community 329]]
- 1 edge to [[_COMMUNITY_Community 389]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 85]]

## Top bridge nodes
- [[_reprice_or_cancel_pending_orders()]] - degree 25, connects to 10 communities
- [[_amend_live_order()]] - degree 9, connects to 4 communities
- [[_midpoint_price()]] - degree 8, connects to 4 communities
- [[TestRepriceOrCancelPendingOrders]] - degree 19, connects to 2 communities
- [[TestMidpointPrice]] - degree 6, connects to 2 communities