---
type: community
cohesion: 0.11
members: 29
---

# Community 84

**Cohesion:** 0.11 - loosely connected
**Members:** 29 nodes

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
- [[CircuitOpenError]] - code - circuit_breaker.py
- [[Create a non-persisting CircuitBreaker for tests.]] - rationale - tests/test_phase3_batch_b.py
- [[Exception]] - code
- [[P3-4 execute() provides automatic check → call → record protection.]] - rationale - tests/test_phase3_batch_b.py
- [[P3-6 HALF-OPEN must allow exactly one probe and reopen on probe failure.]] - rationale - tests/test_phase3_batch_b.py
- [[Phase 3 Batch B Circuit Breaker Tests]] - code - tests/test_phase3_batch_b.py
- [[Phase 3 Batch B regression tests P3-4, P3-5, P3-6.]] - rationale - tests/test_phase3_batch_b.py
- [[Raised when a circuit breaker is open (source is down).]] - rationale - circuit_breaker.py
- [[Second is_open() call while probe is in flight must be blocked.]] - rationale - tests/test_phase3_batch_b.py
- [[TestCircuitBreakerExecute]] - code - tests/test_phase3_batch_b.py
- [[TestCircuitBreakerHalfOpen]] - code - tests/test_phase3_batch_b.py
- [[_cb()]] - code - tests/test_phase3_batch_b.py
- [[execute() probe raises → circuit reopens.]] - rationale - tests/test_phase3_batch_b.py
- [[execute() probe succeeds → circuit closes.]] - rationale - tests/test_phase3_batch_b.py
- [[kalshi_client._kalshi_cb_read  _kalshi_cb_write  _request_with_retry]] - code - kalshi_client.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_84
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 44]]
- 4 edges to [[_COMMUNITY_Community 226]]
- 2 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 95]]
- 1 edge to [[_COMMUNITY_Community 351]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]

## Top bridge nodes
- [[CircuitOpenError]] - degree 12, connects to 6 communities
- [[Phase 3 Batch B Circuit Breaker Tests]] - degree 10, connects to 3 communities
- [[_cb()]] - degree 17, connects to 1 community
- [[TestCircuitBreakerHalfOpen]] - degree 12, connects to 1 community
- [[TestCircuitBreakerExecute]] - degree 10, connects to 1 community