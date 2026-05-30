---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Module: tests"
location: "L77"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# HMAC signed with different secret → mismatch → return {}.

## Connections
- [[.test_wrong_secret_returns_empty()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests