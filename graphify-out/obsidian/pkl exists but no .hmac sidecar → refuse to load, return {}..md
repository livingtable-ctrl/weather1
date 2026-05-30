---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Module: tests"
location: "L49"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# pkl exists but no .hmac sidecar → refuse to load, return {}.

## Connections
- [[.test_missing_hmac_sidecar_returns_empty()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests