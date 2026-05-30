---
source_file: "tests/test_idempotency.py"
type: "rationale"
community: "Module: tests"
location: "L114"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# If _post raises but the order exists on exchange, return it without re-raising.

## Connections
- [[.test_returns_existing_order_when_post_fails_but_order_landed()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests