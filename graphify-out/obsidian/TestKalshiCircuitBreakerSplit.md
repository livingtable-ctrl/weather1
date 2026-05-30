---
source_file: "tests/test_phase3_batch_b.py"
type: "code"
community: "Module: tests"
location: "L75"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# TestKalshiCircuitBreakerSplit

## Connections
- [[.test_delete_uses_write_cb()]] - `method` [EXTRACTED]
- [[.test_get_uses_read_cb()]] - `method` [EXTRACTED]
- [[.test_post_uses_write_cb()]] - `method` [EXTRACTED]
- [[.test_read_and_write_cbs_are_separate_objects()]] - `method` [EXTRACTED]
- [[.test_read_cb_name_distinct_from_write()]] - `method` [EXTRACTED]
- [[.test_read_failures_do_not_open_write_cb()]] - `method` [EXTRACTED]
- [[CircuitBreaker]] - `uses` [INFERRED]
- [[CircuitOpenError]] - `uses` [INFERRED]
- [[P3-5 Read failures must not block write operations.]] - `rationale_for` [EXTRACTED]
- [[test_phase3_batch_b.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests