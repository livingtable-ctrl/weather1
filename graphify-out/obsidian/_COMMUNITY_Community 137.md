---
type: community
cohesion: 0.12
members: 23
---

# Community 137

**Cohesion:** 0.12 - loosely connected
**Members:** 23 nodes

## Members
- [[dot-_open_position_row()]] - code - tests/test_live_execution.py
- [[dot-_open_position_row()_1]] - code - tests/test_live_execution.py
- [[dot-setup_method()_10]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_7]] - code - tests/test_live_execution.py
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
- [[Regression _get_current_book's REST fallback returns the raw…]] - rationale - tests/test_live_execution.py
- [[Regression two separate open live positions sharing a ticker (two distinct…]] - rationale - tests/test_live_execution.py
- [[Shared execution_log DB isolation for the live-position-protection test classes…]] - rationale - tests/test_live_execution.py
- [[TestCheckLiveModelExits]] - code - tests/test_live_execution.py
- [[TestCheckLivePositionExits]] - code - tests/test_live_execution.py
- [[The fan-out safety property this ticket-level by_ticker grouping exists for…]] - rationale - tests/test_live_execution.py
- [[_LiveDBTestBase]] - code - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_137
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Community 3]]
- 10 edges to [[_COMMUNITY_Community 12]]
- 2 edges to [[_COMMUNITY_Community 119]]

## Top bridge nodes
- [[_LiveDBTestBase]] - degree 11, connects to 2 communities
- [[TestCheckLivePositionExits]] - degree 12, connects to 1 community
- [[TestCheckLiveModelExits]] - degree 9, connects to 1 community
- [[dot-test_stop_loss_and_breakeven_are_mutually_exclusive_same_cycle()]] - degree 4, connects to 1 community
- [[dot-test_stop_loss_fires_on_rest_fallback_integer_cents_book()]] - degree 4, connects to 1 community