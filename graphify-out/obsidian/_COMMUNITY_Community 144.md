---
type: community
cohesion: 0.16
members: 21
---

# Community 144

**Cohesion:** 0.16 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-_open_position_row()]] - code - tests/test_live_execution.py
- [[dot-_open_position_row()_1]] - code - tests/test_live_execution.py
- [[dot-test_healthy_position_is_left_alone()]] - code - tests/test_live_execution.py
- [[dot-test_missing_entry_prob_is_skipped()]] - code - tests/test_live_execution.py
- [[dot-test_model_flip_beyond_threshold_triggers_exit()]] - code - tests/test_live_execution.py
- [[dot-test_no_client_returns_zero()]] - code - tests/test_live_execution.py
- [[dot-test_no_open_positions_is_a_no_op()]] - code - tests/test_live_execution.py
- [[dot-test_stop_loss_and_breakeven_are_mutually_exclusive_same_cycle()]] - code - tests/test_live_execution.py
- [[dot-test_stop_loss_breach_triggers_immediate_exit()]] - code - tests/test_live_execution.py
- [[dot-test_stop_loss_fires_on_rest_fallback_integer_cents_book()]] - code - tests/test_live_execution.py
- [[dot-test_two_positions_on_same_ticker_both_get_exited()]] - code - tests/test_live_execution.py
- [[dot-test_two_positions_same_ticker_only_one_individually_breaches_both_exit()]] - code - tests/test_live_execution.py
- [[dot-test_within_settlement_gate_skips_exit()]] - code - tests/test_live_execution.py
- [[A ticker that stop-loss-exits must not also be evaluated for a breakeven exit…]] - rationale - tests/test_live_execution.py
- [[Protect open live positions with stop-loss and breakeven-stop checks, reusing…]] - rationale - order_executor.py
- [[Regression _get_current_book's REST fallback returns the raw…]] - rationale - tests/test_live_execution.py
- [[Regression two separate open live positions sharing a ticker (two distinct…]] - rationale - tests/test_live_execution.py
- [[TestCheckLiveModelExits]] - code - tests/test_live_execution.py
- [[TestCheckLivePositionExits]] - code - tests/test_live_execution.py
- [[The fan-out safety property this ticket-level by_ticker grouping exists for…]] - rationale - tests/test_live_execution.py
- [[_check_live_position_exits()]] - code - order_executor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_144
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 45]]
- 6 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 4 edges to [[_COMMUNITY_Community 111]]
- 2 edges to [[_COMMUNITY_Community 145]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 164]]
- 1 edge to [[_COMMUNITY_Community 159]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]

## Top bridge nodes
- [[_check_live_position_exits()]] - degree 20, connects to 8 communities
- [[TestCheckLivePositionExits]] - degree 12, connects to 2 communities
- [[TestCheckLiveModelExits]] - degree 9, connects to 2 communities
- [[dot-test_missing_entry_prob_is_skipped()]] - degree 3, connects to 1 community
- [[dot-test_model_flip_beyond_threshold_triggers_exit()]] - degree 3, connects to 1 community