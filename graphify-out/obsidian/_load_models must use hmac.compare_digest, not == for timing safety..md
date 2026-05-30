---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Module: tests"
location: "L114"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# _load_models must use hmac.compare_digest, not == for timing safety.

## Connections
- [[.test_compare_digest_used_not_equality()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests