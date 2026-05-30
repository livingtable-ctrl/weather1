---
source_file: "tests/test_idempotency.py"
type: "rationale"
community: "Module: tests"
location: "L92"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Omitting cycle produces a random (non-deterministic) client_order_id.

## Connections
- [[.test_no_cycle_uses_random_id()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests