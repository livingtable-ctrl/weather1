---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Module: tests"
location: "L63"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# HMAC mismatch (tampered pkl) → refuse to load, return {}.

## Connections
- [[.test_tampered_pkl_returns_empty()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests