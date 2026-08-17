---
type: community
cohesion: 0.13
members: 23
---

# Community 139

**Cohesion:** 0.13 - loosely connected
**Members:** 23 nodes

## Members
- [[dot-test_execute_calls_fn_when_closed()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_opens_circuit_after_threshold_failures()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_passes_args_and_kwargs()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_probe_failure_reopens()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_probe_success_closes_circuit()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_raises_circuit_open_error_when_open()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_records_failure_and_reraises_on_exception()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_execute_records_success_on_fn_return()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_failed_probe_applies_backoff()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_failed_probe_reopens_circuit()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_half_open_allows_one_probe()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_half_open_blocks_subsequent_callers()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_successful_probe_closes_circuit()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_trip_count_increments_on_probe_failure()]] - code - tests/test_phase3_batch_b.py
- [[Create a non-persisting CircuitBreaker for tests.]] - rationale - tests/test_phase3_batch_b.py
- [[P3-4 execute() provides automatic check → call → record protection.]] - rationale - tests/test_phase3_batch_b.py
- [[P3-6 HALF-OPEN must allow exactly one probe and reopen on probe failure.]] - rationale - tests/test_phase3_batch_b.py
- [[Second is_open() call while probe is in flight must be blocked.]] - rationale - tests/test_phase3_batch_b.py
- [[TestCircuitBreakerExecute]] - code - tests/test_phase3_batch_b.py
- [[TestCircuitBreakerHalfOpen]] - code - tests/test_phase3_batch_b.py
- [[_cb()]] - code - tests/test_phase3_batch_b.py
- [[execute() probe raises → circuit reopens.]] - rationale - tests/test_phase3_batch_b.py
- [[execute() probe succeeds → circuit closes.]] - rationale - tests/test_phase3_batch_b.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_139
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 7]]
- 3 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[_cb()]] - degree 17, connects to 2 communities
- [[TestCircuitBreakerHalfOpen]] - degree 12, connects to 2 communities
- [[TestCircuitBreakerExecute]] - degree 10, connects to 2 communities