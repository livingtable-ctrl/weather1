---
type: community
cohesion: 0.15
members: 25
---

# Community 110

**Cohesion:** 0.15 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-_position()]] - code - tests/test_live_execution.py
- [[dot-test_builds_check_function_compatible_dicts()]] - code - tests/test_live_execution.py
- [[dot-test_excludes_already_early_exited_positions()]] - code - tests/test_live_execution.py
- [[dot-test_full_fill_exit_order_not_treated_as_new_open_position()]] - code - tests/test_live_execution.py
- [[dot-test_full_fill_records_fee_adjusted_pnl()]] - code - tests/test_live_execution.py
- [[dot-test_gain_case_applies_fee_discount()]] - code - tests/test_live_execution.py
- [[dot-test_gate_blocked_returns_false_and_places_nothing()_1]] - code - tests/test_live_execution.py
- [[dot-test_ioc_no_fill_leaves_position_open()]] - code - tests/test_live_execution.py
- [[dot-test_no_side_exit_pnl_uses_no_side_prices_directly()]] - code - tests/test_live_execution.py
- [[dot-test_partial_fill_gain_case_applies_fee_discount()]] - code - tests/test_live_execution.py
- [[dot-test_partial_fill_reconciles_quantity_and_realizes_pnl()]] - code - tests/test_live_execution.py
- [[dot-test_place_order_exception_logs_failed_status()]] - code - tests/test_live_execution.py
- [[dot-test_prefers_filled_at_over_placed_at_for_entered_at()]] - code - tests/test_live_execution.py
- [[dot-test_reflects_reduced_quantity_after_partial_exit()]] - code - tests/test_live_execution.py
- [[A genuine gain (exit_price  entry_price, e.g. a model-exit that fires on a…]] - rationale - tests/test_live_execution.py
- [[Build a paper-trade-shaped dict from execution_log's filled-unsettled live…]] - rationale - order_executor.py
- [[End-to-end proof the partial-fill fix actually closes the gap after…]] - rationale - tests/test_live_execution.py
- [[Mirrors test_gain_case_applies_fee_discount for the partial-fill branch -- the…]] - rationale - tests/test_live_execution.py
- [[Place an immediate taker-cross sell to close an open live position. Re-runs…]] - rationale - order_executor.py
- [[Regression pin for the phantom-position bug on the FULL-fill path specifically…]] - rationale - tests/test_live_execution.py
- [[TestExitLivePosition]] - code - tests/test_live_execution.py
- [[TestGetLiveOpenPositions]] - code - tests/test_live_execution.py
- [[_exit_live_position()]] - code - order_executor.py
- [[_get_live_open_positions()]] - code - order_executor.py
- [[entry_priceexit_price are already side-normalized (see…]] - rationale - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_110
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 45]]
- 7 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 4 edges to [[_COMMUNITY_Community 111]]
- 3 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[_exit_live_position()]] - degree 23, connects to 5 communities
- [[_get_live_open_positions()]] - degree 11, connects to 5 communities
- [[TestExitLivePosition]] - degree 14, connects to 2 communities
- [[TestGetLiveOpenPositions]] - degree 8, connects to 2 communities