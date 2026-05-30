---
source_file: "tests/test_phase2_batch_j.py"
type: "rationale"
community: "Module: tests"
location: "L139"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# fetch_metar must not fabricate a timestamp — None obsTime → return None.

## Connections
- [[.test_null_obstime_is_rejected_not_fabricated()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests