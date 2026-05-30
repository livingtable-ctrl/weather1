---
source_file: "tests/test_circuit_breaker.py"
type: "rationale"
community: "Module: tests"
location: "L109"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Backoff accumulates across open/close cycles — success does not reset it.

## Connections
- [[.test_backoff_persists_through_success()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests