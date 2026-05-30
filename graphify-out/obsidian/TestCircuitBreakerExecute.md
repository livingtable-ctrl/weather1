---
source_file: "tests/test_phase3_batch_b.py"
type: "code"
community: "Module: tests"
location: "L24"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# TestCircuitBreakerExecute

## Connections
- [[.test_execute_calls_fn_when_closed()]] - `method` [EXTRACTED]
- [[.test_execute_opens_circuit_after_threshold_failures()]] - `method` [EXTRACTED]
- [[.test_execute_passes_args_and_kwargs()]] - `method` [EXTRACTED]
- [[.test_execute_raises_circuit_open_error_when_open()]] - `method` [EXTRACTED]
- [[.test_execute_records_failure_and_reraises_on_exception()]] - `method` [EXTRACTED]
- [[.test_execute_records_success_on_fn_return()]] - `method` [EXTRACTED]
- [[CircuitBreaker]] - `uses` [INFERRED]
- [[CircuitOpenError]] - `uses` [INFERRED]
- [[P3-4 execute() provides automatic check → call → record protection.]] - `rationale_for` [EXTRACTED]
- [[test_phase3_batch_b.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests