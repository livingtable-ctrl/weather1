---
source_file: "tests/test_debug_fixes.py"
type: "rationale"
community: "Module: tests"
location: "L95"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# was_traded can go from 0 → 1 via log_analysis_attempt after batch insert.

## Connections
- [[.test_batch_can_set_was_traded_true()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests