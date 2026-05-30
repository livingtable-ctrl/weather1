---
source_file: "tests/test_debug_fixes.py"
type: "rationale"
community: "Module: tests"
location: "L202"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# entry_prob=0.0 on an open trade must not be replaced by 0.5 in covariance math.

## Connections
- [[.test_covariance_kelly_uses_zero_entry_prob_not_half()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests