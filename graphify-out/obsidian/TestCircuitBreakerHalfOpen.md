---
source_file: "tests/test_phase3_batch_b.py"
type: "code"
community: "Community 84"
location: "L173"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_84
---

# TestCircuitBreakerHalfOpen

## Connections
- [[dot-test_execute_probe_failure_reopens()]] - `method` [EXTRACTED]
- [[dot-test_execute_probe_success_closes_circuit()]] - `method` [EXTRACTED]
- [[dot-test_failed_probe_applies_backoff()]] - `method` [EXTRACTED]
- [[dot-test_failed_probe_reopens_circuit()]] - `method` [EXTRACTED]
- [[dot-test_half_open_allows_one_probe()]] - `method` [EXTRACTED]
- [[dot-test_half_open_blocks_subsequent_callers()]] - `method` [EXTRACTED]
- [[dot-test_successful_probe_closes_circuit()]] - `method` [EXTRACTED]
- [[dot-test_trip_count_increments_on_probe_failure()]] - `method` [EXTRACTED]
- [[CircuitBreaker]] - `uses` [INFERRED]
- [[CircuitOpenError]] - `uses` [INFERRED]
- [[P3-6 HALF-OPEN must allow exactly one probe and reopen on probe failure.]] - `rationale_for` [EXTRACTED]
- [[Phase 3 Batch B Circuit Breaker Tests]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_84