---
type: community
cohesion: 0.13
members: 20
---

# Community 157

**Cohesion:** 0.13 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-setup_method()_10]] - code - tests/test_live_execution.py
- [[dot-setup_method()_11]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_5]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_6]] - code - tests/test_live_execution.py
- [[dot-test_get_order_failure_falls_back_to_plain_canceled()]] - code - tests/test_live_execution.py
- [[dot-test_partial_fill_cancel_promotes_to_filled()]] - code - tests/test_live_execution.py
- [[dot-test_raw_api_status_preserved_when_still_resting()]] - code - tests/test_live_execution.py
- [[dot-test_returns_canceled_zero_on_clean_cancel()]] - code - tests/test_live_execution.py
- [[dot-test_returns_filled_with_count_on_partial_fill()]] - code - tests/test_live_execution.py
- [[dot-test_returns_sentinel_negative_one_when_verification_query_fails()]] - code - tests/test_live_execution.py
- [[dot-test_zero_fill_cancel_stays_canceled()]] - code - tests/test_live_execution.py
- [[A cancel that hasn't propagated yet (Kalshi still reports resting) must…]] - rationale - tests/test_live_execution.py
- [[F9 followup _finalize_cancel() is the shared post-cancel_order() fill-check…]] - rationale - tests/test_live_execution.py
- [[Fill state genuinely unknown here -- callers must fail closed (never place a…]] - rationale - tests/test_live_execution.py
- [[Record the outcome of a cancel_order() call this bot just initiated. F9…]] - rationale - order_executor.py
- [[TestFinalizeCancel]] - code - tests/test_live_execution.py
- [[TestFinalizeCancelReturnValue]] - code - tests/test_live_execution.py
- [[The cancel itself already happened -- a failed follow-up query must not leave…]] - rationale - tests/test_live_execution.py
- [[_finalize_cancel now returns (status, fill_count, raw_api_status) so…]] - rationale - tests/test_live_execution.py
- [[_finalize_cancel()]] - code - order_executor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_157
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 45]]
- 3 edges to [[_COMMUNITY_Community 111]]
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 300]]
- 1 edge to [[_COMMUNITY_Community 67]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]

## Top bridge nodes
- [[_finalize_cancel()]] - degree 16, connects to 6 communities
- [[TestFinalizeCancelReturnValue]] - degree 10, connects to 2 communities
- [[TestFinalizeCancel]] - degree 9, connects to 2 communities