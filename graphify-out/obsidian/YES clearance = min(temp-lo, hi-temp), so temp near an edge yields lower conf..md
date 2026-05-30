---
source_file: "tests/test_phase2_batch_d.py"
type: "rationale"
community: "Module: tests"
location: "L82"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# YES clearance = min(temp-lo, hi-temp), so temp near an edge yields lower conf.

## Connections
- [[.test_yes_clearance_uses_min_distance_to_edge()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests