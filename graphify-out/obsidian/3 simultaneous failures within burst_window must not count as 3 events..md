---
source_file: "tests/test_circuit_breaker.py"
type: "rationale"
community: "Module: tests"
location: "L132"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# 3 simultaneous failures within burst_window must not count as 3 events.

## Connections
- [[.test_parallel_failures_count_as_one_event()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests