---
type: community
cohesion: 0.09
members: 32
---

# Community 73

**Cohesion:** 0.09 - loosely connected
**Members:** 32 nodes

## Members
- [[dot-_seed_row()]] - code - tests/test_live_execution.py
- [[dot-setup_method()_37]] - code - tests/test_live_execution.py
- [[dot-setup_method()_38]] - code - tests/test_live_execution.py
- [[dot-setup_method()_39]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_28]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_29]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_30]] - code - tests/test_live_execution.py
- [[dot-test_false_when_cancel_call_itself_raises()]] - code - tests/test_live_execution.py
- [[dot-test_false_when_order_still_resting_despite_zero_fill_count()]] - code - tests/test_live_execution.py
- [[dot-test_false_when_partial_fill_detected()]] - code - tests/test_live_execution.py
- [[dot-test_false_when_post_cancel_verification_query_fails()]] - code - tests/test_live_execution.py
- [[dot-test_get_order_failure_falls_back_to_plain_canceled()]] - code - tests/test_live_execution.py
- [[dot-test_partial_fill_cancel_promotes_to_filled()]] - code - tests/test_live_execution.py
- [[dot-test_raw_api_status_preserved_when_still_resting()]] - code - tests/test_live_execution.py
- [[dot-test_returns_canceled_zero_on_clean_cancel()]] - code - tests/test_live_execution.py
- [[dot-test_returns_filled_with_count_on_partial_fill()]] - code - tests/test_live_execution.py
- [[dot-test_returns_sentinel_negative_one_when_verification_query_fails()]] - code - tests/test_live_execution.py
- [[dot-test_true_when_confirmed_unfilled()]] - code - tests/test_live_execution.py
- [[dot-test_zero_fill_cancel_stays_canceled()]] - code - tests/test_live_execution.py
- [[A cancel that hasn't propagated yet (Kalshi still reports resting) must…]] - rationale - tests/test_live_execution.py
- [[A cancel that hasn't propagated yet (Kalshi still reports resting, zero fills…]] - rationale - tests/test_live_execution.py
- [[Cancel a resting order and return True only if verified both genuinely unfilled…]] - rationale - order_executor.py
- [[F9 followup _finalize_cancel() is the shared post-cancel_order() fill-check…]] - rationale - tests/test_live_execution.py
- [[Fill state genuinely unknown here -- callers must fail closed (never place a…]] - rationale - tests/test_live_execution.py
- [[Record the outcome of a cancel_order() call this bot just initiated. F9…]] - rationale - order_executor.py
- [[TestCancelAndVerifySafeToReplace]] - code - tests/test_live_execution.py
- [[TestFinalizeCancel]] - code - tests/test_live_execution.py
- [[TestFinalizeCancelReturnValue]] - code - tests/test_live_execution.py
- [[The cancel itself already happened -- a failed follow-up query must not leave…]] - rationale - tests/test_live_execution.py
- [[_cancel_and_verify_safe_to_replace()]] - code - order_executor.py
- [[_finalize_cancel now returns (status, fill_count, raw_api_status) so…]] - rationale - tests/test_live_execution.py
- [[_finalize_cancel()]] - code - order_executor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_73
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Community 12]]
- 4 edges to [[_COMMUNITY_Community 1]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 74]]

## Top bridge nodes
- [[_finalize_cancel()]] - degree 16, connects to 4 communities
- [[_cancel_and_verify_safe_to_replace()]] - degree 10, connects to 3 communities
- [[TestCancelAndVerifySafeToReplace]] - degree 11, connects to 1 community
- [[TestFinalizeCancelReturnValue]] - degree 10, connects to 1 community
- [[TestFinalizeCancel]] - degree 9, connects to 1 community