---
source_file: "tests/test_infrastructure.py"
type: "rationale"
community: "Circuit Breaker & Session Retry Infrastructure"
location: "L368"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Circuit_Breaker__Session_Retry_Infrastructure
---

# If both primary and /tmp writes fail, AtomicWriteError is raised.

## Connections
- [[test_atomic_write_raises_on_double_failure()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Circuit_Breaker__Session_Retry_Infrastructure