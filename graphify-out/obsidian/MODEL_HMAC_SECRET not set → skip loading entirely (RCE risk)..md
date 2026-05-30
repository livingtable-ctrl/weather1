---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Module: tests"
location: "L89"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# MODEL_HMAC_SECRET not set → skip loading entirely (RCE risk).

## Connections
- [[.test_no_secret_set_returns_empty()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests