---
source_file: "tests/test_hmac_bias.py"
type: "rationale"
community: "Community 120"
location: "L89"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Community_120
---

# MODEL_HMAC_SECRET not set → skip loading entirely (RCE risk).

## Connections
- [[dot-test_no_secret_set_returns_empty()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Community_120