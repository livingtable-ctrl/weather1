---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Community 151"
location: "L114"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Community_151
---

# _load_models must use hmac.compare_digest, not == for timing safety.

## Connections
- [[dot-test_compare_digest_used_not_equality()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Community_151